# data 模块｜进度

## Done
- 明确模块边界、数据契约、校验与聚合规则（见 `docs/modules/data/requirements.md`）
- 确定初版存储方案方向：本地缓存（SQLite 优先）
- 确定初版必须提供离线 provider（CSV/本地文件导入）
- 建立 data 模块代码骨架（模型/Provider 接口/SQLite store/校验/聚合/服务层）
- 增加脚本：
  - `scripts/data_import_csv.py`（CSV → SQLite）
  - `scripts/data_selfcheck_csv.py`（CSV 校验/缺口/聚合自检）
- 最小端到端验证通过：`examples/csv/000001.SZ.csv` → 导入 SQLite → 读取 → 聚合（见 `scripts/data_e2e_smoketest.py`）
- 新增在线 provider（免费 Token 可用）：Tushare Pro 1m 接入（`stock_management/data/providers/tushare_provider.py`）
- 新增脚本：
  - `scripts/data_fetch_tushare.py`（Tushare → SQLite，需要 `TUSHARE_TOKEN`）
  - `scripts/data_parse_tushare_sample.py`（离线解析样例，验证字段映射）
- 新增在线 provider（无需 Token，免费优先）：Eastmoney 1m K线接入（`stock_management/data/providers/eastmoney_provider.py`）
- 新增脚本：
  - `scripts/data_fetch_eastmoney.py`（Eastmoney → SQLite）
  - `scripts/data_parse_eastmoney_sample.py`（离线解析样例，验证字段映射）
- 增强 Eastmoney 访问稳定性：限流 + 重试退避（`stock_management/data/providers/eastmoney_provider.py`）
- 修正 Eastmoney 1m 时间戳口径：将“分钟结束时间”归一化为“分钟开始时间”（减 1 分钟），避免开盘首分钟缺失导致重复拉取
- 统一脚本默认数据目录：仓库根 `data/`（避免在 `scripts/` 下生成 `scripts/data/`）
- 新增 provider 回退封装：`stock_management/data/providers/fallback_provider.py`
- 新增缓存优先刷新语义：`DataService.ensure_1m`（`stock_management/data/service.py`）

## Doing
- （暂无）

## Next
- 明确并固化 `ts` 的定义（分钟开始/结束）与全项目一致性策略
- 补充：在线 provider 的限流/重试/分页策略（按真实运行反馈迭代）

## Blockers
- 免费在线数据源尚未选定（先用离线 provider 推进开发）
