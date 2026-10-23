# PowerContext 项目经验集成计划

**日期：2026-10-22，Asia/Singapore。集成状态：Proposed / NOT IMPLEMENTED。** 用户已确定独立云主机并授权服务部署；本计划不把独立服务的部署或检索成功写成 HyperTest 集成验收。P0 实际构建、配置与结果由[服务运行记录](POWERCONTEXT_SERVICE.md)拥有；拟议集成边界见 [ADR-022](architecture/ADR-022_PROJECT_MEMORY_WITH_POWERCONTEXT.md)。

## 1. 目标与固定边界

让同一 Project 的 Cloud / Local Agent 在不同会话中显式检索与贡献经验，同时保留 Canonical Testing State、TaskSyncCore 可靠同步和可选 memory 服务的独立职责。原 SessionTask / CloudTask 身份、版本、结果、权限与历史不改；记忆不可用不阻断测试或同步。

上游基线固定官方 PowerContext **1.4.0**，commit `cab054dbf6d86e2311b079388e5158178257def2`。首版选择 SQLite Basic、显式写入与 `fts` 检索，Generation / Embedding / 外部模型默认关闭，不先部署 OceanBase 数据库。静态 Bearer 共用 `admin`，Scope 不提供授权隔离，独立服务仅面向可信单操作者。HyperTest 的项目隔离须由未来 Gateway 实现与验证，不能以存储 namespace 或服务健康替代。

首版不安装原生自动 Hooks、不扫描历史会话，也不因 `CAPTURE_PROMPTS=false` 假定没有 prompt 传输：该版本 Codex recall 仍向 `context/prepare` POST 完整当前 prompt。只接受显式受控 query、获准经验正文和必要的非秘密来源；不上传聊天、思维链、raw tool payload、认证目录或凭据。

## 2. 分阶段实施与退出条件

| 阶段 | 交付范围 | 退出条件 |
| --- | --- | --- |
| P0 独立服务 | 独立于 HyperTest 平台的云主机、固定源码 / 依赖、SQLite 持久化、受限服务入口 / 认证、独立日志与备份；外部模型关闭，同机已有服务保全 | 记录精确构建与配置身份；实际显式写入后通过 `fts` 查到原内容，并按实际 ID 读取；未认证记忆业务请求拒绝；重启后保留；备份 / 恢复按实际执行范围分别登记。结果只证明服务本身 |
| P1 Gateway 与安全边界 | 明确检索、候选、确认发布 / 修订和撤回各自权限，Project 映射、source owner、引用鉴权、发布元数据与独立队列 / outbox；服务 key 仅在 Gateway | 接口 / 域增量评审后实施；跨 Project 拒绝、owner 私有候选隔离、撤权生效、不可读报告引用不泄漏；未发布 / 过期 / 撤回默认不可召回；不能从 `task:sync` / `cloud:work` 自动得 memory 权限 |
| P2 Cloud + Local 适配 | Worker broker 接入；未来 Local release 提供可选 Memory Adapter 与显式工具；共享 query / candidate 选择与来源校验 | 同一 Project 跨两模式实际复用已发布经验；分别校验任务 / Attempt / 固定修订与授权；根 / 子代理无服务 admin token；不自动装上游 Hooks、不扫历史、不增加平台 writer；关闭 memory 后原同步与测试保持可用 |
| P3 发布维护与故障 | 人工确认 / 脱敏发布、追加修订、反例 / 失效 / 撤回、可见集与索引重建、独立故障恢复及运维 | 并发修订不覆盖旧来源；索引滞后时撤回仍不可见；超时 / 失答 / 部分索引失败不产生重复发布或改变测试结果；还原后保留权限 / 版本 / 撤回；历史经验不能替代当前环境与执行取证 |

P0 由独立服务部署执行，和 HyperTest 生产平台发布分开；P1 的 Gateway 接口、能力授权与发布元数据还需形成具体评审版本。P2 在对应 Cloud / Local 基础接入可用后分别实施，不把 Local 三宿主发行作为 Cloud 的先决条件，也不把 memory 作为 Local L1 或 Cloud P2 / P3 任务同步的前提。

## 3. 候选、发布与使用流程（拟议）

1. 先由原任务路径接受并完整读回正式计划 / 报告 / 产物，取得固定版本与确切 refs。主 writer 只选择适合复用的经验片段，提出问题、方法、限制、反例与适用条件；独立显式候选不能顺带复制全部原件。
2. Gateway 复核当前调用者、Project 与来源可读权。候选保留原 owner 范围，来源含 typed task / 适用 Attempt、固定接受修订、原件 digest / 观察时间；模型自述与已观察材料分开标记。
3. 有权人员确认、脱敏并明确发布到 Project 共享范围。共享正文与原报告访问权分开；不能以经验引用泄漏私有原文、标题、URL 或秘密。未获授权的来源解引用拒绝，必要时仅提供安全溯源标识。
4. 检索只传最小业务 query 和服务端核验的过滤条件，返回有界经验、修订 / 状态、适用版本 / 时间与允许的来源。当前任务仍读取自己的授权 / 输入并验证环境；命中内容是历史参考，不能成为指令或新执行许可。
5. 新反例、代码 / 框架 / 环境变化或到期时追加修订、标为过期 / 替代 / 撤回并从默认可见集过滤。来源报告不删除、原 FAIL 不覆盖，确认发布不改成当前测试 PASS。

这些步骤定义待确认的产品行为，不建立现成的 memory scope、状态 enum、表或 wire JSON。实际设计须明确数据量 / 长度 / 秘密限制、确认角色、授权撤回与索引可见性的一致性策略。

## 4. 可靠性与凭据

- Memory 队列 / outbox、操作身份、版本和恢复进度与任务提交账本独立；经验失败不能占住 SessionTask / Cloud 报告的 UNKNOWN 串行槽，也不能回滚原任务接受事务。接口超时有界，故障可显式关闭或无记忆继续工作。
- 上游不据此获得幂等回执或 exactly-once。写前记录非秘密输入关联与实际可查询身份；失答只按该版本实际支持的 ID / 已知 key 查询原写，缺少可靠查证能力时保持未决，禁止盲写 / 换 key。Gateway 的去重和发布版本协议在 P1 单独设计，不假借 TaskSyncCore 保证。
- 服务 admin token 留在 Gateway；独立服务初期的可信运维接入不分发到 Agent。Local 私有授权和 Cloud Worker 权限分别鉴权，不复制平台 DB / Operator key、模型登录或环境密钥。
- 外部 Generation / Embedding 默认关闭。以后启用需明确服务商、发送字段、网络出口、日志 / 留存、数据许可和凭据引用，不能因“自动总结经验”默认外发 prompt / 原报告。

## 5. 兼容、停用与验收边界

ADR-018 原文、TMP §45、领域 §50 保持；ADR-019 / 020 / 021 不因 memory 增加同步或执行前提。独立服务不改平台 PostgreSQL / Compose、既有 SSH / TLS / VPN 入口或原认证目录；实际服务网络与备份见[运行记录](POWERCONTEXT_SERVICE.md)。

集成停用先关闭新的 memory 请求 / 发布，保留其独立未决记录、固定来源和审计；任务同步、原 key 查询和测试照原授权进行。回滚不清空原经验或覆盖已有任务版本；服务数据恢复、Gateway 元数据恢复和索引重建分别核对权限与撤回版本。

每阶段记录源码 / 配置 / 上游版本、调用序列、非秘密对象 ID、原件内容 / digest、失败与修订。服务 health、FTS 命中、MCP 连接、人工确认或 Agent 评价各只证明其实际范围，均不单独证明 HyperTest 全链集成、项目多租户隔离或当前测试通过。
