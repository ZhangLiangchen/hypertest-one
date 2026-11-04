# HyperTest One 当前待办

本表只列尚未完成的开发、操作和用户验收。各轮实现、部署和验证事实保留在[历史交付记录](FOLLOWUP_DELIVERY_20261023.md)；日期和提交不代表服务器此刻的运行状态，操作前应核实。新 Local 接入以 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 和 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)为准。

## 用户操作与验收

- Cloud 一键开始：自动准备后下发、折叠代码版本和任务输入旧字段清理已部署；真实页面操作与业务功能由用户验收。指定旧任务已按原解析身份关闭失败准备，按用户确认使用框架 master，经新流程进入 RUNNING，实际 SDK 进程已启动；测试结果尚未回传。见[交付记录](CLOUD_ONE_CLICK_START_DELIVERY_20261103.md)和[指定任务恢复记录](CLOUD_SOURCE_RECOVERY_20261103.md)。
- Local 上传身份清理：本机既有 CLI 的真实根空间及子任务归档和读回已按用户要求验证；其他设备使用体验和任务页面显示待用户验收，见[本轮记录](LOCAL_UPLOADER_RETIREMENT_DELIVERY_20261101.md)。
- Local CLI：真实设备升级到 0.1.2、默认全项目永久授权配对及归档由用户验收；存量授权迁移和交付见[本轮记录](CLI_GLOBAL_AUTHORIZATION_DELIVERY_20261028.md)。未知请求只按原 key 恢复，不重发。TLS 信任按本机 CA 配置，见 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)；2026-10-27 远端 CA 指引仅作历史。
- Web：Local 任务统一页面、归档 Prompt、授权页面、任务导航与性能等的用户功能或体感验收仍待用户执行；自动回归和部署健康检查不等于用户验收。各轮范围见[历史交付](FOLLOWUP_DELIVERY_20261023.md)。
- 复制交互（2026-10-28）：HTTP 授权页的安装/新增项目 Prompt 与任务页归档 Prompt 已改用具传统回退的复制助手，Headless Chrome 点击验证通过；真实浏览器与不同操作系统剪贴板权限的用户验收仍待执行，手动复制 textarea 为兜底。见[本轮记录](CLI_CLIPBOARD_FALLBACK_FIX_DELIVERY_20261028.md)。
- CLI 安装 Prompt 服务器地址修复（2026-10-28）：授权页与绑定命令在本机 WireGuard HTTP Web 下改为使用配置的 CLI HTTPS 地址。外部设备接入已改为经 WireGuard 的 `https://10.66.66.3:18444` 并在 Prompt 中携带公开 CA；外部设备真实复制 Prompt、配对批准与产物推送由用户验收。见[本轮记录](CLI_EXTERNAL_DEVICE_ACCESS_DELIVERY_20261028.md)与[前一轮记录](CLI_PROMPT_CLI_ORIGIN_FIX_DELIVERY_20261028.md)。
- 外部设备严格 X.509 与原配对请求（2026-10-28）：CLI 叶子证书已补 SKI/AKI，Python 3.13+ 严格校验和本机 CLI `doctor` 已验证；原 request `58966389-8daf-44b0-8223-921eed7b1e38` 服务端从未创建（DB 0 行、无 CREATE POST），旧本机记录保持 UNKNOWN 不重放。外部设备需发起新的显式配对并完成真实配对/归档，属用户验收。见[本轮记录](CLI_TLS_AKI_AND_PAIRING_ATTEMPT_20261028.md)。
- 其他 Cloud 场景、P0 恢复与 PowerContext：各自用户功能验收仍待用户执行；本机限定原生测试的网页主流程已见[实际闭环](CLOUD_WEB_LIFECYCLE_ACCEPTANCE_20261103.md)。Memory 项目授权需独立配置，不能由 Local 或 Cloud grant 推定。见[跟进记录](FOLLOWUP_DELIVERY_20261023.md)和[Memory 交付](POWERCONTEXT_INTEGRATION_DELIVERY_20261023.md)。
- Cloud Harness 原生配置：其他插件、项目与远程业务仍分别验收；本机 DeepSeek SDK、固定源码、原生测试、报告回传以及网页创建/下发/查看/复测/删除已按用户要求验证，见[网页闭环记录](CLOUD_WEB_LIFECYCLE_ACCEPTANCE_20261103.md)。ADR-031 容器 profile 为历史路径。
- Cloud 任务输入精简（ADR-038）：项目资源页和预期部署版本退出产品；项目编辑仓库、创建填写任务名称及 MR/PR 地址、单个可选 prompt、框架默认 main 及草稿编辑的用户功能验收待执行；前轮实现和部署见[MR 链接创建交付](CLOUD_MR_INPUT_DELIVERY_20261103.md)，该记录不代表本轮名称输入修正已部署。旧资源页不再安排验收；当前合同见 [ADR-038](architecture/ADR-038_TASK_FOCUSED_CLOUD_INPUTS.md)，旧实现、测试和部署仅见[历史任务管理记录](CLOUD_TASK_MANAGEMENT_DELIVERY_20261030.md)。
- 任务创建清理用户验收：旧 SessionTask 和受管 TestRun 的 API、页面及数据迁移已完成本机容器部署，实际结果见[本轮记录](TASK_CREATION_RETIREMENT_20261028.md)；用户功能验收尚未执行。

## 未完成的开发与条件

- Cloud 既有外部业务动作的复测与原 key 观测仍分别验收；本机无外部写操作的独立 Attempt 网页复测已完成，见[网页闭环](CLOUD_WEB_LIFECYCLE_ACCEPTANCE_20261103.md)。[ADR-033](architecture/ADR-033_CLOUD_ATTEMPT_RETRY_SNAPSHOT.md) 的独立快照、范围/授权确认及未知操作不重放边界继续适用；宿主直接操作不经过旧受控 broker，也不提供强隔离。

- [ADR-032](architecture/ADR-032_LIGHTWEIGHT_HARNESS_WORKER.md) 轻量 Worker 的公司发行和未来项目资源隔离的全容器化另行设计；本机领取恢复与真实结果回传已见本轮交付，不重复列为开发待办。
- 本机 Cloud Worker：独立 Docker Attempt、受控写入和自动观察收尾修复已部署；真实 Docker/SDK 的无兑换项目单测任务与报告闭环已观察，自动 action 观察及收尾另以专用测试库和合成目标验证，尚未在修复版本上以真实写操作复验。原历史任务、动作及报告保持不变；不能将合成结果推定为真实 SUT 测试通过。见[本轮记录](CLOUD_WORKER_FIRST_SLICE_20261029.md)。
- Cloud 框架与受控 HTTPS 只完成首片；真实目标授权、依赖闭包和离线供应、认证或写 API、其他工具链与浏览器等尚未完成。见[受控 HTTPS](CONTROLLED_HTTPS_FOLLOWUP_20261023.md)和[框架冻结](FRAMEWORK_RUNTIME_FOLLOWUP_20261023.md)。
- Cloud 对话与多会话薄 Worker：公开输出和四槽桥接保留；按 [ADR-041](architecture/ADR-041_CLOUD_AS_HARNESS_SHELL.md) 去掉平台阶段/人工审批，普通消息负责原会话连接。指定业务任务的真实回复和继续执行由用户验收，实施/部署见[纠正记录](CLOUD_HARNESS_SHELL_DELIVERY_20261104.md)。旧接管表单不再安排验收。
- SUT CI adapter、一般 SSH 和 Cloud Claude 尚未实现；分别需要明确 provider 与独立权限、受限目标及 host key、云端服务身份和模型预算。见[P2 设计与输入](CLOUD_P2_FOLLOWUP_20261023.md)。
- 平台完整回归 CI 为按需手动执行；日常按改动风险做必要检查。未运行不等于通过，发行标签构建单独保留。

源码、部署与验收分别记录；历史实现或已完成工作不重复排入待办。新开发遵循 [AGENTS.md](../AGENTS.md)，服务器操作遵循[运维指南](SERVER_OPERATIONS.md)。


## 2026-11-04：Cloud 框架项目工作目录

- 实现和宿主部署已完成，见 [交付记录](CLOUD_FRAMEWORK_PROJECT_DELIVERY_20261104.md)。框架原文件直接归档，HyperTest 不另造测试流程。
- USER_OWNED：新 Cloud 任务实际业务验收待用户执行；旧会话跨目录归组尚无原生支持，本轮保留原会话与结果。
