# -*- coding: utf-8 -*-
"""market_guard 单元测试（不联网，用合成数据）。

运行：python -m pytest tests/ -v
或：  python tests/test_core.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_guard.datafeed import Bar
from market_guard.indicators import (Stage, ma, support_lines, trend_stage,
                                     resonance, avg_deviation, MA_DAILY)
from market_guard.stoploss import (Position, Severity, StoplossEngine,
                                   default_policy)
from market_guard.cycle import question_ma_broken, question_tangle, assess_cycle


def mk(closes, start="2026-01"):
    """用收盘价序列造合成 K 线（不含真实数据）。"""
    bars = []
    for i, c in enumerate(closes):
        bars.append(Bar(date=f"{start}-{i+1:02d}", open=c, high=c * 1.01,
                        low=c * 0.99, close=c, volume=1000.0))
    return bars


# ---------------- indicators ----------------

def test_ma():
    assert ma(mk([10, 20, 30, 40, 50]), 5) == 30.0
    assert ma(mk([10, 20]), 5) is None, "数据不足必须返回 None 而非 0"


def test_trend_stage_above():
    bars = mk([10] * 6 + [20, 20, 20, 20])
    assert trend_stage(bars)["stage"] == Stage.ABOVE


def test_trend_stage_first():
    # 现价跌破，但此前未破 → first
    bars = mk([20] * 8 + [10])
    st = trend_stage(bars)
    assert st["stage"] in (Stage.FIRST, Stage.OFF2)


def test_trend_stage_off2():
    # 构造真实场景：长期 30，末尾连续两根跌到 10。
    # 5月均线按含当月口径 = (30*3 + 10*2)/5 = 22；
    # completed 末尾两根 10 < 22 → below_run=2 → off2
    bars = mk([30] * 8 + [10, 10])
    st = trend_stage(bars)
    assert st["stage"] == Stage.OFF2, st
    assert st["below_run"] >= 2, st


def test_trend_stage_insufficient():
    try:
        trend_stage(mk([10, 11, 12]))
        raise AssertionError("数据不足应抛异常")
    except ValueError:
        pass


def test_support_lines():
    # 需足够长的序列才能算出全部均线（MA250 需要 250 根）
    long_bars = mk([10 + i * 0.01 for i in range(260)])
    sup = support_lines(long_bars)
    assert len(sup) == len(MA_DAILY), f"应算出全部 {len(MA_DAILY)} 条均线"
    assert all("role" in s for s in sup)
    # 短序列时不足的均线应被跳过而非报错
    short = support_lines(mk([10] * 7))
    assert len(short) == 1, "7 根只够 MA5"


def test_resonance_and_deviation():
    bars = mk([10] * 30)
    assert isinstance(resonance(bars), dict)
    assert avg_deviation(bars, 5) is not None


# ---------------- stoploss ----------------

def test_percent_no_action_below_threshold():
    """回撤 4% 未达 5% 动手线 → 不应触发。这是设计的核心：宁可不动。"""
    eng = StoplossEngine(peak_value=100.0, current_value=96.0)
    r = eng.evaluate(positions=[])
    assert r["severity"] == Severity.OK
    assert r["triggers"] == []
    assert r["drawdown_pct"] == 4.0


def test_percent_watch_near_line():
    """回撤 4.2% 接近 5% 动手线 → 警戒但仍不触发动手。"""
    eng = StoplossEngine(peak_value=100.0, current_value=95.8)
    r = eng.evaluate(positions=[])
    assert r["severity"] == Severity.WATCH, r["severity"]
    assert r["total_reduce"] == 0.0, "警戒档不应给减仓动作"
    assert any(t["code"] == "WATCH" for t in r["triggers"])


def test_percent_act_at_5():
    eng = StoplossEngine(peak_value=100.0, current_value=95.0)
    r = eng.evaluate(positions=[])
    assert any(t["code"] == "ACT" for t in r["triggers"])


def test_percent_clear_at_20():
    """回撤 21% ≥ 20% → 无条件清仓，total_reduce 必须为 1.0。"""
    eng = StoplossEngine(peak_value=100.0, current_value=79.0)
    r = eng.evaluate(positions=[])
    assert r["severity"] == Severity.URGENT, r["severity"]
    assert r["total_reduce"] == 1.0, r["total_reduce"]
    assert any(t["code"] == "CLEAR" for t in r["triggers"])


def test_leveraged_act_line_stricter():
    """融资账户动手线是 5%（不可碰的硬线），非融资账户的"警戒带"更早出现但不动手。
    两者真正可检验的差异是：融资账户在 5% 立刻 ACT，非融资要到 8% 才 ACT。
    """
    # 5.5% 回撤：融资账户已过动手线
    lev = StoplossEngine(peak_value=100.0, current_value=94.5, leveraged=True)
    lr = lev.evaluate(positions=[])
    assert lr["severity"] == Severity.ACT, lr["severity"]
    assert any(t["code"] == "ACT" for t in lr["triggers"])

    # 同样 5.5%：非融资账户只是进入预减仓档
    nor = StoplossEngine(peak_value=100.0, current_value=94.5, leveraged=False)
    nr = nor.evaluate(positions=[])
    assert nr["severity"] == Severity.ACT, nr["severity"]
    order = {Severity.OK: 0, Severity.WATCH: 1, Severity.ACT: 2, Severity.URGENT: 3}
    assert order[lr["severity"]] >= order[nr["severity"]]

    # 极端情形：融资账户在 4.9% 就已经进警戒带，非融资还完全无动作
    lev2 = StoplossEngine(peak_value=100.0, current_value=95.1, leveraged=True)
    nor2 = StoplossEngine(peak_value=100.0, current_value=95.1, leveraged=False)
    assert order[lev2.evaluate(positions=[])["severity"]] > \
           order[nor2.evaluate(positions=[])["severity"]], "融资账户警戒必须更早"


def test_bull_market_relaxed():
    bull = StoplossEngine(peak_value=100.0, current_value=79.0, bull_market=True)
    r = bull.evaluate(positions=[])
    assert r["total_reduce"] == 0.0, "牛市 30% 内不该触发清仓"


def test_structure_track():
    eng = StoplossEngine(peak_value=100.0, current_value=99.0)
    pos = [Position(code="X", name="破位股", weight=0.3, below_ma=True)]
    r = eng.evaluate(positions=pos)
    assert any(t["track"] == "structure" for t in r["triggers"])


def test_rate_priority():
    eng = StoplossEngine(peak_value=100.0, current_value=95.0)
    pos = [
        Position("A", "低波低仓", 0.10, 0.01),
        Position("B", "高波高仓", 0.40, 0.05),
    ]
    order = eng.rank_reduction_priority(pos)
    assert order[0].code == "B", "仓位×波动最大者应优先减"


def test_action_plan_generated():
    eng = StoplossEngine(peak_value=100.0, current_value=70.0)
    pos = [Position("A", "甲", 0.35), Position("B", "乙", 0.25)]
    r = eng.evaluate(positions=pos)
    assert r["action_plan"], "触发后应生成可执行清单"
    assert all("weight_after" in a for a in r["action_plan"])


def test_action_plan_fields_consistent():
    """防回归：to_text() 消费的字段必须与 _build_plan() 产出的一致。
    历史 bug：plan 里叫 reduce_value，渲染时取 a['action'] → KeyError 崩溃。
    """
    eng = StoplossEngine(peak_value=100.0, current_value=70.0)
    pos = [Position("A", "甲", 0.35), Position("B", "乙", 0.25)]
    plan = eng.evaluate(positions=pos)["action_plan"]
    required = {"code", "name", "reduce_value", "weight_before",
                "weight_after", "reason"}
    for a in plan:
        assert required <= set(a), f"缺字段: {required - set(a)}"


def test_radar_report_renders():
    """端到端：RiskRadar 生成的报告必须能渲染成文本（不联网，跳过均线抓取）。"""
    from market_guard.radar import RiskRadar, AccountSnapshot
    acc = AccountSnapshot(
        date="t", total_asset=130000.0, net_asset=100000.0,
        total_debt=30000.0, market_value=152000.0,
        holdings=[{"code": "600519", "name": "示例", "shares": 100,
                   "price": 1680.0, "dayRate": -0.42}],
    )
    rep = RiskRadar(acc, peak_value=150000, check_structure=False).scan()
    txt = rep.to_text()          # 之前会在这里 KeyError 崩溃
    assert "风控雷达" in txt
    assert "维持担保" in txt
    assert isinstance(rep.to_dict(), dict)


def test_radar_detects_urgent_drawdown():
    from market_guard.radar import RiskRadar, AccountSnapshot
    acc = AccountSnapshot(
        date="t", total_asset=80000.0, net_asset=40000.0,
        total_debt=40000.0, market_value=64000.0,
        holdings=[{"code": "000001", "name": "示例", "shares": 1000,
                   "price": 64.0}],
    )
    # 峰值 100000 → 现 64000 = 回撤 36%，必然触发最高级别
    rep = RiskRadar(acc, peak_value=100000, check_structure=False).scan()
    assert rep.severity == Severity.URGENT, rep.severity
    assert rep.drawdown_pct > 30


def test_invalid_peak():
    try:
        StoplossEngine(peak_value=0, current_value=100)
        raise AssertionError("peak 必须为正")
    except ValueError:
        pass


def test_leverage_ratio_is_percentage_not_multiple():
    """防回归：维持担保必须返回百分数（433.3 = 433.3%），不是倍数（2.91）。
    历史 bug：返回倍数却按百分数渲染，导致 291% 显示成 2.91%。"""
    from market_guard.radar import AccountSnapshot
    a = AccountSnapshot(date="t", total_asset=130000.0, net_asset=100000.0,
                        total_debt=30000.0, market_value=152000.0)
    assert abs(a.leverage_ratio - 433.33) < 0.5, a.leverage_ratio
    # 无负债时应为 inf，便于显示"无融资"
    b = AccountSnapshot(date="t", total_asset=100, net_asset=100,
                        total_debt=0, market_value=50)
    assert b.leverage_ratio == float("inf")


# ---------------- cycle ----------------

def test_cycle_q1():
    # 长期 30，末尾两根 10 → 5月线=(30*3+10*2)/5=22，连续两月收在下方
    bars = mk([30] * 8 + [10, 10], start="2025-01")
    q = question_ma_broken(bars)
    assert q["broken_months"] >= 2, q
    assert "确认" in q["state"], q["state"]


def test_cycle_q2():
    bars = mk([10] * 30)
    q = question_tangle(bars)
    assert q["state"]


def test_cycle_summary():
    bars = mk([20] * 30)
    v = assess_cycle(bars)
    txt = v.summary()
    assert "定性三问" in txt


# ---------------- runner ----------------

def run_all():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    ok = 0
    print(f"运行 {len(fns)} 个测试\n")
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
            ok += 1
        except Exception as exc:
            print(f"  FAIL  {name}: {type(exc).__name__} {exc}")
    print(f"\n{ok}/{len(fns)} 通过")
    return 0 if ok == len(fns) else 1


if __name__ == "__main__":
    sys.exit(run_all())
