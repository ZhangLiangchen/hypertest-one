---
name: hypertest-local-task-onboarding
description: "为 HyperTest One 接入本地会话任务：安装或升级 Local 客户端、排查 Codex Hooks 与真实父会话来源、绑定指定的已有 Local Task，并可靠同步计划、用例和原始报告。用于本地模式首次接入及恢复；不用于 Cloud 任务、SUT 执行或平台部署。"
---

# HyperTest 本地任务接入

将用户指定的 Local Task 接入当前真实父会话，完成管理资产同步与完整读回。此 Skill 可独立安装，也随新版 Local 包交付；它不替换 `hypertest-interactive`。旧 `local-v0.1.0` 资产保持不变，安装指南本身不安装 runtime 或新增授权。

## 先固定目标和范围

- 从用户提供的链接或已授权平台读回确认 **Project、Local Task ID、intended actor、当前版本、真实父会话和 workspace**。目录名或测试主题不能替代 Project 映射。
- 用户已给 Task ID 时始终复用，不再创建 Task。没有 ID 时先取得或请求 Operator 在平台创建 Local Task；Agent 不以旧自动创建协议绕过绑定，也不自行获取 Operator key 或签发 grant。
- 复用有效、仅含所需 `task:sync` 授权的私有 profile、token 文件和 CA；保留原 state、journal、未决 key、配置及其他 Hooks。授权或目标不明时保留私有草稿，并明确缺口。
- 只由选定的真实主会话串行写平台；子代理只回交产物。管理同步不授权 SUT 测试、交易、资源创建、部署或模型启动；执行环境及执行权限另按用户要求处理。

## 按可核验状态推进

1. **恢复优先。** 读取已有安装收据及原账本。遇到可能已发送、`SENT`、`UNKNOWN` 或失答，先按原操作和原 key 查询；不越过未决写继续绑定或同步。
2. **安装与能力。** 已有安装且能力满足时直接复用；确需首次安装或升级时，按 [安装与宿主核验](references/setup.md) 选择匹配服务端、宿主及 OS 的固定版本。`doctor`、工具列表成功只证明配置或能力；缺少新绑定能力不能退回自动建任务。
3. **实际 Hook 源。** 用宿主的标准 Hooks 检视界面或受支持的只读 `hooks/list`，核对 `sourcePath`、启用、信任及诊断。保全其他 Hook 组。需要用户信任或生命周期操作时，只指出**已选工作区、正确聊天与具体操作**，按 [故障恢复](references/troubleshooting.md) 处理。
4. **真实来源。** 核验真实 `SessionStart` 建立的 root 与 Project/provider/当前父 session/workspace/policy/artifact directory 一致。新 BIND 及手动绑定任务的显式新 SYNC 还需要受支持宿主每调用提供的 caller context；工具 arguments、CLI 参数或知道父 ID 均不能代替。当前仓库支持边界见 setup，不凭旧三宿主证明扩大。
5. **读现有 Task。** 完整读取当前 Task 与绑定，核对 owner、来源及版本。已绑定到本会话则恢复原目标，**不再 BIND**；绑定到其他会话时，由该原 writer 接续或报告来源不匹配，不改绑、不借用其 ID。
6. **先 BIND、后 SYNC。** 对 UNBOUND 目标按 [写入与读回契约](references/sync-contract.md) 冻结一次 BIND。接受且完整读回后，承接最新 Task 的全部可写标量，合并本次真实产物，再冻结一次 SYNC。显式 MCP 和 Hook 使用同一协调器、目标与账本，不能形成两个 writer。
7. **完整验证。** 固定接受版本读完所有页，逐字段及 Markdown 原文比较，再观察 current head。将接受版内容投影到 root 返回的正式产物槽，避免旧计划或不同 report key 使后续 Hook 覆盖或重复提交。

用户已授权本地接入时，继续完成该范围内的常规配置、绑定及同步，不额外要求重复批准；宿主要求的标准 Hook 信任由用户审阅，已 trusted 的项不再次索要信任。

## 写入和恢复的不变量

- 每个真实新意图在发送前持久保存完整 payload、稳定 key、`expected_version` 与来源；先记可能已发送，再让原生工具调用一次。冻结后不改正文、key 或版本来“重试”。
- BIND 原 key 用 `hypertest_get_task_binding`；SYNC 原 key 用 `hypertest_get_task`。`UNKNOWN`、超时、失答及 `NOT_FOUND` 只允许原 key GET，不重 POST、不换 key、不另建任务。
- `hypertest_sync_task` **不是 PATCH**。完整承接 `title/objective/status/plan_markdown/reported_result`，按稳定 key 合并 cases/reports，保留已有 FAIL、UNKNOWN、修订及来源。未执行的新用例用 NOT_RUN；传输结果不能重写测试结果。
- 正式文件只写入已批准 policy 的槽和真实 root 的 `artifact_directory`。不扫描聊天、隐藏推理、工具原始负载或认证目录；不手造 source 哈希目录、SessionStart、caller metadata 或信任状态。
- 不关闭证书校验，不修改旧发行 tag/digest，不删除 journal 来消除阻塞。配置保全冲突或身份不匹配时保留原件，停止依赖该条件的写入。

## 收尾输出

给出原 Task URL、绑定来源、接受及读回版本、用例/报告数量、内容比较和 current head 观察、未决 key 与剩余工作。分别说明：安装是否完成、真实宿主接入是否观察到、绑定/同步是否完成、SUT 是否执行及其真实结果。不要用 Hook 信任、工具可见、上传或 Stop 推导 PASS/COMPLETED，也不把一条真实路径扩大成所有 Hook 的 E2E 验收。

接口、所有权与版本规则以 [ADR-024](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md)、[TMP §45.4](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/protocol/TEST_MISSION_PROTOCOL.md#454-统一创建与local显式绑定adr-024) 及[领域 §50.5](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#505-预创建local任务与一次性来源绑定adr-024)为准；版本变化时重新核验实际能力。
