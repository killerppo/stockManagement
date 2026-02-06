---
name: a-share-signal-tool
description: "Project governance for stockManagement. Use when working on this repo to enforce doc-first development: implement features strictly based on docs; when changing functionality, update docs before code. Require each module to have a requirements doc and a progress doc, and keep them updated."
---

# 编写规范与原则（只管流程与规范，不定义功能细节）

## 0. 文档优先（Doc-First）
- 所有功能实现必须以文档为准：先读文档、再写代码。
- 任何“功能修改/行为变更/字段变更/接口变更/默认参数变更”，必须**先修改文档**，再修改代码；禁止直接改代码“顺便”改逻辑。
- 如果发现文档缺失或不明确：先补文档（至少写到能验收），再实现。

## 1. 文档层级与约束
- `docs/PRD.md`：产品级需求（范围锚点、MVP边界、统一术语）。
- `docs/modules/<module>/requirements.md`：模块需求与接口约定（模块内的“必须/不做/输入输出/边界”）。
- `docs/modules/<module>/progress.md`：模块进度（做了什么/下一步/阻塞项/变更记录摘要）。
- 约束：模块代码不允许引入跨模块的隐式依赖；任何跨模块交互必须在双方模块的 `requirements.md` 中写清楚（输入/输出/错误处理/版本化策略）。

## 2. 模块文档要求（每个模块两份文档）
- 每个模块必须同时具备：
  - 一份需求文档：`docs/modules/<module>/requirements.md`
  - 一份进度文档：`docs/modules/<module>/progress.md`
- 新增模块时：先创建上述两份文档（写清楚边界与接口），再创建代码目录/文件。

## 3. 开发流程（每次改动都按这个走）
1) 定位影响范围：对应到 `docs/PRD.md` 与相关模块文档
2) 先更新文档：补充/修订需求与验收点，更新模块 `progress.md`
3) 再改代码：只实现文档已定义的内容
4) 完成后回填：在 `progress.md` 记录本次变更摘要与下一步

## 4. 代码组织原则（语言无关）
- 单一职责：模块内部职责清晰，避免“全能模块”。
- 公开接口稳定：模块对外暴露的函数/类/CLI参数等必须在该模块 `requirements.md` 写清楚。
- 可复现：同一输入数据 + 同一参数 → 同一输出结果（尤其是指标/信号类逻辑）。
- 可回滚：变更默认行为时必须在文档记录（必要时引入版本号或配置开关）。
- 最小改动：一次提交/一次变更只做一件事，避免混杂重构与需求变更。

## 5. 文档写作规范（简洁可验收）
- 需求文档只写“必须/不做/边界/验收点”，避免长篇背景叙述。
- 进度文档按条目记录：`Done / Doing / Next / Blockers`（不要求复杂模板，但要可追踪）。
