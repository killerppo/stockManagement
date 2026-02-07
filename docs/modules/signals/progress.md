# signals 模块｜进度

## Done
- 明确初版信号字段与入场/止损/止盈规则（见 `docs/modules/signals/requirements.md`）
- 实现第一套策略模板：短线突破 5m（`stock_management/signals/strategies/breakout_5m.py`）
- 增加最小脚本：`scripts/signals_breakout_5m.py`
- 增加区间扫描能力：输出窗口内所有触发点（`breakout_scan_5m`）

## Doing
- （暂无）

## Next
- 补齐更多模板（趋势回调/风控止盈止损等）
- 增加冷却/去抖状态机（后置）

## Blockers
- 依赖 indicators 模块的指标清单与参数规范。
