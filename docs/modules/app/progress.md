# app 模块｜进度

## Done
- 定义 app 的最小 CLI 入口与刷新策略（见 `docs/modules/app/requirements.md`）
- 实现最小 CLI：`scripts/app_refresh_watchlist.py`
- 打通信号联动：支持 `--signals` 输出（短线突破 5m）
- 支持信号落库：`--log-signals` 写入 `data/signals.sqlite`
- 支持信号区间扫描：`--signals-scan` 输出窗口内触发点
- app 增加 GUI 需求约定（见 `docs/modules/app/requirements.md`）
- 实现桌面 GUI（Tkinter）：`scripts/app_gui.py`
- GUI 增强：Refresh+Scan、一键循环（Start Loop）、Signal Details 面板
- GUI 增强：支持 Start/End 选择（Use Start/End + Pick 对话框 + 今日快捷）
- GUI 增强：K 线窗口（1m/5m/15m/60m，基于缓存数据）
- GUI 增强：Watchlist 可视化增删改查并写回 CSV
- Refresh+Scan 使用 GUI 策略参数（lookback/vol_factor）
- 最小验证：`python scripts/watchlist_validate.py` 通过

## Doing
- （暂无）

## Next
- 增加更合理的 session 策略（仅盘中循环）
- 增加一条“推荐用法”示例到 README（后续）
- 增加指标叠加与更丰富的图表能力（后置）

## Blockers
- （暂无）
