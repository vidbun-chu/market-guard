# 使用指南

本文档面向"第一次使用 market_guard"的开发者。看完能在 5 分钟内跑出第一份风控报告。

---

## 0. 安装

```bash
pip install market-guard
```

零第三方依赖，只需 Python ≥ 3.9。不需要编译，不需要额外装包。

验证安装：

```bash
python -m market_guard demo
```

看到风控报告即安装成功。

---

## 1. 准备账户快照 JSON

风控雷达需要一个描述账户的 JSON 文件。这是**唯一需要你自己准备的东西**。

### 最小可用格式

```json
{
  "date": "2026-10-09",
  "account": {
    "totalAsset": 130000.0,
    "netAsset": 100000.0,
    "totalDebt": 30000.0,
    "marketValue": 152000.0
  },
  "holdings": [
    {"code": "600519", "name": "某蓝筹", "shares": 100, "price": 1680.0}
  ]
}
```

完整示例见 [`examples/account.example.json`](../examples/account.example.json)。

### 字段说明

| 字段 | 必填 | 含义 | 备注 |
|---|---|---|---|
| `account.totalAsset` | ✅ | 总资产（含负债） | 维持担保比例的分子 |
| `account.netAsset` | ✅ | 净资产（自有资金） | 所有仓位百分比的**分母** |
| `account.totalDebt` | ✅ | 融资负债 | 填 `0` 表示无融资，此时不启用杠杆档位 |
| `account.marketValue` | ✅ | 持仓总市值 | 回撤计算的分子 |
| `account.available` | ❌ | 可用资金 | 仅展示用 |
| `holdings[].code` | ✅ | 6 位证券代码 | 决定抓哪个市场的月线 |
| `holdings[].name` | ❌ | 名称 | 只为报告可读性 |
| `holdings[].shares` | ✅* | 股数 | 与 price 二选一用于算市值 |
| `holdings[].price` | ✅* | 现价 | 与 shares 二选一 |
| `holdings[].marketValue` | ❌ | 直接给定市值 | 给了就优先用它 |
| `holdings[].dayRate` | ❌ | 当日涨跌幅（%） | **强烈建议提供**，用于"速率轨"排序 |

### 三个必须自洽的恒等式

数据自洽是报告正确的前提，请务必检查：

```
1. totalAsset ≈ netAsset + totalDebt
2. marketValue  ≈ Σ(各持仓市值)
3. 仓位          = marketValue / netAsset
```

如果第 1 条不成立，维持担保比例会算错；如果第 2 条不成立，集中度会失真。

### 特别提醒：`peak_value` 不能省

```bash
# ✗ 错误：省略 peak
python -m market_guard radar --account account.json

# ✓ 正确：传入历史最高收盘市值
python -m market_guard radar --account account.json --peak 200000
```

不传 `peak` 时回撤恒为 0，止损功能完全失效——这是最容易踩的坑。
`peak` 的口径是**账户历史最高收盘市值**，不是初始资金、不是当前市值。

---

## 2. 跑第一次扫描

```bash
# 基本用法
python -m market_guard radar --account account.json --peak 200000

# 机器可读（接入自己的系统/告警）
python -m market_guard radar --account account.json --peak 200000 --json

# 跳过均线抓取（离线或网络差时，快 10 倍）
python -m market_guard radar --account account.json --peak 200000 --no-structure
```

### 报告怎么读

```
 市值回撤      24.00%          ← 相对 peak 的回撤
 仓位          152.0%          ← marketValue / netAsset
 维持担保      433.33%         ← totalAsset / totalDebt
 最高级别      URGENT          ← ok < watch < act < urgent

【触发项】
  · [percent]  ...            ← 哪条轨触发、为什么
  · [structure] ...           ← 哪只持仓破位
  · [leverage]  ...           ← 杠杆专项

【集中度】                     ← 单只超 30% 会标红
【结构（均线）】                ← 每只相对 5 月线的位置
【减仓清单】                   ← 减谁、多少、降到几成，以及理由
【建议】                        ← 优先读这段
```

**四个级别**：

| 级别 | 含义 | 该做什么 |
|---|---|---|
| `ok` | 未触发 | 什么都不用做 |
| `watch` | 接近动手线 | 准备减仓清单，随时可执行 |
| `act` | 已触动手手线 | 按清单减仓 |
| `urgent` | 清仓线/强平风险 | 无条件执行，不找理由 |

`avoidance` 字段比 `action_plan` 更值得读——它告诉你**现在做什么可以让将来永远不必触发止损**。

---

## 3. Python API

### 3.1 风控扫描

```python
from market_guard import RiskRadar, AccountSnapshot

acc = AccountSnapshot.from_json("account.json")
radar = RiskRadar(acc, peak_value=200000, check_structure=True)

report = radar.scan()
print(report.to_text())
```

只要数据：

```python
data = report.to_dict()
if data["severity"] in ("act", "urgent"):
    notify_me(data)          # 接你自己的告警通道
```

### 3.2 自定义策略

```python
from market_guard import StoplossEngine, StoplossPolicy

policy = StoplossPolicy(
    normal_reduce=0.08,      # 比默认更早减仓
    normal_clear=0.15,
    act_at=0.04,
    reduce_at_normal=0.40,   # 触发时减得更多
)
eng = StoplossEngine(peak_value=200000, current_value=180000, policy=policy)
result = eng.evaluate(positions=[
    Position(code="600519", name="某蓝筹", weight=0.35, volatility=0.02),
])
print(result["total_reduce"])
```

### 3.3 手动控制数据源

```python
from market_guard import DataFeed

feed = DataFeed(order=["tencent", "sina"], verbose=True)
bars = feed.get("sh600519", "month", 40)
print(f"使用数据源: {feed.last_used}")
```

批量抓取（单只失败不影响整体，缺失键即失败）：

```python
codes = ["sh600519", "sz000001", "sh601318"]
result = feed.get_many(codes, "month", 40)
failed = set(codes) - set(result)
if failed:
    print(f"这些代码抓取失败: {failed}")   # 显式失败，不静默跳过
```

### 3.4 趋势分析

```python
from market_guard import trend_stage, support_lines, resonance, avg_deviation

st = trend_stage(bars)          # {"stage": "off2", "below_run": 2, ...}
if st["stage"] == "off2":
    print("已连续两月跌破 5 月线，转弱确认")

for s in support_lines(bars):
    print(f"MA{s['period']}: {s['value']} ({s['role']})")

print("共振:", resonance(bars))
print("偏离5日线:", avg_deviation(bars, 5), "%")
```

### 3.5 周期定位

```python
from market_guard import assess_cycle

view = assess_cycle(feed.get("sh000001", "month", 60),
                    low_price_surge=False)   # 第三个参数需自行接数据源
print(view.summary())
```

---

## 4. 集成到定时任务

### 收盘后自动扫描（Linux/macOS crontab）

```cron
30 15 * * 1-5 cd /path/to/project && \
  python -m market_guard radar --account ~/account.json --peak 200000 \
  --json > ~/radar_$(date +\%F).json
```

### Windows 任务计划

```powershell
$action = New-ScheduledTaskAction -Execute "python" `
  -Argument "-m market_guard radar --account C:\path\account.json --peak 200000 --json"
$trigger = New-ScheduledTaskTrigger -Daily -At 3:30pm
Register-ScheduledTask -TaskName "market_guard" -Action $action -Trigger $trigger
```

退出码可用于告警：`0` = 未触发，`1` = 有触发。

---

## 5. 常见问题

**Q: 报告里某只持仓没出现在"结构（均线）"里？**

需要联网抓月线。数据源失败会记在 `data_warnings` 里，**失败是可见的**，不会被静默跳过。网络环境不稳定时可用 `--no-structure` 关闭。

**Q: 为什么 demo 的示例仓位是 152%？**

示例数据刻意设置成"高杠杆 + 大回撤"，用来演示工具在最危险场景下的行为。不是推荐仓位。

**Q: 支持港股/美股吗？**

K 线层可以尝试（代码格式 `hk00700`、`usAAPL`），但**止损阈值和单只 3 成上限是按 A 股设计的**，跨市场务必自行调整 policy。

**Q: 会不会自动下单？**

不会。本包不含任何券商交易接口，只读数据、只做计算与提示。

**Q: `DataUnavailable` 怎么处理？**

```python
from market_guard import DataFeed, DataUnavailable
try:
    bars = feed.get("sh600519", "month", 40)
except DataUnavailable as e:
    print(f"所有数据源都不可用: {e}")   # e 里含每个源的失败原因
    # 降级：跳过结构检查，而不是把空数据当"没风险"
```

**绝不要**把异常吞掉后返回空列表——空列表会让下游算出"均线没破"的假信号。

---

## 6. 术语

| 术语 | 含义 |
|---|---|
| `peak_value` | 账户历史最高收盘市值，止损基准 |
| 回撤 / drawdown | (peak − current) / peak |
| 维持担保比例 | totalAsset / totalDebt，融资账户的核心风险指标 |
| `stage` | 月线相对 5 月线：above / first / off2 |
| 三轨 | 百分比轨（深度）、结构轨（破位）、速率轨（速度） |
| 体系均线 | 5/10/20/30/55/60/89/120/144/250 日线 |

---

## 7. 许可与免责

MIT License。

本工具包仅提供技术计算与纪律提示，**不构成投资建议**。它不连接券商、不下单。
使用者的全部决策与风险由其自行承担。
