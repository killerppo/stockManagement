# app 模块｜需求

## 目标
- 提供统一入口（CLI + GUI），把日常操作收敛为“刷新数据 → 扫描信号 → 查看结果”。
- GUI 优先：减少命令行复杂度。

## 范围（已确认）
- 以 `docs/PRD.md` 为准，仅实现已文档化功能。
- 支持最小闭环：watchlist → data.ensure_1m →（可选）signals 扫描 →（可选）storage 落库 → GUI 展示。

## 输入
- 自选股：`config/watchlist.csv`
- 数据缓存目录：`data/`（`data/bars.sqlite`）
- 信号库：`data/signals.sqlite`
- 数据源：GUI 可选 `akshare` / `eastmoney`（默认 `akshare`）

## 输出
- GUI 列表 + 日志（不做通知推送）
- 调试日志：记录按钮点击与关键参数快照，便于排查

## 运行模式
- CLI（脚本）：单次 / 循环（已实现）
- GUI（桌面窗口）：按钮式操作 + 循环模式（本次增强优先做）

## 刷新窗口策略
- 刷新（Refresh）：覆盖最近 `window_minutes`（默认 60）或用户指定的 `start/end`
- 信号扫描（Scan）：使用 `signal_window_minutes`（默认 240）窗口，扫描区间内所有 5m 触发点
- 数据覆盖说明：Refresh Cache 目前以 1m 缓存为主；若某 provider 的 1m 历史覆盖有限（例如 AkShare 1m 可能仅最近若干交易日），Scan/回测/K线 在需要时会通过 data 模块直接拉取 5m/15m/60m 以覆盖用户指定窗口（以日志提示为准）

### 固定窗口（Start/End）约定
- GUI 提供 Start/End 选择能力（Pick 对话框与快捷按钮），输出统一格式：`YYYY-MM-DDTHH:MM:SS+08:00`
- 当启用固定窗口时：
  - Refresh 使用 `[start, end)` 作为数据窗口
  - Scan 使用 `[start, end)` 作为扫描窗口（忽略 `signal_window_minutes`）
  - K线与回测使用 `[start, end)` 作为展示/回测窗口（忽略 bars 数与回溯窗口）
- 当未启用固定窗口时：
  - Refresh 使用 “当前分钟回溯 window_minutes”
  - Scan 使用 “当前分钟回溯 signal_window_minutes”
  - K线使用 bars 数回溯窗口
  - 回测使用 window_minutes 作为默认窗口
- 当不启用固定窗口时：以“当前分钟”为 `end`，回溯 `window_minutes` 作为 Refresh 窗口

## GUI（MVP+）
启动：`python scripts/app_gui.py`

### 页面/区域
- Watchlist 表格：symbol/group/enabled/最近时间/最近收盘价/本次变更数
- Signals 表格：信号列表（从 `data/signals.sqlite` 读取，支持分页：上一页/下一页 + 每页条数）
- Signal Details：选中某条信号后展示 reasons / params / risk_flags
- Log：运行日志与错误
- K线视图：展示选中标的的 K 线（1m/5m/15m/60m），用于快速确认走势
  - 缓存优先（`data/bars.sqlite`）；当选择 provider 且缓存覆盖不足时，可能直接拉取 5m/15m/60m 以覆盖展示窗口（不做指标叠加与复杂交互）
- 回测视图：可在 GUI 触发回测与参数优化，展示摘要与（可选）逐笔 CSV

### 操作按钮（必须）
- Reload Watchlist
- Refresh Cache
- Scan Signals
- Refresh+Scan（一键执行）
- Reload Signals
- Start Loop / Stop（循环刷新；可选每轮自动 Scan）
- Show Kline（打开 K 线窗口）
- Backtest（打开回测窗口）
- Watchlist Add / Edit / Delete / Save（GUI 内可视化维护）

### 配置项（必须）
- group 过滤、limit
- window_minutes、signal_window_minutes
- start/end（可选，指定则用于一次性跑窗；循环模式通常留空）
- loop interval（秒）
- Log signals to SQLite（开关）
- 策略参数（初版：breakout_5m）可在 GUI 调整并影响扫描结果与落库 params
- 回测参数：entry_mode、fill_bars、hold_bars、tp_level、exit_priority、fee_bps、slippage_bps
- 回测优化：lookback/grid、vol_factor/grid、metric

## 不做（后置）
- K线/指标曲线图（先只做表格与文本明细）
- 通知推送、自动下单、全市场扫描

## 验收点（GUI）
- 能加载并校验 watchlist
- 能刷新缓存并更新 Watchlist 表格的最近时间/收盘价/变更数
- 能扫描信号并在 Signals 表格展示；选中信号可看 Details
- 循环模式可稳定运行；Stop 能中断当前任务与循环
- K线窗口能展示选中标的的 1m/5m/15m/60m K 线
- Watchlist 可在 GUI 增删改查并正确写回 `config/watchlist.csv`
- 回测窗口可执行回测与优化，输出摘要并可导出逐笔 CSV
