# indicators 模块｜进度

## Done
- 明确初版指标清单与默认参数（见 `docs/modules/indicators/requirements.md`）
- 实现指标计算与自检脚本：`stock_management/indicators/*`、`scripts/indicators_selfcheck.py`

## Doing
- （暂无）

## Next
- 与 signals 模块对接：提供统一的指标计算入口（按参数集输出 dict）

## Blockers
- 依赖 data 模块的数据接口定义。
