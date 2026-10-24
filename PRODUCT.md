# HyperTest One

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

测试 / QA 工程师，以及负责版本质量的研发负责人。用户在日常测试工作中提交需求和代码版本，跟踪测试任务，定位失败，并核对可发布结论的证据。此用户范围已由项目负责人确认。

## Product Purpose

一次输入，一个使命，完整测试闭环。将 PRD、固定的仓库提交和测试环境转化为可治理、可验证、可追溯的测试资产与质量判定。成功意味着用户能够清楚判断测试进度、失败原因、覆盖缺口、正式执行结果与判定依据。

## Positioning

面向用户是 AI Test Engineering Workbench；架构上是 Autonomous Testing Control Plane。HyperTest 编排测试 Mission；Codex 等可替换 Harness 提供智能，可信 Runner 提供执行事实，平台根据策略作出决策。Agent 会话与自述不能代替测试状态或正式证据。

## Operating Context

仅在 PC 端宽屏使用；本轮界面统一以桌面宽屏操作效率为目标，无须适配移动端和竖屏。既有窄屏样式可保留，不作为本轮设计或验证范围。

创建项目 → 提交仓库与固定 SHA → 粘贴或导入 PRD → 配置策略 → 确认不可变输入 → 提交后台测试周期 → 查看任务、执行、证据、发现和质量判定。后台 Worker 独立推进工作，关闭浏览器不取消任务。保留显式干预、取消、重试与历史查看入口。

## Capabilities and Constraints

- 沿用 Next.js、React、Ant Design、TanStack Query 和现有 API，不改变后端业务契约。
- Canonical chain：Requirement → Risk → TestCase → Implementation → Execution → Evidence → Finding → Verdict。
- Proposal 需平台验证才能进入 Canonical State；正式事实来自可信执行通道。
- 任务完成、设计覆盖完成、执行通过、可发布是不同概念；缺失事实和未知覆盖不能呈现为成功或零缺口。
- 固定 SourceSnapshot 与 PolicySnapshot；变更实质输入创建新 Run。重试保留历史，禁止静默重复正式执行。
- 当前支持路径与运行限制以代码和规范为准；不可将长远规划宣传为已实现功能。
- 网络访问与授权取决于实际部署。前端改版不得改变数据、凭据、部署访问边界。

## Brand Commitments

名称为 HyperTest One。表达专业、清晰、精致，适合测试工程师日常使用。文案直接说明动作、状态、错误与恢复方式。中文与英文界面同等维护；需求、代码、日志和证据保留原始内容。

## Evidence on Hand

四份基础规范是产品规则的原始权威，优先级依次为领域模型、任务协议、技术架构、白皮书；本文件是设计摘要，不能覆盖规范。

- `docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md`
- `docs/protocol/TEST_MISSION_PROTOCOL.md`
- `docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md`
- `docs/foundation/HYPERTEST_WHITEPAPER.md`
- `docs/WEB_PRODUCT_WORKFLOW.md` 与现有 Web / API 实现。

历史验收记录不能证明当前服务健康。演示数据必须清楚标明为合成数据，不得伪造客户、覆盖率或上线结论。

## Product Principles

1. 先呈现决定下一步行动的信息：进度、阻塞原因、质量结论和证据。
2. 所有结论可回到正式执行与可信证据；Agent Activity 为辅助信息。
3. 保留用户输入、已加载内容和历史，明确未知、失败和可恢复状态。
4. 日常操作以清晰和效率为先，渐进展示底层细节。
5. 保持 Agent 独立、可审计、可复现，避免将提供方术语作为产品导航。

## Accessibility & Inclusion

保留中英文切换及切换前的表单与页签状态。键盘可完成核心操作，焦点可见。状态同时使用文字与颜色，长文本可阅读。适配范围为 PC 宽屏。未指定认证等级，不宣称满足未经验证的无障碍标准。
