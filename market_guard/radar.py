# -*- coding: utf-8 -*-
"""
market_guard.radar — 账户级风险雷达

把 datafeed / indicators / stoploss 串成一个可直接调用的风控入口：

    from market_guard import RiskRadar
    radar = RiskRadar(account_json="account.json")   # 或直接传 dict
    report = radar.scan()
    print(report.to_text())

报告包含：
    · 市值回撤与止损触发（百分比轨）
    · 维持担保比例与杠杆风险（融资账户专有）
    · 单只集中度（体系上限：单只 3 成）
    · 持仓均线结构（结构轨）
    · 减仓优先级清单（速率轨）

★ 免责声明：本模块只做计算与提示，不连接任何券商接口，不下单。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .datafeed import DataFeed, DataUnavailable
from .indicators import trend_stage, support_lines, avg_deviation
from .stoploss import (Position, Severity, StoplossEngine, default_policy)

__all__ = ["AccountSnapshot", "RiskReport", "RiskRadar"]

# 融资账户的维持担保比例警戒线
MARGIN_CALL = 150.0   # 强平线
MARGIN_DANGER = 200.0
MARGIN_WARN = 300.0   # 体系建议的"立即处理"警戒
SINGLE_MAX = 0.30     # 单只上限 3 成


@dataclass
class AccountSnapshot:
    """账户快照（脱敏：不要求成本价，成本本就不该参与决策）。"""
    date: str = ""
    total_asset: float = 0.0     # 总资产（含负债）
    net_asset: float = 0.0       # 净资产
    total_debt: float = 0.0      # 融资负债
    market_value: float = 0.0    # 持仓市值
    cash: float = 0.0
    holdings: List[Dict] = field(default_factory=list)  # [{code,name,shares,price,weight?}]

    @property
    def position_ratio(self) -> float:
        return self.market_value / self.net_asset if self.net_asset else 0.0

    @property
    def leverage_ratio(self) -> float:
        """维持担保比例 = 总资产 / 负债，单位为**百分数**。

        ⚠️ 单位约定：返回百分数（433.3 表示 433.3%），
           便于与券商 App 显示一致、也便于与 150/200/300 阈值直接比较。
           不要与"倍数"混用，否则会出现 291% 显示成 2.91% 的问题。
        """
        if not self.total_debt:
            return float("inf")
        return self.total_asset / self.total_debt * 100.0

    @classmethod
    def from_json(cls, path: str) -> "AccountSnapshot":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        acc = d.get("account", d)
        return cls(
            date=d.get("date", ""),
            total_asset=acc.get("totalAsset", 0.0),
            net_asset=acc.get("netAsset", 0.0),
            total_debt=acc.get("totalDebt", 0.0),
            market_value=acc.get("marketValue", 0.0),
            cash=acc.get("available", 0.0),
            holdings=d.get("holdings", []),
        )


@dataclass
class RiskReport:
    """风控报告。"""
    date: str
    drawdown_pct: float
    severity: str
    position_ratio: float
    leverage_ratio: Optional[float]
    margin_status: str
    triggers: List[Dict]
    concentration: List[Dict]
    structure: List[Dict]
    action_plan: List[Dict]
    avoidance: str
    data_warnings: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        L = []
        bar = "=" * 60
        L.append(bar)
        L.append(f" 风控雷达 · {self.date}")
        L.append(bar)
        L.append(f" 市值回撤      {self.drawdown_pct:.2f}%")
        L.append(f" 仓位          {self.position_ratio:.1%}")
        if self.leverage_ratio and self.leverage_ratio != float("inf"):
            L.append(f" 维持担保      {self.leverage_ratio:.2f}%  ({self.margin_status})")
        if self.leverage_ratio == float("inf"):
            L.append(" 维持担保      无融资负债")
        L.append(f" 最高级别      {self.severity.upper()}")
        L.append("")

        if self.triggers:
            L.append("【触发项】")
            for t in self.triggers:
                L.append(f"  · [{t['track']}] {t['message']}")
                if t.get("hint"):
                    L.append(f"      → {t['hint']}")
            L.append("")

        if self.concentration:
            over = [c for c in self.concentration if c["over_limit"]]
            L.append("【集中度】")
            for c in self.concentration[:8]:
                flag = "  ← 超单只上限" if c["over_limit"] else ""
                L.append(f"  {c['name']:<10} {c['weight']:>6.1%}{flag}")
            if over:
                L.append(f"  共 {len(over)} 只超 3 成上限")
            L.append("")

        if self.structure:
            L.append("【结构（均线）】")
            for s in self.structure:
                L.append(f"  {s['name']:<10} {s['stage']:<6} "
                         f"5月线 {s['m5']} 现价 {s['price']}")
            L.append("")

        if self.action_plan:
            L.append("【减仓清单（按 仓位×波动 排序）】")
            for a in self.action_plan:
                L.append(f"  {a['name']}({a['code']}) "
                         f"减 {a['reduce_value']:,.0f}  "
                         f"{a['weight_before']:.1%} → {a['weight_after']:.1%}")
                L.append(f"      理由：{a['reason']}")
            L.append("")

        if self.data_warnings:
            L.append("【数据提示】")
            for w in self.data_warnings:
                L.append(f"  ! {w}")
            L.append("")

        L.append(f"【建议】{self.avoidance}")
        L.append(bar)
        L.append("本报告由 market_guard 生成，仅为纪律提示，不构成投资建议。")
        L.append("不连接券商、不下单。决策与风险由使用者自负。")
        return "\n".join(L)

    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "drawdown_pct": self.drawdown_pct,
            "severity": self.severity,
            "position_ratio": round(self.position_ratio, 4),
            "leverage_ratio": (round(self.leverage_ratio, 2)
                               if self.leverage_ratio != float("inf") else None),
            "margin_status": self.margin_status,
            "triggers": self.triggers,
            "concentration": self.concentration,
            "structure": self.structure,
            "action_plan": self.action_plan,
            "avoidance": self.avoidance,
            "data_warnings": self.data_warnings,
        }


class RiskRadar:
    """账户级风险雷达。"""

    def __init__(self, account: AccountSnapshot,
                 peak_value: Optional[float] = None,
                 feed: Optional[DataFeed] = None,
                 check_structure: bool = True):
        """
        peak_value: 历史最高收盘市值（止损基准）。
                    强烈建议显式传入——没有基准就无法计算回撤。
                    缺省时退化为用当前市值当基准（回撤恒为 0，无意义）。
        """
        self.acc = account
        self.peak = peak_value if peak_value else account.market_value
        self.feed = feed or DataFeed(verbose=False)
        self.check_structure = check_structure

    # ---------------- 杠杆状态 ----------------

    @staticmethod
    def margin_status(ratio: float) -> str:
        if ratio == float("inf"):
            return "无融资"
        if ratio < MARGIN_CALL:
            return "🔴🔴 强平风险"
        if ratio < MARGIN_DANGER:
            return "🔴🔴 极危"
        if ratio < MARGIN_WARN:
            return "🔴 高危（已破 300% 警戒）"
        return "🟢 安全"

    # ---------------- 持仓构造 ----------------

    def _positions(self) -> List[Position]:
        out = []
        for h in self.acc.holdings:
            mv = h.get("marketValue") or 0
            if not mv:
                price = h.get("price") or 0
                shares = h.get("sharesTotal") or h.get("shares") or 0
                mv = price * shares
            w = mv / self.acc.net_asset if self.acc.net_asset else 0.0
            # 用日涨跌幅近似波动率（有则用，无则按 0 保守处理）
            vol = abs(h.get("dayRate") or 0) / 100.0
            out.append(Position(
                code=h.get("code", ""), name=h.get("name", ""),
                weight=w, volatility=vol, below_ma=False,
            ))
        return out

    def _concentration(self) -> List[Dict]:
        rows = []
        for h in self.acc.holdings:
            mv = h.get("marketValue") or 0
            if not mv:
                mv = (h.get("price") or 0) * (h.get("sharesTotal") or h.get("shares") or 0)
            w = mv / self.acc.net_asset if self.acc.net_asset else 0.0
            rows.append({"code": h.get("code", ""), "name": h.get("name", ""),
                         "weight": w, "over_limit": w > SINGLE_MAX})
        return sorted(rows, key=lambda x: -x["weight"])

    # ---------------- 结构检查 ----------------

    def _check_ma(self, positions: List[Position]) -> List[Dict]:
        """抓月线判阶段；失败只记警告，不影响整体评估。"""
        rows, warnings = [], []
        for p in positions:
            try:
                sym = ("sh" if p.code.startswith("6") else "sz") + p.code
                bars = self.feed.get(sym, "month", 40)
                st = trend_stage(bars)
                rows.append({"code": p.code, "name": p.name, **st})
                p.below_ma = st["stage"] != "above"
            except (DataUnavailable, ValueError, KeyError) as exc:
                warnings.append(f"{p.name}({p.code}) 月线获取失败：{type(exc).__name__}")
        return rows

    # ---------------- 主流程 ----------------

    def scan(self) -> RiskReport:
        acc = self.acc
        positions = self._positions()
        leverage = acc.total_debt > 0

        engine = StoplossEngine(
            peak_value=self.peak,
            current_value=acc.market_value,
            leveraged=leverage,
        )
        result = engine.evaluate(positions=positions)

        # 杠杆告警（融资账户专项）
        triggers = list(result["triggers"])
        if leverage:
            mr = acc.leverage_ratio
            if mr < MARGIN_CALL:
                triggers.append({
                    "code": "MARGIN_CALL", "track": "leverage",
                    "severity": Severity.URGENT,
                    "message": f"维持担保 {mr:.2f}% 已低于强平线 {MARGIN_CALL:.0f}%",
                    "hint": "立即降杠杆，这是最紧急的一档"})
            elif mr < MARGIN_WARN:
                triggers.append({
                    "code": "MARGIN_WARN", "track": "leverage",
                    "severity": Severity.ACT,
                    "message": f"维持担保 {mr:.2f}% 已破 {MARGIN_WARN:.0f}% 警戒线",
                    "hint": "杠杆账户波动会放大亏损，应主动降杠杆"})

        # 结构
        structure, warnings = ([], [])
        if self.check_structure:
            structure = self._check_ma(positions)
        # 结构结果回填到 action_plan 的理由里
        broken = {s["code"] for s in structure if s["stage"] != "above"}
        plan = []
        for a in result["action_plan"]:
            if a["code"] in broken:
                a["reason"] += "；且已跌破 5 月线，结构走坏"
            plan.append(a)

        severity = result["severity"]
        if any(t["severity"] == Severity.URGENT for t in triggers):
            severity = Severity.URGENT
        elif any(t["severity"] == Severity.ACT for t in triggers):
            severity = max(severity, Severity.ACT, key=lambda s: [Severity.OK, Severity.WATCH, Severity.ACT, Severity.URGENT].index(s))

        return RiskReport(
            date=acc.date,
            drawdown_pct=result["drawdown_pct"],
            severity=severity,
            position_ratio=acc.position_ratio,
            leverage_ratio=acc.leverage_ratio if leverage else None,
            margin_status=self.margin_status(acc.leverage_ratio) if leverage else "无融资",
            triggers=triggers,
            concentration=self._concentration(),
            structure=structure,
            action_plan=plan,
            avoidance=result["avoidance"],
            data_warnings=warnings,
        )
