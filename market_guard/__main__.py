# -*- coding: utf-8 -*-
"""
market_guard.__main__ — 命令行入口

    python -m market_guard radar --account account.json --peak 200000
    python -m market_guard cycle --code sh000001
    python -m market_guard trend --code sh600519 --period month
    python -m market_guard demo
"""
import argparse
import json
import sys


def cmd_radar(args):
    from .radar import RiskRadar, AccountSnapshot
    if args.peak is None:
        print("提示：未提供 --peak（历史最高收盘市值），回撤将无法计算。")
    acc = AccountSnapshot.from_json(args.account)
    radar = RiskRadar(acc, peak_value=args.peak,
                      check_structure=not args.no_structure)
    rep = radar.scan()
    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1))
    else:
        print(rep.to_text())
    return 0


def cmd_cycle(args):
    from .datafeed import DataFeed
    from .cycle import assess_cycle
    feed = DataFeed(verbose=args.verbose)
    bars = feed.get(args.code, "month", 60)
    view = assess_cycle(bars, low_price_surge=args.low_price_surge)
    print(view.summary())


def cmd_trend(args):
    from .datafeed import DataFeed
    from .indicators import trend_stage, support_lines, resonance, avg_deviation
    feed = DataFeed(verbose=args.verbose)
    bars = feed.get(args.code, args.period, 320)
    if args.period == "month":
        st = trend_stage(bars)
        print(json.dumps(st, ensure_ascii=False, indent=1))
    else:
        sup = support_lines(bars)
        print(f"最新收盘 {bars[-1].close}")
        print("均线位置：")
        for s in sup:
            flag = "支撑" if s["role"] == "support" else "压力"
            print(f"  MA{s['period']:<4} {s['value']:>10.2f}  "
                  f"偏离 {s['distance_pct']:>+7.2f}%  {flag}")
        print("共振：", json.dumps(resonance(bars), ensure_ascii=False))
        print("偏离5日线：", avg_deviation(bars, 5), "%")


def cmd_demo(args):
    from .radar import RiskRadar, AccountSnapshot
    # 注意：以下为**自洽的演示数据**，不代表任何真实账户。
    # 总资产 = 净资产 + 负债；持仓市值之和 = market_value
    acc = AccountSnapshot(
        date="demo(示例数据)",
        total_asset=130000.0, net_asset=100000.0,
        total_debt=30000.0, market_value=152000.0, cash=0.0,
        holdings=[
            {"code": "600519", "name": "示例蓝筹", "shares": 100,
             "price": 1680.0, "dayRate": -0.42},
            {"code": "000858", "name": "示例消费", "shares": 1000,
             "price": 145.0, "dayRate": 0.85},
            {"code": "300750", "name": "示例成长", "shares": 2000,
             "price": 62.0, "dayRate": -2.31},
        ],
    )
    radar = RiskRadar(acc, peak_value=200000, check_structure=False)
    print(radar.scan().to_text())


def main():
    ap = argparse.ArgumentParser(prog="market_guard",
                                 description="账户级风控与趋势工具包")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("radar", help="账户风控扫描")
    p1.add_argument("--account", required=True, help="账户快照 JSON 路径")
    p1.add_argument("--peak", type=float, default=None, help="历史最高收盘市值")
    p1.add_argument("--json", action="store_true")
    p1.add_argument("--no-structure", action="store_true", help="跳过均线抓取")
    p1.set_defaults(func=cmd_radar)

    p2 = sub.add_parser("cycle", help="大周期定性三问")
    p2.add_argument("--code", required=True, help="指数代码，如 sh000001")
    p2.add_argument("--low-price-surge", action="store_true",
                    help="低价股是否集体暴动")
    p2.add_argument("--verbose", action="store_true")
    p2.set_defaults(func=cmd_cycle)

    p3 = sub.add_parser("trend", help="趋势/均线分析")
    p3.add_argument("--code", required=True)
    p3.add_argument("--period", default="day", choices=["day", "week", "month"])
    p3.add_argument("--verbose", action="store_true")
    p3.set_defaults(func=cmd_trend)

    p4 = sub.add_parser("demo", help="跑一个内置样例")
    p4.set_defaults(func=cmd_demo)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
