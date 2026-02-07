# signals 模块｜需求

## 目标
- 依据指标与规则生成可解释信号，并计算入场区间/止损/止盈。

## 范围（已确认）
- 信号必须包含：入场价区间 / 止损位 / 止盈位（自动计算）+ 触发原因（可解释）
- 短线 + 波段策略（模板与参数后续补充）
- 去抖/冷却：避免同标的短时间重复触发（细则后续补充）

## 模块边界
- 本模块负责：策略模板、信号字段定义、入场/止损/止盈规则化计算、原因解释。
- 本模块不负责：行情抓取（data 模块）、指标计算（indicators 模块）、通知推送、下单。

## 信号输出字段（初版固定）
每条信号必须包含：
- `symbol`：如 `000001.SZ`
- `time`：信号触发时间（使用输入 bars 的最后一根时间戳）
- `freq`：信号运行周期（`1m/5m/15m/60m`）
- `direction`：`Entry | Exit | Risk | Watch`
- `score`：0–100
- `entry_zone`：`[entry_low, entry_high]`
- `stop_loss`：单值
- `take_profit`：支持 1–3 档（TP1/TP2/TP3）
- `reasons`：列表（每条包含：条件名、当前值、阈值、是否命中）
- `risk_flags`：列表（如：数据缺口、接近涨跌停、T+1 约束等；初版可先留空）

## 入场/止损/止盈计算（初版约定）
### 入场区间
- 触发价 `trigger`：由策略给出（如突破位/回踩位）
- 缓冲 `buffer`：`max(0.3 * ATR, 0.2% * trigger)`
- 突破买入：`[trigger, trigger + buffer]`

### 止损
默认优先使用结构止损（可配置后置）：
- 结构低点 `swing_low`：最近 N 根 bar 的最低价（N 默认 20）
- `stop_loss = swing_low - buffer`

### 止盈
默认用 R 倍目标：
- `R = entry_mid - stop_loss`，其中 `entry_mid = (entry_low + entry_high)/2`
- `TP1 = entry_mid + 1*R`，`TP2 = entry_mid + 2*R`（TP3 后置）

## 策略模板（初版先实现 1 套）
### 模板：短线突破（5m）
触发条件（示例，细则参数化后置）：
- 价格突破近 N 根最高价（N 默认 20）
- 当前成交量 > VOL_SMA * factor（factor 默认 1.5）
输出：
- direction=Entry，触发价为突破位
- 给出 entry/stop/tp 与 reasons

数据长度要求：
- 需要至少 `max(lookback+1, swing_lookback+1)` 根 5m bars；不足则不输出信号（返回 None）。

## 区间扫描（增强，当前优先实现）
为支持“盘中任意时刻触发点”的复盘与展示，策略需要支持区间扫描：
- 输入：一段连续的 `bars_5m`
- 输出：`list[Signal]`（按时间递增），每个 Signal 的 `time` 为对应触发 bar 的时间戳
- 去重：由 storage 模块按 `symbol+ts+freq+strategy_id` UNIQUE 约束实现；signals 模块只负责正确输出

### app 集成约定
- app 可通过 `--signals-scan` 开关启用扫描模式：
  - 输出窗口内所有触发信号（可限制打印条数，落库不限制）
  - 若不开启扫描，默认只评估最后一根 bar（保留原行为）

## 约束
- 同一输入数据 + 同一参数 → 同一信号输出
- 信号输出字段在此文档定义后，代码不得擅自变更

## 验收点（待补充）
- 给定一段 5m bars + 指标，能输出 0 或 1 条信号（只对最后一根 bar 评估）
- 信号包含入场/止损/止盈与 reasons，且可复现
