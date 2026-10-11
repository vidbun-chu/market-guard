# -*- coding: utf-8 -*-
"""
market_guard — 账户级风控与趋势工具包
====================================
模块:
    datafeed    多源容错行情抓取（腾讯/新浪/东财，自动回退）
    indicators  趋势引擎（体系均线清单 + 月线阶段判定）
    stoploss    市值止损三轨制（百分比/结构/速率）
    cycle       大周期定位（定性三问法）
    radar       风险雷达（账户级汇总，生成可执行减仓清单）

设计原则:
    1. 只计算与提示，不连接券商、不下单、不修改账户数据。
    2. 显式失败优于静默兜底——数据拿不到就说拿不到。
    3. 规则来自成熟的趋势投资纪律体系，规则阈值在代码中显式可改，
       且每个阈值旁标注了设定理由。
    4. 决策与风险由使用者自负。本包是纪律工具，不是荐股器。

快速开始:
    from market_guard import RiskRadar, AccountSnapshot

    acc = AccountSnapshot.from_json("account.json")
    radar = RiskRadar(acc, peak_value=200000)
    print(radar.scan().to_text())

命令行:
    python -m market_guard radar --account account.json --peak 200000
    python -m market_guard cycle --code sh000001
    python -m market_guard trend  --code sh600519
"""
from .datafeed import Bar, DataFeed, DataUnavailable
from .indicators import (MA_DAILY, MA_MONTHLY, MA_WEEKLY, Stage,
                         avg_deviation, ma, resonance, support_lines, trend_stage)
from .stoploss import (Position, Severity, StoplossEngine, StoplossPolicy,
                       default_policy)
from .cycle import CycleView, assess_cycle
from .radar import AccountSnapshot, RiskRadar, RiskReport

__version__ = "1.0.0"
__all__ = [
    "Bar", "DataFeed", "DataUnavailable",
    "MA_DAILY", "MA_WEEKLY", "MA_MONTHLY", "Stage",
    "ma", "trend_stage", "support_lines", "resonance", "avg_deviation",
    "Position", "Severity", "StoplossEngine", "StoplossPolicy", "default_policy",
    "CycleView", "assess_cycle",
    "AccountSnapshot", "RiskRadar", "RiskReport",
    "__version__",
]
