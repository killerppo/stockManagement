# storage 模块｜进度

## Done
- 明确初版存储方案与表结构（见 `docs/modules/storage/requirements.md`）
- 实现信号 SQLite 存储与查询脚本：
  - `stock_management/storage/signal_store.py`
  - `scripts/storage_selfcheck.py`
  - `scripts/storage_list_signals.py`

## Doing
- （暂无）

## Next
- 与 app 模块打通：刷新后写入 signals 日志
- 增加导出 CSV（后置）

## Blockers
- 依赖 signals 模块的信号字段最终定稿。
