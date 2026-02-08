# backtest 模块｜进度

## Done
- 编写回测需求文档与范围约定
- 实现回测引擎与 CLI（`scripts/backtest_breakout_5m.py`）
- 最小验证：模块可导入
- 实测：`000001.SZ`（2026-02-06 09:30-15:00）无信号、无交易
- 实测：watchlist（2026-02-06 09:30-15:00）`signals=4` 但 `trades=0`（触发信号未成交）
- 增加回测完善项：入场模式、成本（fee/slippage）、逐笔 CSV 输出、更多指标
- 实测：watchlist（2026-02-06 09:30-15:00，entry_mid，fee=1bp，slippage=2bp）`signals=4` / `trades=0`，输出 `data/backtest_trades.csv`
- app 集成：回测窗口（回测/优化/摘要/CSV）
- GUI 回测验证：summary 000001.SZ trades=0 / summary 002519.SZ trades=0 / summary ALL trades=0（signals=4 skipped=4）
- AkShare 长窗口验证：`002519.SZ`（2026-01-05 09:30-2026-02-06 15:00，5m）`signals=39` / `trades=15` / `win_rate≈46.67%`（证明长窗口数据覆盖后回测可产出有效指标）

## Doing
- （暂无）

## Next
- 在有缓存数据时做一次完整回测样例

## Blockers
- （暂无）
