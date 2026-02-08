# backtest 模块｜进度

## Done
- 编写回测需求文档与范围约定
- 实现回测引擎与 CLI（`scripts/backtest_breakout_5m.py`）
- 最小验证：模块可导入
- 实测：`000001.SZ`（2026-02-06 09:30-15:00）无信号、无交易
- 实测：watchlist（2026-02-06 09:30-15:00）`signals=4` 但 `trades=0`（触发信号未成交）
- 增加回测完善项：入场模式、成本（fee/slippage）、逐笔 CSV 输出、更多指标
- 实测：watchlist（2026-02-06 09:30-15:00，entry_mid，fee=1bp，slippage=2bp）`signals=4` / `trades=0`，输出 `data/backtest_trades.csv`

## Doing
- （暂无）

## Next
- 在有缓存数据时做一次完整回测样例

## Blockers
- （暂无）
