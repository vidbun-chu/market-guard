# -*- coding: utf-8 -*-
"""
market_guard.datafeed — 多源容错行情抓取层

设计要点（来源于生产环境的踩坑经验）：
  1. 多源回退：单一数据源随时会断连（限流、接口下线、IP 封禁），
     因此每个数据源独立实现 fetch()，由 DataFeed 按优先级自动回退。
  2. 前复权统一口径：所有 K 线一律取 qfq（��复权），
     否则跨源比较与均线计算会出现系统性偏差。
  3. 统一返回结构：无论哪个源，都归一化为 Bar 列表，
     上层（indicators/stoploss）不感知数据源差异。
  4. 明确的失败语义：全源失败时抛 DataUnavailable，
     绝不静默返回空列表——静默空值会让下游算出"均线未破"的假信号。

内置数据源（按优先级）：
  · tencent   web.ifzq.gtimg.cn  —— 日/周/月 K 线，实测稳定
  · sina      finance.sina.com.cn —— 日 K 线，实测稳定
  · eastmoney push2his.eastmoney.com —— 备用，部分网络环境不可达
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable, List, Optional

__all__ = ["Bar", "DataFeed", "DataUnavailable", "tencent", "sina", "eastmoney"]


class DataUnavailable(RuntimeError):
    """所有数据源均不可用。调用方必须显式处理，不可静默吞掉。"""


@dataclass(frozen=True)
class Bar:
    """单根 K 线。前复权口径。"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# HTTP 基础设施
# --------------------------------------------------------------------------

def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _get(url: str, referer: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer}
    )
    return urllib.request.urlopen(req, timeout=timeout, context=_ctx()).read()


def _rows_to_bars(rows: Iterable, has_volume: bool = True) -> List[Bar]:
    """把各家源的原始行统一成 Bar。"""
    out: List[Bar] = []
    for r in rows:
        try:
            # 腾讯/东财: [日期, 开, 收, 高, 低, 量]
            # 新浪:     [日期, 开, 收, 高, 低, 量]  (顺序一致)
            out.append(Bar(
                date=str(r[0]),
                open=float(r[1]), close=float(r[2]),
                high=float(r[3]), low=float(r[4]),
                volume=float(r[5]) if has_volume and len(r) > 5 else 0.0,
            ))
        except (IndexError, TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------
# 数据源实现
# --------------------------------------------------------------------------

def tencent(code: str, period: str = "day", count: int = 320) -> List[Bar]:
    """腾讯财经。日线最稳，周/月线需注意未走完的当月/当周。"""
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},{period},,,{count},qfq")
    js = json.loads(_get(url, "https://stockapp.finance.qq.com/").decode("utf-8", "ignore"))
    node = (js.get("data") or {}).get(code) or (js.get("data") or {})
    rows = node.get(period) or node.get("qfq" + period) or []
    return _rows_to_bars(rows)


def sina(code: str, period: str = "day", count: int = 320) -> List[Bar]:
    """新浪。日线可靠；scale 参数限制在分钟级，日线固定 240。"""
    scale = {"day": "240", "week": "1200", "month": "7200"}.get(period, "240")
    url = ("https://quotes.sina.cn/cn/api/json_v2.php/"
           f"CN_MarketDataService.getKLineData?symbol={code}"
           f"&scale={scale}&ma=no&datalen={count}")
    js = json.loads(_get(url, "https://finance.sina.com.cn/").decode("utf-8", "ignore"))
    rows = js.get("result") or []
    return _rows_to_bars(rows)


def eastmoney(code: str, period: str = "day", count: int = 320) -> List[Bar]:
    """东财。secid 规则：沪市 1.xxxxxx，深市/创业板 0.xxxxxx。"""
    market = "1" if code[:2] in ("sh", "6") or code.startswith("6") else "0"
    plain = code[2:] if code[:2] in ("sh", "sz") else code
    period_id = {"day": "101", "week": "102", "month": "103"}.get(period, "101")
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={market}.{plain}&klt={period_id}&fqt=1"
           f"&lmt={count}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56")
    js = json.loads(_get(url, "https://quote.eastmoney.com/").decode("utf-8", "ignore"))
    klines = ((js.get("data") or {}).get("klines") or [])
    rows = [k.split(",") for k in klines]
    # 东财顺序: 日期,开,收,高,低,量,额
    return _rows_to_bars(rows)


# --------------------------------------------------------------------------
# 调度器
# --------------------------------------------------------------------------

_SOURCES = {"tencent": tencent, "sina": sina, "eastmoney": eastmoney}


class DataFeed:
    """多源容错抓取器。

    用法:
        feed = DataFeed()
        bars = feed.get("600519", "day")          # 自动回退
        bars = feed.get("600519", "day", only="sina")

    顺序回退是特性，不是兜底掩盖：只有当所有源都失败才抛异常，
    避免上游误以为"没数据=没风险"。
    """

    def __init__(self, order: Optional[List[str]] = None, verbose: bool = False):
        self.order = order or ["tencent", "sina", "eastmoney"]
        self.verbose = verbose
        self.last_used: Optional[str] = None

    def get(self, code: str, period: str = "day", count: int = 320,
            only: Optional[str] = None) -> List[Bar]:
        sources = [only] if only else self.order
        errors = []
        for name in sources:
            fn = _SOURCES.get(name)
            if fn is None:
                errors.append(f"{name}: 未知数据源")
                continue
            try:
                bars = fn(code, period, count)
                if bars:
                    self.last_used = name
                    if self.verbose:
                        print(f"[datafeed] {code} {period} ← {name} ({len(bars)} bars)")
                    return bars
                errors.append(f"{name}: 返回空")
            except Exception as exc:  # noqa: BLE001 — 需捕获全部异常继续回退
                errors.append(f"{name}: {type(exc).__name__} {exc}")
        raise DataUnavailable(
            f"所有数据源均失败 code={code} period={period}\n  " + "\n  ".join(errors)
        )

    def get_many(self, codes: List[str], period: str = "day",
                 count: int = 320) -> dict:
        """批量抓取。单只失败不影响整体（返回 dict，缺失键即失败）。"""
        out = {}
        for c in codes:
            try:
                out[c] = self.get(c, period, count)
            except DataUnavailable:
                continue
        return out
