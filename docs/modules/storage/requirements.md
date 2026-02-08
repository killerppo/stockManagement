# storage 模块｜需求

## 目标
- 记录信号日志与复盘所需快照，支持筛选与导出（格式后续补充）。

## 范围（已确认）
- 记录信号触发时间、触发价、周期、参数快照、指标快照、原因列表
- 支持复盘：可按条件查询（字段细则后续补充）

## 模块边界
- 本模块负责：信号/复盘数据的本地持久化与读取。
- 本模块不负责：生成信号（signals）、计算指标（indicators）、获取行情（data）。

## 存储方案（初版：SQLite）
- 文件路径：`data/signals.sqlite`（不入库，见 `.gitignore`）
- 表：`signals`

### signals 表字段（初版）
- `id`：INTEGER PRIMARY KEY
- `symbol`：TEXT
- `ts`：INTEGER（epoch seconds，UTC）
- `freq`：TEXT（如 `5m`）
- `strategy_id`：TEXT（如 `breakout_5m_v1`）
- `direction`：TEXT（Entry/Exit/Risk/Watch）
- `score`：INTEGER
- `entry_low` / `entry_high`：REAL
- `stop_loss`：REAL
- `tp1` / `tp2`：REAL
- `reasons_json`：TEXT（JSON array）
- `risk_flags_json`：TEXT（JSON array）
- `params_json`：TEXT（JSON object：策略参数 + 指标参数快照）
- `created_at`：INTEGER（epoch seconds，UTC）

### 去重约束
- 同一 `symbol + ts + freq + strategy_id` 只保留一条（UNIQUE）。
- 重复插入默认忽略（不更新），避免循环刷新时重复写日志。

## 对外接口（供 app 使用）
- `init()`
- `insert_signals(signals, strategy_id, params_snapshot) -> inserted_count`
- `list_recent(limit=50, offset=0, symbol=None) -> list[SignalRow]`（用于 GUI 分页）
- `count_signals(symbol=None) -> int`（用于 GUI 计算页数/禁用翻页）

## 约束
- 任何日志字段变更必须先更新此文档与 `docs/PRD.md`，再改代码。

## 验收点（待补充）
- 能将 signals 模块输出的信号写入 SQLite，并通过 UNIQUE 约束去重
- 能列出最近 N 条信号用于复盘/调试
