---
name: hypertest-local-task-onboarding
description: "为 HyperTest One 接入本地会话任务：安装或升级 Local 客户端、排查 Codex Hooks 与真实父会话来源、绑定已有 Local Task 或加入显式授权的多会话协作，并可靠提交计划、用例和原始报告。用于本地模式首次接入及恢复；不用于 Cloud 任务、SUT 执行或平台部署。"
---

# HyperTest 本地任务接入

安装或升级本机 Local 客户端，或将用户指定的 Local Task 接入当前真实父会话并完成管理资产同步与完整读回。此 Skill 可独立安装，也随新版 Local 包交付；它不替换 `hypertest-interactive`。旧 `local-v0.1.0` 资产保持不变。

用户仅要求安装或升级时，直接按 [安装与宿主核验](references/setup.md) 完成官方 updater 与本地诊断，不要求先提供 Task ID，不创建、绑定任务或启动模型、SUT 测试。用户给出平台生成的单条安装 Prompt 时承接其中的 Project、宿主和通道；已有配置与目录能确定时不再重复询问。

## 先固定目标和范围

- 从用户提供的链接或已授权平台读回确认 **Project、Local Task ID、intended actor、当前版本、真实父会话和 workspace**。目录名或测试主题不能替代 Project 映射。
- 用户已给 Task ID 时始终复用，不再创建 Task。没有 ID 时先取得或请求 Operator 在平台创建 Local Task；Agent 不以旧自动创建协议绕过绑定，也不自行获取 Operator key 或签发 grant。
- 复用有效、仅含所需 `task:sync` 授权的私有 profile、token 文件和 CA；保留原 state、journal、未决 key、配置及其他 Hooks。授权或目标不明时保留私有草稿，并明确缺口。
- 默认单会话任务由已绑定 root 写入。明确启用协作后，多个获授权的独立 root 分别提交自己的贡献，只有当前 PRIMARY 汇总整体状态；原生子代理仍只回交产物。管理同步不授权 SUT 测试、交易、资源创建、部署或模型启动；执行环境及执行权限另按用户要求处理。

## 按可核验状态推进

1. **恢复优先。** 读取已有安装收据及原账本。遇到可能已发送、`SENT`、`UNKNOWN` 或失答，先按原操作和原 key 查询；不越过未决写继续绑定或同步。
2. **安装与能力。** 已有安装且能力满足时直接复用；确需首次安装或升级时，按 [安装与宿主核验](references/setup.md) 选择匹配服务端、宿主及 OS 的固定版本。`doctor`、工具列表成功只证明配置或能力；缺少新绑定能力不能退回自动建任务。
3. **实际 Hook 源。** 用宿主的标准 Hooks 检视界面或受支持的只读 `hooks/list`，核对 `sourcePath`、启用、信任及诊断。保全其他 Hook 组。需要用户信任或生命周期操作时，只指出**已选工作区、正确聊天与具体操作**，按 [故障恢复](references/troubleshooting.md) 处理。
4. **真实来源。** 核验真实 `SessionStart` 建立的 root 与 Project/provider/当前父 session/workspace/policy/artifact directory 一致。新 BIND、手动绑定任务的显式新 SYNC，以及 JOIN/CONTRIBUTE/PUBLISH 都需要受支持宿主每调用提供的 caller context；工具 arguments、CLI 参数或知道父 ID 均不能代替。当前仓库支持边界见 setup，不凭旧三宿主证明扩大。
5. **读现有 Task。** 完整读取当前 Task 与绑定，核对 owner、来源及版本。已绑定到本会话则恢复原目标，**不再 BIND**。绑定到其他会话的默认单会话 Task 保持来源阻塞；显式启用协作且本真实 root 已获精确授权时，改用协作 GET/JOIN，保留原绑定来源，不冒用或重绑。
6. **选择正确写入合同。** 对 UNBOUND 目标按 [写入与读回契约](references/sync-contract.md) 冻结一次 BIND。单会话接受绑定后承接最新 Task 的全部标量再 SYNC。协作 Task 使用 JOIN、自己的 CONTRIBUTE；整体发布由当前 PRIMARY 显式 PUBLISH，不再调用 full sync。每个 root 的 MCP 和 Hook 共用其协调器、目标与账本；不同 root 不共享 journal。
7. **完整验证。** 固定接受版本读完所有页，逐字段及 Markdown 原文比较，再观察 current head。将接受版内容投影到 root 返回的正式产物槽，避免旧计划或不同 report key 使后续 Hook 覆盖或重复提交。

用户已授权本地接入时，继续完成该范围内的常规配置、绑定及同步，不额外要求重复批准；宿主要求的标准 Hook 信任由用户审阅，已 trusted 的项不再次索要信任。

## 写入和恢复的不变量

- 每个真实新意图在发送前持久保存完整 payload、稳定 key、`expected_version` 与来源；先记可能已发送，再让原生工具调用一次。冻结后不改正文、key 或版本来“重试”。
- BIND 原 key 用 `hypertest_get_task_binding`；SYNC 原 key 用 `hypertest_get_task`；JOIN/CONTRIBUTE/PUBLISH 原 key 用 `hypertest_get_task_collaboration`，保留原 Task/provider/session。`UNKNOWN`、超时、失答及 `NOT_FOUND` 只允许原 key GET，不重 POST、不换 key、不另建任务或换会话重发。
- `hypertest_sync_task` **不是 PATCH**。完整承接 `title/objective/status/plan_markdown/reported_result`，按稳定 key 合并 cases/reports，保留已有 FAIL、UNKNOWN、修订及来源。未执行的新用例用 NOT_RUN；传输结果不能重写测试结果。
- 协作贡献按 participant/kind/stable_key 保留独立修订；同名 key 不属于同一共享资产。Hook 的正式文件只成为本 root 的贡献，整体状态、结果和采纳映射必须由当前 PRIMARY 显式发布。Operator 授权与交接不由 Agent 代办；工具可见也不代表旧公开包已支持新合同。
- 正式文件只写入已批准 policy 的槽和真实 root 的 `artifact_directory`。不扫描聊天、隐藏推理、工具原始负载或认证目录；不手造 source 哈希目录、SessionStart、caller metadata 或信任状态。
- 不关闭证书校验，不修改旧发行 tag/digest，不删除 journal 来消除阻塞。配置保全冲突或身份不匹配时保留原件，停止依赖该条件的写入。

## 收尾输出

给出原 Task URL、绑定来源、接受及读回版本、用例/报告数量、内容比较和 current head 观察、未决 key 与剩余工作。分别说明：安装是否完成、真实宿主接入是否观察到、绑定/同步是否完成、SUT 是否执行及其真实结果。不要用 Hook 信任、工具可见、上传或 Stop 推导 PASS/COMPLETED，也不把一条真实路径扩大成所有 Hook 的 E2E 验收。

接口、所有权与版本规则以 [ADR-024](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md)、[ADR-026](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/architecture/ADR-026_MULTI_SESSION_TASK_COLLABORATION.md)、[TMP §45](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/protocol/TEST_MISSION_PROTOCOL.md#45-codex-会话任务管理同步adr-018当前阶段) 及[领域 §50](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#50-sessiontask-管理数据与历史adr-018当前阶段)为准；版本变化时重新核验实际能力。
