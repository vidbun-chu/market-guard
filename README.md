# market_guard

[![PyPI version](https://img.shields.io/pypi/v/market-guard.svg)](https://pypi.org/project/market-guard/)
[![Python versions](https://img.shields.io/pypi/pyversions/market-guard.svg)](https://pypi.org/project/market-guard/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://github.com/vidbun-chu/market_guard/actions/workflows/ci.yml/badge.svg)](https://github.com/vidbun-chu/market_guard/actions/workflows/ci.yml)

账户级风控与趋势工具包 —— 把"凭感觉盯盘"变成"按纪律盯盘"。

> ⚠️ 免责声明：本工具包**只做计算与提示**，不连接券商接口、不下单、不修改账户数据。
> 它不是荐股器，所有输出仅为纪律提醒。决策与风险由使用者自负。

---

## 为什么做这个

多数散户盯盘的问题是：**平时不看盘，出问题时才看；一看盘就反应过度。**
本工具包把三类工作自动化：

| 模块 | 解决什么 |
|---|---|
| `datafeed` | 数据源随时会断连——多源自动回退 |
| `indicators` | 均线算错、口径不一——统一前复权与体系均线 |
| `stoploss` | 止损全凭感觉——用三轨制把纪律变成代码 |
| `cycle` | 大周期靠拍脑袋——用定性三问替代算命式定档 |
| `radar` | 知道该减仓但不知道减谁——生成可执行清单 |

## 安装

```bash
pip install market-guard
```

零第三方依赖，只需 Python ≥ 3.9。无需编译。

```bash
python -m market_guard demo      # 验证安装，零网络
```

**详细指南见 [docs/USAGE.md](docs/USAGE.md)** —— 含账户 JSON 格式说明、
三个必须自洽的恒等式、定时任务集成示例。

---

## 快速开始

```bash
pip install -e .          # 或直接 cp 到你的项目里（零依赖，仅用标准库）

python -m market_guard demo        # 跑内置样例，零网络
```

### 风控扫描

```python
from market_guard import RiskRadar, AccountSnapshot

acc = AccountSnapshot.from_json("account.json")
radar = RiskRadar(acc, peak_value=200000)   # peak = 历史最高收盘市值
report = radar.scan()
print(report.to_text())
```

命令行：
```bash
python -m market_guard radar --account account.json --peak 200000
python -m market_guard radar --account account.json --peak 200000 --json
python -m market_guard radar --account account.json --no-structure   # 跳过均线抓取，更快
```

### 趋势分析

```bash
python -m market_guard trend --code sh600519 --period month
```

```python
from market_guard import DataFeed, trend_stage, support_lines

feed = DataFeed(verbose=True)
bars = feed.get("sh600519", "month", 40)
print(trend_stage(bars))        # → {"stage": "off2", "below_run": 2, ...}
print(support_lines(bars))      # → 各均线是支撑还是压力
```

### 周期定位

```bash
python -m market_guard cycle --code sh000001
```

---

## 核心概念

### 市值止损三轨制

止损不是"跌了补仓"，而是**控制回撤**。本包实现三条互相独立的轨道，任一触发即产生动作：

| 轨 | 关注什么 | 默认档位 |
|---|---|---|
| **百分比轨** | 回撤深度 | 常规 10% 减仓 / 20% 清仓；**5% 就动手**；有融资 4% 动手、3% 进警戒；预估要触及 15% 则 8% 就减；牛市可放宽到 30% |
| **结构轨** | 破位 | 有效跌破 5 周线 / 5 月线 / 144 日线 / 30 日线 → 先行离场 |
| **速率轨** | 亏损速度 | 回撤加速即减持；**优先拔除"仓位 × 波动"最大的那只** |

关键设计：**目标是"尽可能不触发止损"**，所以报告里除了 `action_plan`（已触发怎么办），还有 `avoidance`（现在该做什么以避免将来触发）。

### 阶段判定（trend_stage）

月线收盘相对 5 月线的位置，只有三档：

- `above` —— 站上 5 月线
- `first` —— 首次跌破（第一根，要小心）
- `off2` —— 连续两月收在 5 月线下方（确认转弱）

> ⚠️ 实现要点：连续破位的判定**必须逐月用"当月自己的 5 月线"**，
> 不能拿最新的 5 月线回溯比。否则 5 月线下移时早期月份比较会失真，
> 导致 `off2` 被漏判（本项目开发时实测踩过这个坑）。

### 大周期：定性三问，不算档位

**本包不提供"现价 ÷ 5 月均线 → 四档"的换算。** 那个表格缺乏实证支撑，
容易诱导使用者把周期"算"出来，反而形成指数定档的执念。改用三问：

1. **5 月线破了没？**（月线收盘是否连续两月收在下方）
2. **指数均线缠绕吗？**（5/10/20 月线交织 → 震荡）
3. **低价股集体暴动吗？**（需自行接入数据源）

周期只用于：**确定收益预期、评估市场难度、制定对策**。不要用周期预测点位。

---

## 账户快照格式

```json
{
  "date": "2026-10-09",
  "account": {
    "totalAsset": 130000.0,
    "netAsset": 100000.0,
    "totalDebt": 30000.0,
    "marketValue": 152000.0,
    "available": 0.0
  },
  "holdings": [
    {"code": "600519", "name": "示例蓝筹", "shares": 100,
     "price": 1680.0, "dayRate": -0.42}
  ]
}
```

注意：
- **`totalDebt` 为 0 表示无融资**，此时不启用杠杆相关档位。
- 不需要成本价。成本不参与决策——卖掉不该考虑买入价。
- `dayRate` 可选，用于速率轨排序（波动大的优先减）。

---

## 自定义阈值

```python
from market_guard.stoploss import StoplossPolicy, StoplossEngine

policy = StoplossPolicy(
    normal_reduce=0.08,
    normal_clear=0.15,
    act_at=0.04,
    bull_clear=0.25,
)
eng = StoplossEngine(100000, 92000, policy=policy)
print(eng.evaluate())
```

---

## 测试

```bash
python tests/test_core.py         # 零网络，秒级
# 或
python -m pytest tests/ -v
```

24 个测试覆盖均线计算、阶段判定、三轨触发、融资/非融资差异、
牛市放宽、减仓排序、单位一致性、报告渲染。

---

## 设计原则

1. **只读、只算、不下单** —— 不含任何券商交易接口。
2. **显式失败优于静默兜底** —— 数据全部源失败时抛 `DataUnavailable`，
   绝不静默返回空列表（空列表会让下游算出"均线没破"的假信号）。
3. **不静默替换口径** —— 前复权、拉取周期等口径全部显式可见。
4. **阈值可改且有注释** —— 每个档位都写明设定理由。

---

## 常见问题

**Q: 回撤百分比怎么算的？**
基准是 `peak_value`（账户历史最高收盘市值），不是初始资金、不是当前市值。
强烈建议显式传入 `peak`；不传则回撤恒为 0，止损功能失效。

**Q: 融资账户为什么更严格？**
融资同时放大"亏损幅度"和"被动平仓风险"两个变量，因此动手线前移到 4%、
警戒带 3%（非融资为 5% / 4%）。

**Q: 为什么我的持仓没出现在结构检查里？**
结构检查需要联网抓月线。若数据源不可用，报告的 `data_warnings` 会明确列出
哪只失败了——失败是可见的，不会被静默跳过。用 `--no-structure` 可关闭。

**Q: 支持港股/美股吗？**
K 线层可以（代码格式 `hk00700` / `usAAPL` 视数据源而定），
但止损阈值与单只 3 成上限是按 A 股设计的，跨市场请自行调整 policy。

---

## 许可

MIT

---

## 从源码构建与发布（贡献者）

```bash
git clone <your-fork-url>
cd market_guard
python -m pip install -e . build twine

python tests/test_core.py          # 24 个测试，零网络
python -m build                    # 产出 dist/*.whl 与 *.tar.gz
python -m twine check dist/*       # 校验元数据
python -m twine upload dist/*      # 需在 ~/.pypirc 配置 API Token
```

仓库内置两条工作流：
- `.github/workflows/ci.yml` —— 三平台 × 五 Python 版本的测试矩阵
- `.github/workflows/publish.yml` —— 打 `v*` tag 或手动触发，用 OIDC 信任发布上传 PyPI

维护者推荐用 **OIDC 信任发布**（在 PyPI 后台配置 GitHub 仓库），
这样仓库里不需要存任何 API Token。
