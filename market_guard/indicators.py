# -*- coding: utf-8 -*-
"""
market_guard.indicators — 趋势引擎（均线系统）

体系均线清单（不可自行增删）：
    日线  5 / 10 / 20 / 30 / 55 / 60 / 89 / 120 / 144 / 250
    周线  5 / 10 / 20 / 30 / 89 / 120 / 144 / 250
    月线  5 / 10 / 20

★ 重要口径声明（版本 2.x 起）：
    早期版本提供过"现价 ÷ 5 月均线比值 → 四档定位"的函数，
    但该表格在实际交易语料中缺乏依据，属于后验归纳，
    已在 2.0 移除。本模块只做「均线位置关系」的客观计算，
    大周期定位请用 cycle.py 的定性三问法，不要用比值算档位。

核心概念：
    Stage   —— 个股相对 5 月线的位置状态（站上 / 首破 / 连续破位）
    MA_SET  —— 体系均线全清单
    support_lines() —— 提取个股当前所处的均线支撑/压力位
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .datafeed import Bar

__all__ = [
    "MA_DAILY", "MA_WEEKLY", "MA_MONTHLY", "MA_SET",
    "Stage", "sma", "ma", "ma_series", "ma5_month", "trend_stage",
    "support_lines", "resonance", "avg_deviation",
]

MA_DAILY = (5, 10, 20, 30, 55, 60, 89, 120, 144, 250)
MA_WEEKLY = (5, 10, 20, 30, 89, 120, 144, 250)
MA_MONTHLY = (5, 10, 20)
MA_SET = frozenset(MA_DAILY + MA_WEEKLY + MA_MONTHLY)

# 个股 Stage 常量
STAGE_ABOVE = "above"    # 站上 5 月线
STAGE_FIRST = "first"    # 首次跌破（第一根，小心）
STAGE_OFF2 = "off2"      # 连续两月收在 5 月线下方（确认，转弱）


class Stage:
    ABOVE = STAGE_ABOVE
    FIRST = STAGE_FIRST
    OFF2 = STAGE_OFF2


# --------------------------------------------------------------------------
# 基础均线计算
# --------------------------------------------------------------------------

def sma(values: Sequence[float], n: int) -> Optional[float]:
    """简单移动平均。数据不足返回 None（不是 0，避免下游误判为"极低"）。"""
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def ma(bars: Sequence[Bar], n: int) -> Optional[float]:
    """对 Bar 序列求 n 日均线（以收盘价）。"""
    return sma([b.close for b in bars], n)


def ma_series(bars: Sequence[Bar], n: int) -> List[Optional[float]]:
    """逐点均线序列，长度与 bars 一致，前 n-1 位为 None。用于画线/回测。"""
    closes = [b.close for b in bars]
    out: List[Optional[float]] = [None] * len(closes)
    running = 0.0
    for i, c in enumerate(closes):
        running += c
        if i >= n:
            running -= closes[i - n]
        if i >= n - 1:
            out[i] = running / n
    return out


def ma5_month(bars: Sequence[Bar]) -> Optional[float]:
    """月线 5 月均线。bars 必须是月线序列。"""
    return ma(bars, 5)


# --------------------------------------------------------------------------
# 月线阶段判定（趋势引擎核心）
# --------------------------------------------------------------------------

def _rolling_ma5(closes: Sequence[float], end_idx: int) -> float:
    """截至第 end_idx 根（不含）的滚动 5 月均线。"""
    window = closes[max(0, end_idx - 5):end_idx]
    return sum(window) / len(window)


def trend_stage(month_bars: Sequence[Bar]) -> Dict:
    """
    判定个股相对 5 月线的阶段状态。

    规则（第一根跌破要小心，第二根基本确认）：
      · 现价 > 5月线                      → above
      · 最新完整月收盘 < 5月线，但此前未破  → first
      · 连续 2 个完整月收盘 < 各自当时的5月线 → off2

    ★ 实现要点：连续破位的判定必须**逐月用当月自己的 5 月线**，
      而不是拿最新的 5 月线去回溯比。否则当 5 月线本身下移时，
      早期月份的比较会失真，导致 off2 被漏判（实测过该 bug）。

    返回字段：
      stage       above / first / off2
      price       最新收盘
      m5          最新 5 月均线
      hold_run    连续站上 5 月线的月数（不含当月）
      below_run   连续跌破 5 月线的月数（不含当月）
    """
    if len(month_bars) < 6:
        raise ValueError("月线数据不足 6 根，无法判定阶段（至少需 5+1 根）")

    closes = [b.close for b in month_bars]
    price = closes[-1]
    m5 = sum(closes[-5:]) / 5.0

    # 逐月滚动判定（关键：不使用固定 m5）
    flags: List[bool] = []   # True = 当月收盘在其当时 5 月线之上
    for i in range(5, len(closes)):
        flags.append(closes[i] > _rolling_ma5(closes, i))

    # flags 对应 closes[5:]，其中最后一个是"当月"
    hold_run = 0
    for f in reversed(flags[:-1]):
        if f:
            hold_run += 1
        else:
            break
    below_run = 0
    for f in reversed(flags[:-1]):
        if not f:
            below_run += 1
        else:
            break

    if price >= m5:
        stage = Stage.ABOVE
    elif below_run >= 2:
        stage = Stage.OFF2
    else:
        stage = Stage.FIRST

    return {
        "stage": stage,
        "price": round(price, 4),
        "m5": round(m5, 4),
        "hold_run": hold_run,
        "below_run": below_run,
    }


# --------------------------------------------------------------------------
# 支撑/压力位提取
# --------------------------------------------------------------------------

def support_lines(bars: Sequence[Bar], periods: Sequence[int] = MA_DAILY) -> List[Dict]:
    """
    提取当前价格相对各均线的位置关系。

    返回每条在算的均线：{period, value, distance_pct, role}
      role = support（现价在其上方，回踩此线可观察支撑）
           = pressure（现价在其下方，反弹至此线遇阻）
    """
    price = bars[-1].close
    out = []
    for n in periods:
        v = ma(bars, n)
        if v is None:
            continue
        out.append({
            "period": n,
            "value": round(v, 4),
            "distance_pct": round((price - v) / v * 100, 2),
            "role": "support" if price >= v else "pressure",
        })
    return out


def resonance(bars: Sequence[Bar],
              periods: Sequence[int] = (20, 60, 144)) -> Dict:
    """
    共振检测：多条均线是否密集靠拢。
    多条均线交汇处支撑力度更强；反之若各线分散且现价远离，则无共振。
    """
    px = bars[-1].close
    vals = []
    for n in periods:
        v = ma(bars, n)
        if v is not None:
            vals.append((n, v))
    if len(vals) < 2:
        return {"resonant": False, "reason": "均线数据不足"}

    spread = (max(v for _, v in vals) - min(v for _, v in vals)) / px * 100
    # 偏离最远的一条均线距离现价的百分比
    dists = [abs(px - v) / px * 100 for _, v in vals]
    near = min(dists)

    if spread <= 3.0 and near <= 2.0:
        return {"resonant": True, "spread_pct": round(spread, 2),
                "nearest_pct": round(near, 2),
                "lines": [n for n, _ in vals],
                "note": "均线密集且现价贴近，具共振观察价值"}
    return {"resonant": False, "spread_pct": round(spread, 2),
            "nearest_pct": round(near, 2), "lines": [n for n, _ in vals]}


def avg_deviation(bars: Sequence[Bar], n: int = 5) -> Optional[float]:
    """现价相对 n 日均线的偏离百分比。
    用于判断"恐慌性偏离"——大幅负偏离常对应情绪极端的错杀。
    """
    v = ma(bars, n)
    if not v:
        return None
    return round((bars[-1].close - v) / v * 100, 2)
