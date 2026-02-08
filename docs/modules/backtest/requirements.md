# backtest 模块｜需求

## 目标
- 基于本地缓存数据回测现有策略（`breakout_5m_v1`），输出效果指标。
- 支持基础参数优化（网格搜索）以改进效果。

## 范围（已确认）
- 数据来源：缓存优先（`data/bars.sqlite`，由 data 模块维护）。在 GUI/脚本配置了 provider 且缓存覆盖不足时，允许 data 模块直接拉取 5m/15m/60m 用于回测（以日志为准）。
- 频率：以 5m bar 为主（优先由 1m 聚合；必要时可由 provider 直接提供 5m）。
- 策略：`breakout_5m`（signals 模块）。
- 不涉及：实盘下单、通知、图形化结果。

## 输入
- `symbol` 或 watchlist（`config/watchlist.csv` + `group` 过滤）。
- 时间窗口 `start/end`（ISO 时间，支持 `Asia/Shanghai`）。
- 回测参数：`fill_bars`、`hold_bars`、`tp_level`、`exit_priority`、`entry_mode`。
- 交易约束：**一律按 A 股 T+1**（当日买入不能当日卖出；详见回测规则）。
- 成本参数（固定手续费）：买入固定 `5` 元、卖出固定 `6` 元（CNY/笔）。
  - 为了将固定费用折算为收益率，回测需指定 `position_cash_cny`（每笔入场使用的资金，默认 10000 CNY），并按 A 股 100 股一手取整计算股数。
- 滑点参数（可选）：`slippage_bps`（双边计入，用于执行价偏移；默认 0）。
- 策略参数：`BreakoutParams`（`lookback`、`vol_factor`、`atr_buffer_k`、`pct_buffer`、`swing_lookback`）。

## 输出
- 控制台摘要：`trades` / `win_rate` / `avg_return` / `avg_r` / `profit_factor` / `max_drawdown`。
- 可选输出：逐笔交易明细（CSV）。

## 回测规则（MVP）
- 信号生成：使用 `breakout_scan_5m` 在窗口内扫描。
- 入场：信号后 `fill_bars` 内若价格区间覆盖目标价，则成交；否则忽略该信号。
  - `entry_mode=entry_mid`：使用入场区间中值
  - `entry_mode=entry_low`：使用入场区间下沿
  - `entry_mode=entry_high`：使用入场区间上沿
  - `entry_mode=trigger`：使用触发价（初版等同 `entry_low`）
- 出场：**受 T+1 约束**，成交当日不允许出场；从**下一交易日的第一根 bar 起**才开始逐根检查触发 `stop_loss` 或 `take_profit(tp_level)`。
  - 同一根 bar 同时触发时，按 `exit_priority`（`stop_first` / `tp_first`）。
- 期限：从“允许出场的第一根 bar”开始计数，超过 `hold_bars` 未触发则按最后一根 bar 的 `close` 平仓。
- 交易互不影响（不做持仓冲突与资金管理）。
- 成本：
  - 固定手续费：买入 -5 元、卖出 -6 元（从 PnL 中扣除）
  - 滑点：`slippage_bps` 双边计入（入场加价，出场减价）

## 评估指标（MVP）
- `trades`、`wins`、`win_rate`
- `avg_return`、`avg_r`
- `avg_win`、`avg_loss`、`expectancy`
- `profit_factor`
- `max_drawdown`（按累计收益曲线计算）

## 参数优化（MVP）
- 网格搜索默认覆盖 `lookback` 与 `vol_factor`，其他参数固定。
- 评价指标默认 `avg_return`（可选 `win_rate` / `profit_factor` / `avg_r`）。
- 输出最佳参数与指标。

## CLI 约定
- 脚本：`scripts/backtest_breakout_5m.py`
- 支持 `--symbol` 或 `--watchlist/--group`
- `--start/--end` 必填
- `--optimize` 触发优化
- `--trades-csv` 输出逐笔交易明细

## app 集成约定
- app 提供回测窗口：可触发回测/优化、展示摘要、可导出 CSV

## 验收点
- 在已有缓存数据下可运行回测并输出指标。
- 可执行一次参数优化并输出最佳参数。
