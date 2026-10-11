# -*- coding: utf-8 -*-
"""
market_guard.cycle — 大周期定位（定性三问法）

★ 为什么不用"现价 ÷ 5 月均线比值 → 四档"？
    该表格在早期版本中提供过，但缺乏实际交易语料支撑，属后验归纳，
    容易诱导使用者把周期"算"出来，反而造成指数定档的执念。
    本模块只提供客观事实与定性判据，把结论留给使用者判断。

三个定性问题：
    ① 5 月线破了没？   月线收盘是否连续两月收在 5 月线下方
    ② 指数均线缠绕吗？ 5/10/20 月线是否交织无明显趋势
    ③ 低价股集体暴动吗？ 需要外部数据（本模块不内置抓取，需自行提供）

周期只用于：确定收益预期、评估市场难度、制定对策。
    —— 不要用周期去预测点位。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .datafeed import Bar

__all__ = ["monthly_ma", "question_ma_broken", "question_tangle",
           "assess_cycle", "CycleView"]


def monthly_ma(bars: Sequence[Bar], n: int) -> Optional[float]:
    if len(bars) < n:
        return None
    return sum(b.close for b in bars[-n:]) / n


def question_ma_broken(month_bars: Sequence[Bar]) -> Dict:
    """问题①：5 月线破了没？

    返回客观事实 + 提示，不代替判断：
      · broken_months = 连续收在 5 月线下方的月数
      · broken >= 2 → 已确认转弱
      · broken == 1 → 第一根，小心
      · broken == 0 → 未破
    """
    if len(month_bars) < 6:
        raise ValueError("月线不足 6 根")
    closes = [b.close for b in month_bars]
    m5 = sum(closes[-5:]) / 5.0
    cur = closes[-1]

    # 逐月用"当月自己的 5 月线"判定，避免用最新 m5 回溯造成误判
    flags = []
    for i in range(5, len(closes)):
        window = closes[max(0, i - 5):i]
        flags.append(closes[i] > sum(window) / len(window))

    broken = 0
    for f in reversed(flags[:-1]):
        if not f:
            broken += 1
        else:
            break

    if broken >= 2:
        state = "已确认转弱（连续两月收在 5 月线下）"
        hint = "月线收盘击破 5 月线是最后的逃顶信号；此时不宜再行重注。"
    elif broken == 1:
        state = "首根跌破，警惕"
        hint = "第一根跌破要小心，第二根基本就能确认。控制仓位、等确认。"
    else:
        state = "未破"
        hint = "5 月线是主升/主跌期生命线，当前尚未有效击破。"

    return {
        "question": "5月线破了没",
        "current_close": round(cur, 2),
        "ma5": round(m5, 2),
        "broken_months": broken,
        "state": state,
        "hint": hint,
        "objective_facts": {
            "本月收盘": round(cur, 2),
            "5月均线": round(m5, 2),
            "差值": round(cur - m5, 2),
        },
    }


def question_tangle(month_bars: Sequence[Bar]) -> Dict:
    """问题②：指数均线缠绕吗？

    用 5/10/20 月线的最大最小差占均价的比例衡量交织程度。
    交织 → 震荡，无明确趋势。
    """
    mas = {}
    for n in (5, 10, 20):
        mas[n] = monthly_ma(month_bars, n)
    vals = [v for v in mas.values() if v is not None]
    if len(vals) < 2:
        return {"question": "指数均线缠绕吗",
                "state": "数据不足", "hint": "需要至少 20 根月线"}

    mean = sum(vals) / len(vals)
    spread = (max(vals) - min(vals)) / mean * 100

    if spread <= 3.0:
        state = "缠绕（震荡）"
        hint = "均线交织、无趋势，涨跌都难；此时频繁切换比择时有效。"
    else:
        state = "有方向（不缠绕）"
        hint = "均线已发散，趋势较明确。"

    return {
        "question": "指数均线缠绕吗",
        "state": state,
        "spread_pct": round(spread, 2),
        "ma": {str(k): round(v, 2) for k, v in mas.items() if v is not None},
        "hint": hint,
    }


def assess_cycle(month_bars: Sequence[Bar],
                 low_price_surge: Optional[bool] = None) -> "CycleView":
    """
    汇总三问。低价股暴动需要外部输入（抓取成本高，
    本库不内置，避免为了一个信号拉全市场数据）。

    用法:
        view = assess_cycle(month_bars)
        print(view.summary())
    """
    q1 = question_ma_broken(month_bars)
    q2 = question_tangle(month_bars)
    q3 = {
        "question": "低价股集体暴动吗",
        "state": "需外部数据" if low_price_surge is None else
                  ("是（大牛市信号）" if low_price_surge else "否"),
        "hint": "低价股集体上涨是大牛市启动的重要信号之一；"
                "本库不内置该抓取，请自行接入数据源后传入。",
    }

    return CycleView(q1, q2, q3)


class CycleView:
    def __init__(self, q1: Dict, q2: Dict, q3: Dict):
        self.q1, self.q2, self.q3 = q1, q2, q3

    def summary(self) -> str:
        L = ["=" * 58,
             " 大周期定位 · 定性三问",
             "=" * 58,
             f"① {self.q1['question']}：{self.q1['state']}",
             f"     → {self.q1['hint']}",
             f"② {self.q2['question']}：{self.q2['state']}",
             f"     → {self.q2['hint']}",
             f"③ {self.q3['question']}：{self.q3['state']}",
             f"     → {self.q3['hint']}",
             "=" * 58,
             "周期的用途：确定收益预期、评估市场难度、制定对策。",
             "不要用周期去预测点位，也不要跳过周期直接谈个股。",
             "=" * 58]
        return "\n".join(L)

    def to_dict(self) -> Dict:
        return {"q1_ma_broken": self.q1, "q2_tangle": self.q2,
                "q3_low_price_surge": self.q3}
