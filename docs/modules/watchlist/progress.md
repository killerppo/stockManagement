# watchlist 模块｜进度

## Done
- 定义 watchlist CSV 格式与模块接口（见 `docs/modules/watchlist/requirements.md`）
- 实现解析/校验与示例配置文件：`config/watchlist.csv`
- 新增脚本：
  - `scripts/watchlist_validate.py`（校验自选股）
  - `scripts/watchlist_fetch_eastmoney.py`（批量抓取分钟数据到 SQLite 缓存）
- 新增保存接口：`save_watchlist(...)`，支持 GUI 写回 CSV
- GUI 支持 watchlist 的可视化增删改查（Add/Edit/Delete/Save）

## Doing
- （暂无）

## Next
- 增加导入/导出能力（例如从粘贴列表快速生成 CSV）
- 与 app 模块打通：提供统一 CLI 入口与日志输出

## Blockers
- （暂无）
