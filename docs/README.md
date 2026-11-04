# 文档导航

文档中的设计合同、源码实现、某次部署和用户验收是不同状态。日期、提交号、镜像和检查结果只说明相应记录的时点；查询当前运行状态时应实际核实，不能取历史记录中最后出现的“当前”作为依据。

## 现行入口

- [Cloud 任务内对话与多会话交付（2026-11-04）](CLOUD_CONVERSATION_DELIVERY_20261104.md)及 [ADR-039](architecture/ADR-039_CLOUD_CONVERSATION_BRIDGE.md)：公开消息持久化、文字回复、槽隔离与显式续接；实现、部署和用户验收分别记录。
- [当前待办](TODO.md)：未完成的开发、操作和用户验收。
- [Cloud 原会话受限检查（2026-11-03）](CLOUD_NATIVE_SESSION_INSPECTION_20261103.md)：原执行对账与历史检查边界；后续显式续接由 ADR-039 替代一律未支持的旧声明。
- [Cloud 原生 Harness Web UI 入口（2026-11-03）](CLOUD_HARNESS_WEB_LINK_20261103.md)：任务详情复用现有 3080 原生页面，提供会话 ID；页面交付和实际会话浏览验收分别记录。
- [ADR-038：Cloud 聚焦任务输入、下发与产物归档](architecture/ADR-038_TASK_FOCUSED_CLOUD_INPUTS.md) 与 [Cloud 任务指南](CLOUD_TASK_WORKFLOW.md)：项目详情管理仓库，创建填写任务名称及 MR/PR 地址，环境由可选 prompt 说明；移除资源页和预期部署版本。
- [Cloud 指定任务源码准备恢复（2026-11-03）](CLOUD_SOURCE_RECOVERY_20261103.md)：关闭已隔离的失败准备、确认框架 master 与新开始请求；排队、执行和结果分别记录。
- [Cloud 一键开始测试（2026-11-03）](CLOUD_ONE_CLICK_START_DELIVERY_20261103.md)：服务端自动准备后下发、源码详情折叠及旧框架入口展示清理；已部署，原恢复任务与用户验收分别记录。
- [Cloud E2E 测试说明模板（2026-11-03）](CLOUD_TEST_PROMPT_TEMPLATE_20261103.md)：默认折叠、当前 MR 地址、复制辅助及两次 subagent 审查要求；实现、部署和用户验收边界。
- [Cloud MR 链接创建交付（2026-11-03）](CLOUD_MR_INPUT_DELIVERY_20261103.md)：MR 链接输入、可选说明与框架 main 的前轮实现、自测及部署记录；现行创建页面保留任务名称输入，见上述指南。
- [Cloud 任务职责精简交付（2026-11-03）](CLOUD_TASK_FOCUS_DELIVERY_20261103.md)：前一轮资源和环境入口退休的实现、自测及部署。
- [产品白皮书](foundation/HYPERTEST_WHITEPAPER.md)、[技术架构](architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)、[测试任务协议](protocol/TEST_MISSION_PROTOCOL.md)、[领域模型与状态机](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)：按 [AGENTS.md](../AGENTS.md) 的优先级及后续 ADR 增补阅读。
- [当前系统架构总览（2026-10-28）](architecture/SYSTEM_ARCHITECTURE_OVERVIEW_20261028.md)：当前实现、部署拓扑与外部集成（DeepSeek Harness、PowerContext 等）的全景快照；运行状态仍须现场核实。
- [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 与 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)：新 Local 显式归档及安装授权；旧 SessionTask 的合同与恢复只适用于仍存在的旧路径，清理按 ADR-028 执行。
- [CLI 全项目授权交付（2026-10-28）](CLI_GLOBAL_AUTHORIZATION_DELIVERY_20261028.md)：存量授权迁移、0.1.2 发行、本机部署和用户验收边界。
- [Local 任务上传身份清理（2026-11-01）](LOCAL_UPLOADER_RETIREMENT_DELIVERY_20261101.md)：任务级旧身份入口退役、授权回归和本机部署。
- [Local 任务状态独立管理交付（2026-11-03）](LOCAL_TASK_STATUS_DELIVERY_20261103.md)：独立状态接口、管理历史、权限/幂等回归及专用任务页面实测。
- [ADR-037：Local 任务状态独立管理](architecture/ADR-037_LOCAL_TASK_STATUS_MANAGEMENT.md)：单独保存任务进度和原因，保留结果、汇总、归档及原 key 恢复。
- [ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md)：快速原型期替代不兼容旧实现与定向清除旧数据的决策。
- [服务器操作](SERVER_OPERATIONS.md)：现行本机容器测试环境的操作规则和入口；运行身份以现场检查为准。
- [PowerContext 服务](POWERCONTEXT_SERVICE.md)及 [Cloud 实现状态](CLOUD_IMPLEMENTATION_STATUS.md)：各自能力与范围，部署和验收以具体轮次记录为准。
- [Cloud Worker 首轮进展（2026-10-29）](CLOUD_WORKER_FIRST_SLICE_20261029.md)：本机准入阻塞、报告读回修复及项目框架合成回归。
- [Cloud 任务管理与资源页历史交付（2026-10-30）](CLOUD_TASK_MANAGEMENT_DELIVERY_20261030.md)：当时的草稿编辑、任务删除及部署边界；资源页已由 ADR-038 决定移除，不再作为当前使用入口。
- [ADR-029 草案：单次 Cloud Attempt 的 Docker 隔离](architecture/ADR-029_CLOUD_ATTEMPT_DOCKER_ISOLATION_PROPOSAL.md)：待实现、待验证的备选方案，不改变现行准入。
- [ADR-030 草案：Cloud 受控认证与外部写入](architecture/ADR-030_CLOUD_AUTHENTICATED_ACTION_PROPOSAL.md)：待实现的凭据、单次发送与业务终态边界。
- [ADR-031：云端 Harness 原生配置](architecture/ADR-031_CLOUD_NATIVE_HARNESS_CONFIGURATION.md)：模型、推理和插件由云端 Harness profile 管理，新任务不设置平台预算；远程能力与部署验收分别记录。
- [ADR-034：Cloud 列表删除与执行收尾分离](architecture/ADR-034_CLOUD_DELETION_AND_RECOVERY.md)：已请求取消且已隔离写入权的待恢复任务可移出列表，UNKNOWN 与受限对账能力保留。
- [ADR-035：宿主原生完成后的任务管理](architecture/ADR-035_NATIVE_COMPLETION_MANAGEMENT.md)：保留未知观察范围，正常完成后允许独立复测与删除，已知未决操作继续阻断。
- [ADR-036：薄 Worker 领取失答恢复](architecture/ADR-036_WORKER_CLAIM_RECOVERY.md)：有界 sequence 高水位、原 key 封口与 fence、空闲故障退避；不重放任务，旧无序号记录保持 UNKNOWN 并受控退役。
- [宿主原生完成管理闭环交付（2026-11-03）](CLOUD_NATIVE_COMPLETION_DELIVERY_20261103.md)：复测/删除准入修复、相关回归、本机镜像及尚未恢复的独立领取问题。
- [薄 Worker 领取恢复与真实闭环（2026-11-03）](CLOUD_WORKER_CLAIM_RECOVERY_DELIVERY_20261103.md)：领取恢复、SDK 退出崩溃、只读 Git 重试和撤权解析删除修复；本机部署及两次真实成功运行、失败保留和删除/历史读回。
- [Cloud 网页主流程实际验收（2026-11-03）](CLOUD_WEB_LIFECYCLE_ACCEPTANCE_20261103.md)：真实页面创建、解析、下发、结果原文、独立复测、删除及历史查看；Git 解析与页面准入修复、当前本机版本及两轮各 3 项原生测试通过。
- [ADR-032：快速原型期的轻量 Harness Worker](architecture/ADR-032_LIGHTWEIGHT_HARNESS_WORKER.md)：项目笔记与已决定的职责边界；全容器化是未来资源隔离方向，实现和部署分别记录。
- [Cloud 原生交互 SDK 构建（2026-11-02）](CLOUD_NATIVE_INTERACTION_SDK_BUILD_20261102.md)：固定上游、锁文件构建修复与配套包验证。
- [Cloud Agent 运行中提问调查（2026-11-02）](CLOUD_AGENT_INTERACTION_INVESTIGATION_20261102.md)：官方 SDK 能力、模拟验证、构建阻塞与未实现的交互通道。
- [轻量 Harness Worker 本机交付（2026-11-02）](CLOUD_LIGHTWEIGHT_WORKER_DELIVERY_20261102.md)：宿主 Worker、API/Web 部署和合成验证；真实 Harness、项目测试与用户验收分别记录。
- [云端仓库与项目范围提示修正（2026-11-02）](CLOUD_PROJECT_SCOPE_WARNING_20261102.md)：按项目范围与下级仓库判断创建页提示，保留既有仓库和任务数据。

## 历史与兼容资料

[交付跟进](FOLLOWUP_DELIVERY_20261023.md)、各 `*DELIVERY*`、`*ACCEPTANCE*`、`*PRODUCTION*`、旧方案和发行文档保留当时的事实与证据，不是现行部署或新接入教程。[服务器历史快照](SERVER_OPERATIONS_HISTORY.md)保留从现行指南移出的操作记录。本机容器取代远端 Linux 宿主后，[ADR-013 容器部署](CONTAINERIZED_DEPLOYMENT.md)、[ADR-013 正式部署](ADR013_PRODUCTION_DEPLOYMENT.md)与 [CLI HTTPS 信任](CLI_TLS_TRUST_20261027.md)只作为远端历史保留，其中的 SSH 别名、systemd、宿主 nginx 和服务器 CA 路径不再有效；本轮残留清理见[记录](REMOTE_ENVIRONMENT_RESIDUE_CLEANUP_20261028.md)。旧 ADR 说明其 profile 的原合同；对被新实现替代且不兼容的旧实现及对应数据，ADR-028 取消无条件兼容和保留要求。历史验收材料记录当时事实，不代表相关业务数据仍然存在。

新增或修改文档时，把长期规则放在其权威文档，未完成工作放在 TODO，按轮次记录实际结果并说明时间和范围；避免在多个入口复制易过期的部署状态。
