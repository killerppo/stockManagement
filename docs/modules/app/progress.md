# app 模块｜进度

## Done
- 定义 app 的最小 CLI 入口与刷新策略（见 `docs/modules/app/requirements.md`）
- 实现最小 CLI：`scripts/app_refresh_watchlist.py`
- 打通信号联动：支持 `--signals` 输出（短线突破 5m）
- 支持信号落库：`--log-signals` 写入 `data/signals.sqlite`

## Doing
- （暂无）

## Next
- 增加更合理的 session 策略（仅盘中循环）
- 增加一条“推荐用法”示例到 README（后续）

## Blockers
- （暂无）
