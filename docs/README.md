# 项目文档结构

- `docs/PRD.md`：产品级需求（范围锚点、MVP边界、统一术语）
- `docs/modules/<module>/requirements.md`：模块需求与接口约定
- `docs/modules/<module>/progress.md`：模块进度与变更摘要
  - 当前模块：`app` / `data` / `indicators` / `signals` / `storage` / `watchlist`

约束：任何功能修改必须先改文档再改代码。

## 项目逻辑（当前实现）
数据流（缓存优先）：
- `watchlist`：读取/校验 `config/watchlist.csv`，产出 symbol 列表
- `data`：通过 provider 拉取行情（1m 或高周期分钟 K），写入/读取本地缓存（`data/bars.sqlite`），对外提供 `get_bars()/ensure_1m()`
- `indicators`：在给定 bars 上计算指标序列（可复现、可参数化）
- `signals`：基于 bars + indicators 生成可解释信号（含入场区间/止损/止盈与 reasons）
- `storage`：将信号及参数快照落库（`data/signals.sqlite`，UNIQUE 去重）
- `backtest`：基于 bars_5m + signals 扫描结果模拟成交与收益指标

## GUI 与模块映射（scripts/app_gui.py）
- Reload Watchlist → `watchlist`（load/validate/save）
- Refresh Cache → `data.ensure_1m`（同步 1m 到本地缓存；不同 provider 的 1m 覆盖可能有限）
- Scan Signals → `data.get_bars("5m")` + `signals`（可选写入 `storage`）
- Show Kline → `data.get_bars(freq)`（缓存优先；必要时可直拉高周期以覆盖窗口）
- Backtest → `data.get_bars("5m")` + `backtest`

### 重要约定：Start/End 与回溯窗口
- 勾选 `Use Start/End`：Refresh/Scan/Kline/Backtest 使用同一 `[start, end)` 固定窗口
- 未勾选：按 `window_minutes` / `signal_window_minutes` 回溯形成滚动窗口（Loop 模式即持续滚动刷新/扫描）
