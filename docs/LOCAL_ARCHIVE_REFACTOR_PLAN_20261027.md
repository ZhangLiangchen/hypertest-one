# Local 后置显式归档改造与开发计划

更新：2026-10-27（Asia/Singapore）。**方向已确定，产品开发未开始。** 本轮只交付方案文档；不表示已移除 Hooks/MCP、部署新 API 或发布新 CLI。

架构决定见 [ADR-027：显式 Local 测试产物归档](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)。剩余工作统一由[当前 TODO](TODO.md)与[本轮跟进](FOLLOWUP_DELIVERY_20261023.md)跟踪；此前 `local-v0.1.1` 正式发行及宿主验收状态保持原义。

## 1. 改造目标与依据

当前 Local 接入把测试过程与平台同步耦合：安装器为工具结束、回合结束等事件注册 Hook；已有批准文件时，即使内容不变，也可能经历文件读取、校验、协调器锁及在线 baseline 读取。DeepSeek 桥还会等待 Hook 返回。源码依据见 `src/hypertest/local_sync/installer.py`、`hooks.py`、`sources.py`、`coordinator.py` 与 `deepseek_root_bridge.mjs`。

这些路径说明存在额外工作和等待来源，但本轮没有性能测量，不量化耗时或收益。MCP 同样能够上传与写入；问题在于过程耦合、自动触发及接入复杂度，不能归因于“MCP 无法归档”或声称 HTTP 天然更快。

目标是让本地 Agent 使用项目已有工具完成测试，测试过程无需平台授权、Task ID、网络连接、Hooks、MCP 或常驻 HyperTest 进程。用户准备归档时，才提供目标并显式调用 Skill，由短命 CLI 完成可靠传输。

## 2. 新的使用流程

1. 用户与本地 Agent 自行完成需求分析、测试设计、执行与报告；正式产物保存在用户选择的位置。
2. 测试结束后，用户在 PC Web 的既有 Project 下创建归档 Task 及至少一个 Subtask，取得两个明确目标 ID；简单任务可由同一页面连贯创建默认子任务。
3. Web 复制包含 Project/Task/Subtask ID 的 `hypertest-archive` 显式 Skill 调用指令，例如：“当前需求测试完成，请调用 hypertest-archive，将指定产物上传归档到任务……、子任务……”。指令不含凭据。
4. 用户在需要归档的会话显式调用该 Skill。Skill 整理计划、结构化用例与原始报告，生成待提交 manifest，调用 `hypertest archive`。
5. CLI 校验目标与权限、冻结完整请求、提交并完整读回固定接受版本，输出归档链接、Submission ID 和结果，然后退出。
6. 失答或 UNKNOWN 时保存原请求及账本；用户再次调用恢复命令，只按原 key 查询，不重新上传或创建替代任务。

Task 可以由用户提前创建，但不是测试前置条件。关键词是表达用户上传意图的自然语言示例，不是监听规则、密码或授权凭证；CLI 不提供关键词参数、不扫描聊天、不后台监听。Skill 不依据 Agent 自称完成、Stop 或工具活动自动触发。

拟议的 Codex 显式调用示例（其他宿主采用其已支持的 Skill 选择方式）：

```text
$hypertest-archive
当前需求测试完成，请将 ./test-results 中的本轮正式产物上传并归档至 HyperTest One。
任务ID：TASK_UUID
子任务ID：SUBTASK_UUID
```

## 3. 新领域与权限边界

新增 `local-artifact-archive/v1alpha1`，以及归档 Task、Subtask、Submission、AssetRevision、Publication；具体字段与 API 由 ADR-027、领域§56和 TMP§51 的目标合同拥有。

- 归档 Task/Subtask 属于 Project；Subtask 是用户选择的业务归档单元，不是原生子代理或子会话身份。
- Submission 固定上传者、目标、完整请求、原 key、接受版本及回执；资产按稳定业务 key 保留不可变修订，禁止覆盖失败报告或旧原件。
- uploader 由当前授权识别，不要求 native SessionStart、父会话绑定、MCP caller context 或指定宿主版本。可选 provider/session/source 仅为声明的来源 metadata，不提升为独立身份或执行证明。
- 归档权限独立签发和校验，不从 `task:sync`、`cloud:work`、Project 可见性或“知道任务 ID”自动获得；归档授权不赋予 Cloud 执行、Memory 或 Operator 权限。
- CLI 内部读取私有配置/系统凭据引用；Skill、命令参数、manifest、日志及回执不包含 token。首次授权需提供明确受控入口，不能让安装器或 Agent 自行申请 Operator key、签发 grant。
- 任务进度、测试 reported result、传输状态分别保存。上传成功不自动推导测试 PASS、整体 COMPLETED、VERIFIED Evidence 或 RELEASE_READY。
- 新旧任务保留类型化身份；不把 SessionTask/CloudTask 改成归档 Task，不迁移旧 session ID 来冒充新 uploader，不建立跨模式通用 Task 根表。

子任务上传使用各自版本，不递增任务管理版本；整体汇总由 Web 显式引用精确子任务版本向量，之后的新上传不改旧汇总。首片 Task owner 与 Subtask uploader 为同一获准 integration actor，Web 创建者另记；逐资产保留来源声明，不将一批多会话文件统归当前上传会话。

## 4. Skill 与 CLI 的首版分工

`hypertest-archive` 只在用户显式调用时编排：确认本次目标和文件范围、整理结构化资产、生成 manifest、调用 CLI、解释归档结果。Skill 是指令，不持有凭据、不承担 HTTP 重试和账本事务；仅有结束语或模型判断不构成新上传授权。

统一 `hypertest` 入口首版范围如下，命令形式为待实现设计，不是当前可用命令：

| 命令 | 首版职责 |
| --- | --- |
| `hypertest profile add/show` | 保存/检查平台地址、Project 及私有授权引用；不显示秘密，不自动扩权 |
| `hypertest doctor` | 检查 CLI、配置、TLS、当前归档能力与授权；不创建业务记录、启动 daemon 或执行测试 |
| `hypertest archive --task-id … --subtask-id … --manifest …` | 校验目标，读取显式文件，冻结、提交和固定版本完整读回 |
| `hypertest status --request-id …` | 查看私有请求账本和接受/读回状态；需要联网时明确按原请求读取 |
| `hypertest reconcile --request-id …` | 恢复原请求的查询与固定版本读回；SENT/UNKNOWN/NOT_FOUND 不重 POST |
| `hypertest skill install --directory …` | 向用户选定技能目录安装/升级 `hypertest-archive`，按收据保留自定义内容 |

提供 `--json` 稳定输出，供 Skill 读取 `status/code/request_id/submission_id/accepted_version/readback_complete/task_url` 等非秘密信息；人类输出保持简洁。退出码按 TMP§51：0成功、2本地输入错误、3明确拒绝、4未决/读回未完、5配置/能力缺口，具体拒绝码区分授权和版本冲突。`archive` 只有有效回执及完整内容读回后才报归档成功；`--dry-run` 返回 PREVIEW，不伪装已归档。

manifest 明确 profile、Project/Task/Subtask、资产稳定 key、类型、原路径及声明的测试结果；CLI 读取固定基线、计算实际摘要并冻结 expected_subtask_version。请求明确 upsert 所选完整资产，省略资产不删除。首片支持 UTF-8 计划/原始文本报告及结构化用例，按 TMP§51 的2MiB总量及单项/条数上限接受；截图、视频和压缩包二进制存储留待独立扩展，未支持格式明确拒绝，不静默丢弃或转换原件。

只读取 manifest 指定的正式文件，不扫描工作区、聊天、推理、工具原始负载或认证目录。缺少用例、报告或执行材料时如实报告；不得为凑齐归档捏造内容。源文件变化后需构成新的明确提交意图，不修改已冻结请求。

## 5. 可靠传输与轻量发行

CLI 使用短命进程直接通过 HTTPS 调用独立归档 API；复用 `ApiClient` 的 TLS/秘密读取思路、`TaskSyncCore`、`JournalLedger`、`SnapshotStore` 与固定版本分页读回，新增 ArchiveAdapter。抽取共享库时保留旧 Cloud/Memory 消费者边界，不能复用原 SessionTask 身份校验来伪装归档。

每次提交先持久保存完整冻结请求、目标、稳定 key 和 expected version，再记录可能发送；原 key 查重先于版本冲突判断。同 key 异输入拒绝。超时、SENT、UNKNOWN、失答及 NOT_FOUND 只 GET 原 key；有效 ACK 后逐字段及原件比较固定接受版本。并发、撤权及接受后删除等路径保持历史和最小授权边界。

新包采用 `cli-vSEMVER` 独立版本、固定来源和摘要，包含轻量 CLI、必要 HTTP/校验依赖及归档 Skill；不安装 MCP SDK、宿主 MCP 配置、Hook、daemon、Cloud SDK 或模型工具。支持 OS/Python 目标按实际发行能力声明，不为无 native caller 依赖的归档引入三宿主生命周期矩阵。

## 6. 实际源码处置与升级范围

下表为已存在源码的改造清单，**不是已删除声明**；实施时逐项确认共享消费者后处理。

| 现有位置 | 计划处置 |
| --- | --- |
| `src/hypertest/local_sync/{__main__,hooks,hosts,sources,deepseek_bridge}.py`、`deepseek_root_bridge.mjs` | 退出新 Local 默认入口，移除自动观察/上传及宿主桥接；旧恢复需要的读取逻辑独立保留 |
| `src/hypertest/local_sync/{coordinator,adapter,binding,collaboration,manifest}.py` | 新归档不依赖 root/BIND/JOIN/PRIMARY；保留旧快照/回执解析及原 key 只读恢复，抽取可共享校验能力 |
| `src/hypertest/interactive_client/{mcp_server,ipc,__main__,service}.py` | 新包不加载 MCP/UDS/daemon 路径；其他 profile 或 Memory 仍需的实现不连带删除 |
| `src/hypertest/interactive_client/{api_client,config,journal,security}.py`、`src/hypertest/sync_core/` | 复用/抽取传输、安全读取及可靠交付库，拆开旧 profile、路由白名单与归档 namespace |
| `src/hypertest/api/{task_routes,task_schemas,task_collaboration_routes}.py`、`src/hypertest/application/{session_tasks,task_binding,task_collaboration}.py`、`src/hypertest/domain/session_tasks.py` | 退休旧 Local 新写，保留授权历史/固定版本/原 key 查询；新增独立归档模块及非破坏性迁移 |
| `skills/hypertest-local-task-onboarding/`、`src/hypertest/local_sync/{installer,skills}.py` | 新接入改为归档 Skill 与独立安装器；旧指南明确历史和恢复范围，不继续引导新绑定/同步 |
| `pyproject.toml`、`scripts/{update-local,install-local-release,build-local-release,prepare-local-dependencies,plan-local-release,local-release-commands,freeze-local-release-source}.py` | 新增统一 CLI/轻量发行，调整依赖与受管升级；旧 tag、包、manifest 和摘要保持不可变 |
| `scripts/local-release-{dependencies,targets}.json`、`.github/workflows/local-release.yml` | 新发行目标/依赖闭包独立记录，发行构建按实际要求执行；不恢复日常 push/PR 自动 CI |
| `web/app/projects/[projectId]/{local-mode-guide,session-tasks}.tsx`、`web/app/projects/[projectId]/tasks/new/task-create-form.tsx`、`web/app/tasks/[taskId]/page.tsx`、`web/app/tasks/local-task-{binding,collaboration}.tsx` | 新归档创建/详情取代默认接入提示，历史会话任务详情保留类型与只读恢复说明 |
| `web/lib/{local-mode-install,local-task-binding,local-collaboration,types}.ts` 及相关 BFF/测试 | 更新类型、独立权限、复制指令与安装入口；不得把旧 task ID 路由到新归档 API |

受管升级先读取旧安装收据，仅精确移除本产品拥有且未被用户修改的 MCP server、Hook group、DeepSeek 插件行及相关自有配置块。其他 MCP/Hook、宿主设置和自定义 Skill 保留；遇到所有权不明或内容改动则报告冲突并保留原件，不全局替换配置或删除整个文件。仅处理收据可证明属于本产品的 transport；不按进程名批量杀进程。

保留 token/CA、授权引用、旧 state、完整快照、journal、未决 key、源产物和旧安装收据；新归档授权与账本不静默继承或合并。旧元数据待查询不等于要再上传，不能把未决内容批量重投到新任务。旧发行 `mcp-v*`、`local-v*` 与历史验收不重标；不以升级删除用户历史或修改原已接受报告。

## 7. 旧协议退休与 PC Web

新归档可用后，默认 Local 产品流程统一走显式归档；旧 MCP/Hooks Local 新建、BIND、SYNC、JOIN、CONTRIBUTE、PUBLISH 等新写逐项明确退休。服务端在原 key 对账/已接受请求识别之后拒绝新的旧协议写意图，返回可操作的退休错误；不得要求未知旧请求换 key 重试或用新 API 覆盖。

保留获授权的旧 Task/报告/修订、固定版本、原 CREATE/BIND/SYNC/协作 receipt 的只读查询与恢复入口。旧 PENDING 若无法证明从未发送，保持未决并按原 key 查询；能明确证明未发送的旧意图保留为不可新发，不以“恢复”名义推进旧 POST。迁移不补造回执、不清 UNKNOWN、不将历史 SessionTask 自动转成归档任务。服务端退休与客户端升级需协调，且不影响独立 Cloud、Memory 或 legacy 执行域。

PC 宽屏 Web 新增归档 Task/Subtask 创建与类型化列表、详情、资产修订及 Submission 状态；同 Project 可分别查看新归档、旧会话历史和 Cloud。新任务页复制显式 Skill 指令，包含准确目标及可选安装指引；授权缺失显示具体配置缺口，复制内容不携带 token。去掉新流程的宿主选择、会话绑定、Hook 信任和协作 writer 提示；保留原历史解释。中英文、键盘、焦点和可读性继续覆盖，不建设移动端/竖屏适配。

## 8. 分阶段执行清单

| 阶段 | 可执行任务与产出 | 最小相关检查 |
| --- | --- | --- |
| A：合同与拆分 | [x] 本轮确定 ADR-027、四份基础文档目标增补及发行命名；[ ] 实施时落实 typed schema、数据库约束与退休错误码 | 文档差异、引用和新旧合同一致性 |
| B：服务端闭环 | [ ] 新增归档模型/迁移、目标创建、授权、提交/修订、回执及固定版本读取；保留旧历史 | 专用 test DB 验证归属/撤权/拒绝路径、并发版本、同 key 冲突、旧历史保全与迁移 |
| C：CLI 与 Skill | [ ] 实现六类首版命令、manifest、冻结账本、ArchiveAdapter、JSON/退出码；编写 `hypertest-archive` | 本地合成文件/HTTP fixture 验证一次提交、失答/重启原 key 查询、固定读回及敏感字段不外泄 |
| D：PC Web | [ ] 创建 Task/Subtask、复制指令、详情/修订/Submission 展示及独立 BFF 权限 | 定向组件/契约检查；需要时类型检查/构建；PC 中英文与关键键盘路径 |
| E：升级与退休 | [ ] 轻量独立包、精确清理自有配置、保留旧原件；接入旧协议只读恢复并关闭新写 | 合成配置检验其他配置保留、修改冲突、无 MCP/daemon 安装、旧 UNKNOWN 不重 POST |
| F：交付 | [ ] 推送固定 Git，按变更部署 API/Web/必要迁移；独立构建发布 CLI；记录剩余用户验收 | 仅相关服务健康与一条不触发测试的关键路径；发行安装/命令冒烟按真实目标记录 |

实现时优先复用现有干净 checkout、依赖和专用 test DB。只有本轮授权隔离、凭据、幂等/UNKNOWN、版本、迁移及历史保全涉及的关键行为与拒绝路径保留必要自测；不追加全量回归、宿主矩阵、重复环境或额外验收体系。测试 fixtures 不写入业务库，不启动真实模型或 SUT。

## 9. 交付状态与完成判定

| 维度 | 本轮状态 | 后续记录要求 |
| --- | --- | --- |
| 方案 | 方向已确定 | 本文与 ADR-027 说明取舍、边界及执行顺序 |
| 实现 | 开发未开始 | 按阶段记录代码、迁移和相关自动回归；未运行/跳过/失败如实记录 |
| 部署 | 未部署 | 单列固定完整 Git SHA、schema、受影响镜像及最小健康检查 |
| CLI/Skill 发行 | 未发布 | 单列版本、目标、摘要、依赖与安装升级结果；不覆盖旧资产 |
| USER_OWNED | 未执行 | 用户完成真实归档体验与功能验收；实现回归、安装成功和健康检查不能替代 |

首版完成意味着：用户无需在测试期间接入 HyperTest，结束后能从 PC Web 选择任务/子任务，显式调用 Skill，经按需 CLI 可靠归档并查看保真的产物与修订；旧记录和未决请求仍可按原权限只读恢复。文档完成不代表这些能力已经实现。
