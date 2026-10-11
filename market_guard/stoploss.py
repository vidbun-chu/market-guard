# -*- coding: utf-8 -*-
"""
market_guard.stoploss — 市值止损三轨制（风控雷达的核心规则引擎）

三轨并行，任一触发即产生动作建议：

  ① 百分比轨（控制回撤深度）
     · 常规：回撤 10% 减仓、20% 无条件清仓
     · 实际动手点：5% 就采取措施（目标是"不轻易触及 10%"）
     · 有融资：5% 必须立即处理（融资账户波动会放大亏损）
     · 预估将触及 15%：8% 就减（不要一把扛到 15%）
     · 牛市可放宽至 30%（有趋势护卫时）

  ② 结构轨（控制破位）
     · 有效跌破 5 周线 / 5 月线 / 144 日线 / 30 日线 → 先行离场
     · 长下影 + 次日走势证伪 → 止损
     · 同一均线第 3 次触及：支撑弹性已释放，不再视为支撑

  ③ 速率轨（控制亏损速度）
     · 回撤加速即减持
     · 优先拔除最影响回撤速率的个股（高仓位 × 高波动优先）

★ 铁律：目标是"尽可能不触发止损"，而不是"止损执行得漂亮"。
        因此本模块同时输出 `avoidance` 提示——告诉你应该提前做什么，
        而不只是回撤发生后补救。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = ["Severity", "Trigger", "StoplossEngine", "default_policy", "Position"]


class Severity:
    OK = "ok"
    WATCH = "watch"      # 尚未触发，但已接近，需提高警惕
    ACT = "act"          # 必须动手
    URGENT = "urgent"    # 最高级别


@dataclass
class Trigger:
    """一次触发的完整描述。"""
    code: str
    severity: str
    track: str            # percent / structure / rate
    message: str
    reduce_ratio: float = 0.0   # 建议减仓比例（0-1）
    hint: str = ""

    @property
    def is_action(self) -> bool:
        return self.severity in (Severity.ACT, Severity.URGENT)


@dataclass
class Position:
    """持仓条目（脱敏：仅代码与仓位比例，不含成本价——成本不参与决策）。"""
    code: str
    name: str
    weight: float          # 占净资产比例（0-1）
    volatility: float = 0.0  # 近期波动幅度（0-1），用于速率轨排序
    below_ma: bool = False   # 是否跌破关键均线（结构轨用）


@dataclass
class StoplossPolicy:
    """止损策略配置。默认值取自体系常用口径，可按个人风格调整。

    ⚠️ 融资账户与非融资账户的区别：
        融资会同时放大「亏损幅度」和「被动平仓风险」两个变量，
        因此动手线必须前移——融资账户 3% 即进警戒带、4% 即动手；
        非融资账户保持 5% 动手。这是本引擎默认口径的核心差异。
    """
    # 百分比轨
    normal_reduce: float = 0.10     # 常规减仓线
    normal_clear: float = 0.20      # 常规清仓线
    act_at: float = 0.05            # 实际动手点（非融资）
    pre_warn: float = 0.08          # 预减仓点（预估会到 15% 时用）
    leveraged_act_at: float = 0.04  # 有融资时的动手点（更早）
    leveraged_watch_at: float = 0.03  # 有融资时的警戒带起点
    bull_clear: float = 0.30        # 牛市放宽上限
    # 速率轨
    rate_accel_threshold: float = 0.5  # 近 5 日回撤速率相对常态的倍数
    # 减仓力度
    reduce_at_normal: float = 0.30  # 触发常规线时减多少
    reduce_at_urgent: float = 0.60
    clear_all: float = 1.00


# 常用策略预设
def default_policy(leveraged: bool = False) -> StoplossPolicy:
    """根据账户是否融资返回对应口径。

    注意：融资账户的警戒带与动手线都显著前移，
    因为融资账户承受的不只是价格风险，还有强平风险。
    """
    if leveraged:
        return StoplossPolicy(act_at=0.04, leveraged_act_at=0.04,
                              leveraged_watch_at=0.03, pre_warn=0.08)
    return StoplossPolicy()


class StoplossEngine:
    """市值止损引擎。

    典型用法:
        eng = StoplossEngine(peak_value=200000, current_value=152000,
                             leveraged=True)
        res = eng.evaluate(positions=[...])
        print(res["action_plan"])
    """

    def __init__(self, peak_value: float, current_value: float,
                 policy: Optional[StoplossPolicy] = None,
                 leveraged: bool = False, bull_market: bool = False):
        if peak_value <= 0:
            raise ValueError("peak_value 必须为正（基准是历史最高收盘市值）")
        self.peak = float(peak_value)
        self.current = float(current_value)
        self.policy = policy or default_policy(leveraged)
        self.leveraged = leveraged
        self.bull = bull_market
        self.triggers: List[Trigger] = []

    # ---------------- 回撤计算 ----------------

    @property
    def drawdown(self) -> float:
        """当前回撤（正数表示已回撤，0.15 = 回撤 15%）。"""
        return max(0.0, (self.peak - self.current) / self.peak)

    @property
    def drawdown_pct(self) -> float:
        return round(self.drawdown * 100, 2)

    @property
    def remaining_to_bull_clear(self) -> Optional[float]:
        """牛市档距上限还剩多少回撤空间。"""
        if not self.bull:
            return None
        return round(max(0.0, self.bull_clear - self.drawdown) * 100, 2)

    @property
    def bull_clear(self) -> float:
        return self.policy.bull_clear

    # ---------------- ① 百分比轨 ----------------

    def _percent_track(self) -> List[Trigger]:
        p = self.policy
        dd = self.drawdown
        t: List[Trigger] = []

        if self.bull:
            # 牛市放宽：到 30% 才无条件清
            if dd >= p.bull_clear:
                t.append(Trigger(
                    "BULL_CLEAR", Severity.URGENT, "percent",
                    f"回撤 {self.drawdown_pct}% ≥ 牛市清仓线 {p.bull_clear:.0%}",
                    p.clear_all, "牛市也到极值了，无条件清仓"))
            elif dd >= p.normal_clear:
                t.append(Trigger(
                    "BULL_WARN", Severity.WATCH, "percent",
                    f"回撤 {self.drawdown_pct}% 已达常规清仓线，但牛市可放宽至 {p.bull_clear:.0%}",
                    0.0, "确认趋势是否已护卫；若指数破 5 月线则立即恢复常规纪律"))
            return t

        # 常规/熊市口径，从严重到轻微逐级判断
        if dd >= p.normal_clear:
            t.append(Trigger(
                "CLEAR", Severity.URGENT, "percent",
                f"回撤 {self.drawdown_pct}% ≥ {p.normal_clear:.0%} → 无条件清仓",
                p.clear_all, "无条件执行，不找理由"))
        elif dd >= p.normal_reduce:
            t.append(Trigger(
                "REDUCE", Severity.ACT, "percent",
                f"回撤 {self.drawdown_pct}% ≥ {p.normal_reduce:.0%} → 减仓",
                p.reduce_at_normal, "先减高波动、高仓位个股"))
        elif dd >= p.pre_warn:
            t.append(Trigger(
                "PRE_REDUCE", Severity.ACT, "percent",
                f"回撤 {self.drawdown_pct}% ≥ {p.pre_warn:.0%} → 预减仓",
                p.reduce_at_normal * 0.5,
                "预估会继续恶化，提前降速而不是等确认"))
        elif dd >= self._act_threshold():
            thr = self._act_threshold()
            msg = f"回撤 {self.drawdown_pct}% ≥ 动手线 {thr:.0%}"
            if self.leveraged:
                msg += "（有融资，必须立即处理）"
            t.append(Trigger(
                "ACT", Severity.ACT, "percent", msg,
                p.reduce_at_normal * 0.5, "动手线的意义是不让回撤继续扩大"))
        elif dd >= self._watch_threshold():
            t.append(Trigger(
                "WATCH", Severity.WATCH, "percent",
                f"回撤 {self.drawdown_pct}%，接近动手线 {self._act_threshold():.0%}",
                0.0, "进入警戒，准备减仓清单，随时可执行"))
        return t

    def _act_threshold(self) -> float:
        return self.policy.leveraged_act_at if self.leveraged else self.policy.act_at

    def _watch_threshold(self) -> float:
        """警戒带起点。融资账户用更早的警戒线，非融资取动手线的 80%。"""
        if self.leveraged:
            return getattr(self.policy, "leveraged_watch_at",
                           self._act_threshold() * 0.8)
        return self._act_threshold() * 0.8

    # ---------------- ② 结构轨 ----------------

    def _structure_track(self, positions: List[Position]) -> List[Trigger]:
        broken = [p for p in positions if p.below_ma]
        if not broken:
            return []
        names = "、".join(f"{p.name}({p.code})" for p in broken[:5])
        more = f" 等 {len(broken)} 只" if len(broken) > 5 else ""
        return [Trigger(
            "STRUCT_BREAK", Severity.ACT, "structure",
            f"{len(broken)} 只持仓跌破关键均线：{names}{more}",
            min(0.5, 0.2 * len(broken)),
            "有效跌破重要支撑线应先行离场，别等市值层面确认")]

    # ---------------- ③ 速率轨 ----------------

    def _rate_track(self, positions: List[Position]) -> List[Trigger]:
        """回撤速率排序：优先拔除最影响速率的个股。

        权重 = 仓位占比 × (1 + 波动率)，波动大的优先。
        这是"市值回撤加速就减持"的可执行形式。
        """
        scored = sorted(
            positions,
            key=lambda p: -(p.weight * (1 + p.volatility))
        )
        return scored

    def rank_reduction_priority(self, positions: List[Position]) -> List[Position]:
        """按速率轨排序返回，调用方据此顺序减仓。"""
        return self._rate_track(positions)

    # ---------------- 汇总评估 ----------------

    def evaluate(self, positions: Optional[List[Position]] = None,
                 structure_broken: bool = False) -> Dict:
        """
        完整评估。返回:
          {
            "drawdown": 回撤比例,
            "drawdown_pct": 回撤百分数,
            "severity": 最高级别,
            "triggers": 全部触发项,
            "total_reduce": 建议总减仓比例,
            "action_plan": 可执行减仓清单,
            "avoidance": 提前规避建议,
          }
        """
        positions = positions or []
        self.triggers = []
        self.triggers += self._percent_track()
        if positions:
            self.triggers += self._structure_track(positions)

        if self.triggers:
            # 取"最严重"= 等级序数最大者。
            # 注意：不能用 min()，那会取到最不严重的一个，导致
            # 清仓级触发被报成 OK —— 这是很危险的错误。
            order = (Severity.OK, Severity.WATCH, Severity.ACT, Severity.URGENT)
            severity = max((t.severity for t in self.triggers), key=order.index)
        else:
            severity = Severity.OK

        # 建议总减仓比例：取所有触发项最大值，不叠加（避免重复计）
        total_reduce = max((t.reduce_ratio for t in self.triggers), default=0.0)
        total_reduce = min(total_reduce, 1.0)

        return {
            "drawdown": round(self.drawdown, 4),
            "drawdown_pct": self.drawdown_pct,
            "severity": severity,
            "triggers": [
                {"code": t.code, "track": t.track, "severity": t.severity,
                 "message": t.message, "reduce_ratio": t.reduce_ratio, "hint": t.hint}
                for t in self.triggers
            ],
            "total_reduce": round(total_reduce, 4),
            "action_plan": self._build_plan(positions, total_reduce),
            "avoidance": self._avoidance(severity),
        }

    def _build_plan(self, positions: List[Position], total_reduce: float) -> List[Dict]:
        """生成"减谁、多少、降到几成"的可执行清单。"""
        if total_reduce <= 0 or not positions:
            return []
        need = total_reduce * self.current
        plan = []
        for p in self.rank_reduction_priority(positions):
            if need <= 0:
                break
            cut = min(need, p.weight * self.peak)   # 单只先减一半最坏
            if cut <= 0:
                continue
            plan.append({
                "code": p.code, "name": p.name,
                "reduce_value": round(cut, 2),
                "weight_before": round(p.weight, 4),
                "weight_after": round(max(0.0, p.weight - cut / self.current), 4),
                "reason": self._reason_for(p),
            })
            need -= cut
        return plan

    def _reason_for(self, p: Position) -> str:
        if p.below_ma and p.volatility > 0.03:
            return "跌破均线且波动大，同时拖累市值与回撤速率"
        if p.below_ma:
            return "已跌破关键均线，结构走坏"
        if p.volatility > 0.03:
            return "波动大，是回撤速率的主要贡献者"
        return "仓位偏高，需降低集中度"

    def _avoidance(self, severity: str) -> str:
        """核心：目标是永不触发止损。"""
        if severity == Severity.URGENT:
            return ("止损的意义是避免大亏。已经到这一档说明前面没管住，"
                    "这次处理完务必重新设定更早的动手线。")
        if severity == Severity.ACT:
            return ("此刻最重要的不是判断方向，而是立刻降低回撤速率。"
                    "减仓顺序按「仓位×波动」排，优先拔除拖累最大的那只。")
        if severity == Severity.WATCH:
            return ("现在是最好的处理窗口——回撤还没到动手线，"
                    "减掉的代价最小。等确认了再动，成本会高很多。")
        return ("当前无需动作。继续保持：单只别超 3 成、"
                "组合分散、留有余地，让止损永远不必触发。")
