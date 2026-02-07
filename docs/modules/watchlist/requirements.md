# watchlist 模块｜需求

## 目标
- 管理自选股列表（≈50 只）：分组、备注、启用/禁用。
- 为 data 模块批量刷新提供“符号列表输入”。

## 模块边界
- 本模块负责：自选股配置文件格式、解析/校验、按条件筛选输出。
- 本模块不负责：拉行情（由 data 模块负责）、指标与信号、通知与下单。

## 数据格式（初版：CSV，纳入版本管理）
路径：`config/watchlist.csv`

字段（列）：
- `symbol`（必填）：形如 `000001.SZ` / `600000.SH`
- `group`（可选）：分组名（例如 `shortterm` / `swing` / `watch`）
- `enabled`（可选）：`1`/`0`（默认 `1`）
- `note`（可选）：备注（不做语义解析）

约束：
- `symbol` 必须唯一（大小写不敏感，存储时统一大写）。
- 允许空行与以 `#` 开头的注释行（解析时跳过）；但表头行必须是有效 CSV header（不能注释）。

## 对外接口（供脚本/上层使用）
- `load_watchlist(path) -> list[WatchItem]`
- `filter_watchlist(items, group=None, enabled_only=True) -> list[WatchItem]`
- `validate_watchlist(items) -> list[Issue]`（问题列表为空视为通过）

## 验收点（MVP）
- 在没有任何在线数据源的情况下，可加载并校验 `config/watchlist.csv`
- 可按 `group` 过滤输出符号列表
- 与 data 模块联动：对 watchlist 批量执行 `ensure_1m`（Eastmoney 主用）
