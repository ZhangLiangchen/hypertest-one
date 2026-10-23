# DeepSeek Harness SDK：P0 兼容检查与协议探针

**更新：2026-10-23，Asia/Singapore。范围：官方 SDK 接入前置检查；云端完整流程按独立实施记录验收。**

本入口检查 HyperTest 能否加载固定配对的官方 Harness Python SDK，并通过显式探针观察一次无模型输入的 runtime 初始化、会话工作目录查询和关闭。它不接取 CloudTask、不提交测试任务，也不替代 [ADR-019](architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md) 的六步云端流程或[实施计划](CLOUD_TEST_IMPLEMENTATION_PLAN.md)的 P0 退出条件。

云端 Worker 的执行代码位于 `hypertest.cloud`，默认关闭，尚未更新测试服务器常驻Cloud服务；本文的 `hypertest.deepseek_harness` / `hypertest.deepseek_probe` 只负责兼容检查和隔离协议探针。两者的执行能力、部署和验收分别记录，不能用探针成功认定云端任务已完成。

## 最新任务验收与SSH实施边界

第一阶段严格输出已由新Task完成：source-r23物理执行的 `01a166bd-059c-7107-acc9-0bafe7ceb781`固定v20 COMPLETED / reported PASS，ANALYSIS / DESIGN直接引用同一当前child原件，19资产 / Run1 / 7个RunCase / delegation及5份原件完整核对。source-r24仅修只读验收器对精确repo@SHA、显式raw+diff双原件及JSON成功闭集的有限解析，对同v20实际 **strict PASS / failures=[]**，没有新POST、prompt或模型重跑。source-r23所选201通过、source-r24所选231通过及各自Ruff分别登记；旧v17仍strict NON_PASS，不能用新任务覆盖旧DESIGN偏差。

本Task独立只读重放8项unittest通过（7新+1基线）、树前后相同，raw / diff / 实际文件 / host日志精确关联；SETTLED47 REQUEST_CREDITS=ROOT41+CODEX6 / 224秒，原56预留保留，接受namespace / broker停止字段true。来源仍runtime-reported，重放仍UNVERIFIED / Gate NOT_EVALUATED，未完成全部P0或生产准入。完整身份与摘要见[第一阶段证据](CLOUD_IMPLEMENTATION_STATUS.md#第一阶段严格直接原件验收已完成)。

[ADR-023](architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)固定SSH诊断默认关闭；source30 Worker / source29 helper的r8 canonical专项PASS，source31对同v19固定快照的只读SNAPSHOT_REASSESSMENT实际strict PASS。没有新的current GET / 模型 / SSH / SUT执行，旧source30 NON_PASS保留；故障矩阵与真实staging待验收，尚未更新测试服务器常驻Cloud服务。namespace仍无网络或SSH / signing key，只能连接host UDS；独立host签名、canonical远端ledger及真实terminal / emptycgroup门禁不能由SDK idle / 本地停止 / 模型drain替代。Claude继续占位、CI与通用远端shell不支持。

环境路由硬边界：XBlock staging需SSH / 服务器日志 / 操作的任务仅Local，由用户Mac经Workbench CLI访问；166dev内网自建链仅Local。纯Web / API可选Cloud仍需独立实现并验收HTTPS访问，网络可达不等于当前runtime支持；在本SSH小片之后另行接通。禁止Cloud直连受限环境、转发绕过 / 扩IP许可或复制Mac登录 / 本地环境秘密。通用SSH只在隔离fixture中实施，不改变Project共享双模式；见[执行环境路由](CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

SSH增量回归已单独登记：source25独立DB迁移0024成功、所选32文件685 passed / 1 skipped（50.17秒），Ruff有4个I001失败；source26仅机械排列4份导入，SSH所选三文件91 passed（9.70秒）及broad Ruff通过，两轮不合并、不冒称685项重跑。源码加入独立host SSH代理 / canonical远端账本，动作截止提前原总预算内30秒清理；cutoff可以仅关闭SSH scope而不结束root任务。source29独立transport试点与后续r8 canonical SSH专项已通过；**source31对r8同v19固定快照strict重评PASS，旧source30 NON_PASS保留，取消 / 失联矩阵仍待验收**；详情与source / 日志摘要见[SSH实施记录](CLOUD_IMPLEMENTATION_STATUS.md#ssh实施回归与transport试点)。SDK / 模型 / 工作区六步既有证明不替代该验证。

首次真实transport探针因fixture服务的PrivateTmp遮蔽固定`/var/tmp`配置而失败，sshd未监听；单个已发START保留UNKNOWN / remote_closed=false，NOT_FOUND和票据到期都不作为远端终态。source27仅补固定fixture目录BindPaths，保留PrivateTmp；新独立探针实际通过banner / SSH认证 / helper / action exit0，但unit完成后ControlGroup被systemd清空，helper不能核实原组停止，该操作也保留UNKNOWN。旧identity缺少执行前实际cgroup，不能推导后补或仅凭exit0 / 空组封终态；精确身份行政stop不补造旧terminal。action启动前实际原组记录与严格收口修正经source29独立回归 / 新transport验证，未倒写两次旧操作。canonical同Task的UNKNOWN仍阻止完成 / 结算 / 新Attempt，不将独立新探针当旧操作恢复。

source28保留未测试；source29仅增加host固定版本wrapper选择，以独立closure / catalog保留旧环境。首轮远端111 passed / 1 failed，已由实际元数据确认测试profile遗漏`/tmp` exec、可信客户端准入正确拒绝，Ruff该轮未执行。恢复原可执行私有tmpfs后，同一源码 / 校验独立复验 **112 passed（8.76秒）及broad Ruff通过**；保留首轮失败、不合并计数。新versioned transport实际OBSERVED：两个terminal及host独立原cgroup停止证明，原key去重 / 丢ACK原ID查询 / NOT_FOUND不START / 错host pin四项通过；scope为合成MemoryAuthority、无SDK / 模型 / 正式CloudTask、SUT结果不评估。后续canonical r7使用CloudWorker source26与remote helper source29，需分别记录与独立验收；取消 / 超时 / 后代矩阵仍NOT_RUN。

canonical r7实际执行未通过SSH集成验收：固定v17 **RECOVERY_REQUIRED / NOT_RUN，SSH_RECONCILIATION_REQUIRED**。ROOT25 / CODEX8请求均200 / drained、namespace停止，已有资产 / Run / delegation接受，但唯一SSH操作UNKNOWN、没有远端终态result；72credits / 900秒reservation保持HELD，实际33credits / 208秒不结算。模型drain不替代remote停止，CONTROL_UNAVAILABLE也不单独证明授权失效；原ID查询与明确授权的后续清理保留，不重START或自动新建替代Task。完整身份见上述实施记录，既有r6严格PASS和transport试点通过分别保留。

keyless同image / UID997复现已确认：image缺该服务UID的NSS记录，OpenSSH在连接前exit255；此前UID0独立driver通过不能覆盖此Worker身份差异。source30加入SSH开启时claim前的有效UID / 主GID解析门禁，固定码`SSH_LOCAL_IDENTITY_UNAVAILABLE`、元数据仅布尔，默认SSH关闭不查询NSS、nonroot总profile不变。固定image需包含其合成服务账户，不能改root执行、挂宿主passwd / group或复制个人SSH配置来绕过；旧r7 UNKNOWN / HELD保持。

新NSS-only固定image `sha256:797050fea7d083d90bfac3a4ce1625560b4f088ca9d9e3843ffaf060e08ba93c`已实际生成，UID997 / GID988无网络 / key的pwd解析与ssh-G exit0通过；SSH二进制及既有payload清单保持，旧image / rootfs不改。source30在该image所选32文件实际 **717 passed / 1 skipped / 86条既有warnings（41.37秒）**及broad Ruff通过；Node前置跳过不计通过，冻结Local兼容payload不等于当前三宿主全链重验。上述keyless / 回归与后续真实Task分别登记。

r8 Task `01a16762-5fc8-7207-842a-286dd9ede3e0` / Attempt `01a16764-b2bc-703a-8fc5-d4586fd267ec`固定v19 **COMPLETED / reported PASS**，26资产 / 5原件 / 19 RunCases。Worker source30与helper source29分开固定；ROOT30 / CODEX5 host观察closed / drained、inflight0、namespace停止，预算SETTLED35 REQUEST_CREDITS / 238秒，保留72credits / 900秒原预留。canonical SSH专项实际 **PASS / failures=[]**，assessment SHA256 `7477844a7ab3ea13727fd8f66e94696c48ba1d7aab702bde082830618514fd99`，含原操作 / terminal / 原cgroup与STOP / 精确固定诊断输出核对，仍不证明真实SUT部署或完整故障矩阵。

同一v19的source30初次strict NON_PASS及两码ACTUAL_RUN_EXECUTION_MISMATCH、READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID永久保留。规范对照确认描述性build、完整测试 / child合并diff与固定baseline CASE是有限checker缺失的合法表示；source31只读修正精确联核完整SHA / import path / report、child逐字原件及独立operator baseline，不放宽到任意格式。expectation freezer独立v2只修不存在的asset.project_id检查，Task / asset归属绑定保留。独立双层RO replay实际19项通过（18新+1基线）、树不变、2487字节raw log逐字等于accepted log，child / code / diff与实际RO文件已联核；2GiB / 0swap / 256pids、4GiB虚拟地址、120秒命令上限、无网络 / 凭据 / SDK / 模型 / Task写。重放仍UNVERIFIED / Gate NOT_EVALUATED，不直接推导strict或writer证明。私有dump / catalog通过但未restore演练，r30 / API26 / 精确PG停止、空网络移除，其余数据 / container / volume / key / session / user manager和旧UNKNOWN / HELD保留。详见[本轮完整证据](CLOUD_IMPLEMENTATION_STATUS.md#r8ssh专项与固定快照严格验收)。

## 固定版本与来源

source31只读验收器修正有独立静态审查及远端controller117 passed / 两文件Ruff通过，其他419份source30 payload不变。随后对原v19固定快照实际strict PASS / failures=[]，2100字节报告SHA256 `0aa4ccff98848fc877f9e82274890ce3d7cc45d9f3b08aacbc4ee4fd26a94928`。它明确标记SNAPSHOT_REASSESSMENT / current_get_performed=false；独立baseline来自冻结Git对象与停后只读文件，原704字节expectation / 完整GET快照 / source30 NON_PASS不变。无API / DB / SDK / 模型 / SSH / SUT重启或canonical写，两个有限unit已inactive / PID0 / cgroup empty；不是新的current GET或独立child writer证明。精确source与日志摘要见实现状态。

| 项目 | 本入口基线 | 检查含义 |
| --- | --- | --- |
| Python SDK | `deepseek-harness-sdk==0.2.1rc2` | 安装包版本须与固定值相等 |
| 配套 runtime wheel | `deepseek-harness-runtime-bin==0.2.1rc2` | 必须与 SDK 同版本，单独检查安装元数据 |
| runtime profile | `sdk` | 官方 SDK 通过该 profile 与 `dsh` 子进程通信 |
| 协议服务名称 | `deepseek-harness-sdk-runtime` | 初始化响应的协议身份 |
| 协议服务版本 | `0.0.1` | SDK wire 的固定握手值，不是发行包版本或兼容协商结果 |

官方 SDK 的发行元数据要求同版本 runtime wheel，使用 NDJSON / JSON-RPC stdio；它与 DeepSeek 模型 HTTP API SDK 是不同的软件包。[官方 Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)、[固定发行](https://pypi.org/project/deepseek-harness-sdk/0.2.1rc2/)分别提供接口说明与版本信息。

doctor 只比较安装元数据，不校验全部二进制、插件、profile 或运行镜像的来源。生产部署仍须固定并核验实际平台 wheel、依赖、镜像、插件与策略文件的可信来源和摘要。仅有版本字符串或匹配 checksum 不构成完整供应链来源证明。

## 在隔离环境使用

将依赖安装在专用远端验收环境或受控云端构建环境；不要向现有生产环境或用户全局 Python 环境直接安装。以下命令假设已进入该环境并安装 HyperTest：

```bash
python -m pip install '.[cloud]'
python -m hypertest.deepseek_probe doctor
```

安装后的 console entry point 为 `hypertest-deepseek`，与模块入口等价。doctor 是默认操作：

```bash
hypertest-deepseek
hypertest-deepseek doctor
```

doctor 不启动 runtime、不提交 prompt、不登录模型服务、不读取项目凭据或个人认证目录，也不自动安装缺失资源。缺包、错版本或无法检查时输出有界 JSON 和明确状态。`COMPATIBLE` 只表示安装元数据与基线一致；此时 `process_probe=NOT_RUN`。

显式协议探针会启动独立进程并准备私有临时目录。它不接受模型 prompt、API key、仓库 URL 或环境密钥参数：

```bash
hypertest-deepseek probe --allow-protocol-probe --timeout-seconds 20
```

`--allow-protocol-probe` 是显式选择进程探针；省略时保持 `BLOCKED`，不启动 runtime。允许的 timeout 为 1–60 秒，拒绝 NaN、无限值和超限输入。关闭和清理另有有界处理，因此 timeout 不是整个命令的严格墙钟耗时上限。

| 输出 | 可得出的结论 |
| --- | --- |
| doctor `COMPATIBLE` | 固定 SDK / runtime 安装元数据匹配 |
| probe `PROTOCOL_OBSERVED` | 该次隔离 runtime 启动、初始化、会话操作、协议身份与关闭均有观察 |
| `UNAVAILABLE` / `INCOMPATIBLE` | 安装缺失或不满足固定版本 |
| `BLOCKED` / `ERROR` / `PROBE_INCOMPLETE` | 检查未完成；不能把部分成功当成通过 |

成功执行所请求检查时退出码为 0；检查未通过为 1；无效命令参数为 2。输出中的 `not_proven` 持续列明未证明的能力，`diagnostic_only=true`、`cloud_execution=NOT_ASSESSED` 表示本入口不评估整个平台的云端交付状态。

## 运行与信息边界

官方 runtime 的 SEA native addon 需要在私有临时目录中解包并进行可执行映射。隔离容器若将 `/tmp` 挂载为 `noexec`，初始化可能在加载 native addon 时失败；这与模型认证是否可用无关。本轮无模型验收采用受控 `tmpfs /tmp:rw,exec,nosuid,nodev,size=256m`，同时保留只读根文件系统、`network=none`、全部 Linux capabilities 移除和 `no-new-privileges`。这只是私有临时运行资源要求，不授权共享宿主目录执行、网络或凭据访问；实际生产 bubblewrap / 容器基线仍应单独验证。

早期一次性 Docker 容器内的真实 bubblewrap 沙箱探针因无法创建非特权 namespace 返回 **BLOCKED / NAMESPACE_SETUP_FAILED**（EPERM），默认 Docker 路径保持阻塞，没有放宽主机权限。另一次官方 runtime 在 4 GiB 地址空间限制下返回 `status=OBSERVED / reason=NO_PROMPT_PROTOCOL_OBSERVED`，无模型 prompt；该地址空间诊断本身不能代替 namespace 隔离验收。

后续 **r7** 使用专用非 root systemd RootDirectory、只读源码 / venv、空 capabilities、NnP、独立 cgroup（2 GiB memory、0 swap、256 pids）和私有可执行 tmpfs，已在同一生产 bubblewrap 运行完整官方 SDK 无模型初始化 / 关闭（12.276 秒，峰值内存约 290.4 MiB）。这条独立部署基线通过不覆盖默认 Docker 的失败，也不证明模型认证、Git / 模型网络、真实框架或完整任务。精确配置、早期失败与边界见[隔离验收说明](../ops/deepseek/README.md)。

原source-r18的 `RLIMIT_AS=4 GiB` 仅限制单进程虚拟地址空间，不是 RSS 上限。生产 Worker 领取前还要求既有独立 cgroup v2 的有限聚合 memory + swap ≤ 4 GiB、pids ≤ 256，并核验当前 PID 归属；本入口无模型初始化不能代替该资源准入与 namespace 沙箱验收。后续native Codex profile的AS16GiB修正源码已冻结并独立只读审查，root-only仍4GiB，聚合内存与预算不变；RUNNING / prompt-intent分开保存配置上限与实际cgroup闭集数值，不含路径 / 环境。source-r21所选回归已通过，新真实Task已接受runtime-reported子文件原件，但首批typed资产引用遭拒、仍RECOVERY_REQUIRED / NOT_RUN，不改写原source-r18结果。

探针使用独立 workspace、显式 Harness home 和私有 HOME；子进程环境从允许清单构造，不继承操作者的数据库、Operator key、Git / SSH 或个人模型认证。官方 SDK 自身会复制调用进程环境，因此此边界由 HyperTest 的隔离进程实施，不能只传空 `env` 后假定父环境已经清除。

输出只包含固定状态、允许的版本和布尔观察，不输出原始 SDK 异常、stdout / stderr、会话正文、秘密、原始工具 payload 或完整通知。检查不访问 HyperTest 数据库或管理 API，不创建 SessionTask / CloudTask、Job、Runner、Evidence 或 Gate，不改变 Local MCP 的身份、授权、journal 和报告结果。

进程监督用于停止本次受管 POSIX 进程组；这不构成任意恶意代码沙箱，也不证明脱离该进程范围的后代、远程 SSH / CI 或业务副作用已经停止。生产 Attempt 的取消仍须先 fence 写入权，再逐项核验受管后代和外部操作；无法确认的操作进入恢复与对账，不能由探针的关闭结果代替。

## Worker 的模型与委派 profile

以下是独立 `hypertest.cloud` 的新增接入源码，不改变前述 doctor / 无模型 protocol probe。Cloud 默认关闭、未部署生产。首个受控 Task 已固定完整读回 v14 COMPLETED / reported PASS，含15条资产记录、Run1、delegation1和两份原件；真实 ROOT27 / CODEX7 请求完整成功，接受版本内引用与字节关系已核验。该source-r18 Task的Codex仅文本分析贡献成功，子文件 / 命令工具因SIGTRAP仍BLOCKED；Root自行实现 / 执行，独立只读重放9项通过且实现原件精确关联，不升级为 legacy VERIFIED、Gate或全部P0退出。

固定 Harness source `687f282e8625c6b8d11ff58211a90524be2e4317` 的 DeepSeek provider 原生使用 Anthropic Messages，默认 base 为 `https://api.deepseek.com/anthropic`，请求 `/v1/messages`、`x-api-key`。host `ModelBroker` 仅允许固定 model、文本 / thinking / 客户端 tool_use / tool_result / tool changes，拒绝 provider 图片 / 文件 URL、hosted tools 和未知字段，不回退 Chat Completions。[固定 provider 序列化](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/llm/llm-deepseek/src/serialize.ts)、[固定 provider 配置](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/llm/llm-deepseek/src/config.ts)

Codex opt-in 使用官方 `@deepseek-ai/dsh-subagent-codex@0.2.1-rc.2` 与 `@openai/codex@0.153.4`，预装 Node、完整 lock / payload 与外部信任的 manifest digest；当前冻结 payload manifest 为 `412df5f55ec16ad37ad63ac9dff9f4217c4a0144db08ab5045709c1f6dce0d77`。shim 只将官方 subprocess 的精确 Codex app-server argv 从 SEA executable 映射到受控 Node，保留官方 provider / lifecycle / answer selection；不把 host 自行请求 Responses 冒充 CLI 委派。独立 host OAuth relay 仅转发固定 Responses 推理，云端既有 OAuth 不刷新、不导入本机账户，真实 key / OAuth 不进 namespace；内部只有限定 socket 与 sentinel。Codex accounting 只接受显式 REQUEST_CREDITS，不能称 USD 计费。Claude Code 尚为 placeholder。

官方 plugin 通过私有有界 UDS 传 READY / DELEGATION / CLOSED、递增序号和 ACK，不扩 SDK wire、不记录 prompt / transcript。`native_ref` 是官方工具返回的 external activation child UUID，另存 official run UUID；不是 Codex 产品 thread ID，没有原 thread 恢复 / follow-up。父任务交责任 / 资产，Worker 用 start / terminal 观察注入状态；只有通道关闭、全部 child 终态、父任务各委派贡献回执、整 namespace 停止及所有 broker drain 后才允许完成 / 结算。其来源始终是 runtime-reported，不等于独立证明。[固定官方 Codex 限制](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/subagent/subagent-codex/README.md#known-limitations-and-deferred-work)

同日原生无模型记录 `native-probe-r7` 已返回 OBSERVED，`provider_registered`、`tool_registered`、`subprocess_shim`、`node_available` 均为 true，官方初始化、会话创建和观察通道干净关闭均已观察；该探针没有 OAuth 请求、推理或真实 child。当时只核对云端 OAuth 的 LoadCredential 读取 / 时效，不能将之后的独立 host 单请求成功倒填成该探针已通过认证或 CLI turn。

普通 host 秘密文件保持 owner-only 0400/0600。systemd LoadCredential 的 root:root0440 / 0550 特例要求当前 `CREDENTIALS_DIRECTORY` 精确路径、readonly fs、无硬链接及 exact ACL 仅 root / 当前非 root UID；group / other 无权，不能仅凭组位放行。验证与有界读取用同一 FD，拒绝 symlink。该读取兼容代码不证明 provider 已接受认证。

另有[服务启动准备模板](../ops/deepseek/README.md#生产启动配置准备未安装未验收)和 `worker_admission`，**未安装 / 启动生产；真实临时unit的启动准入已通过，未启动长期Worker**。基 unit无 `[Install]`、`Restart=no`，env示例仍双开关false / 请求费率0；Codex为独立显式drop-in，三类leaf统一为 wrapping-key / deepseek-key / codex-oauth并核对当前 `%d` / `CREDENTIALS_DIRECTORY`。非空 `HYPERTEST_CLOUD_SERVICE_RELEASE_SHA256` 才启用该profile：完整只读门禁先于DBimport，此后每轮领取前仅复核严格凭据 / OAuth时效，失败退出，不启动模型或刷新身份。可信manifest字节SHA与实际Python / SDK版本要核验；rootfs / source / venv archive摘要只标记部署者核验记录，不伪称完整运行时重哈希。该字段默认空，现有CLI / Local不受影响；source-r19所选445通过 / 1失败保留，修正测试替身的source-r20所选66项通过 / Ruff全过，完整reported PASS与独立框架关联仍固定 **source-r18**；source-r21另有下述子文件原件 / 拒绝恢复证据。

临时 `hypertest-cloud-service-admission-r20.service`使用真实ExecStartPre doctor / `%d`三凭据挂载、相同rootfs / 2GiB / 0swap / 256pids / cap0 / NnP，ExecStart仅`/usr/bin/true`、PrivateNetwork=yes，已获得 **ADMITTED**；无DB / SDK / 模型 / Task领取，不能推定上游认证、长跑Worker或生产部署。release manifest SHA256为 `f352d4ef96e8e285ba56b32f0a2164399e2e83be9596bedf6f154782dd62a498`，回执`service-admission-r20-start-result.json`。该唯一临时unit / drop-in已精确停止 / 移除并reload，证据保留、生产未触及；renderer和精确边界见实现状态。

Worker 的 typed handoff 由实际 Cloud schemas 派生；模型只发布测试贡献，平台 auth / expected_version / key、停止观察和预算保留 / 结算由 host 控制。Git 前 preparation hold、RUNNING 前全部 scope 的最坏额度保留、完整停止 / drain 后 SETTLED 及原 hold 历史见[领域 §51.3](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#513-六步输入冻结)。失联 / UNKNOWN 继续 HELD，不自动恢复额度；Session.run idle 不改变此规则。

派生 schema 还包含显式跨字段语义和有效样例：CASE.details 的 steps / expected / actual、非 CASE 原正文 / Artifact、同批 kind/key 唯一、checkpoint 必须选择本批 REPORT、Run 时间与缺失观察说明等，不只给字段类型。尚未冻结平台请求的 typed 校验错误可产生本地 `LOCAL_REJECTED` 反馈，路径 `.hypertest-cloud/rejections/<sha256(handoff-key)>.json`；核对 key / handoff 哈希与 `platform_operation_submitted=false` 后，以新 handoff key 发布修正，保留原件。该反馈不是 ACCEPTED / 上传回执，不推进 Task 版本；未决、UNKNOWN、秘密 / 安全与平台 HTTP 错误不走该路径，无反馈也不授权重发。执行和回归证据另记，不能据契约更新称真实任务已完成。

实时活动诊断也有明确观察窗口：driver 最多发出**前 512 条 runtime 活动**，Worker 二次过滤并保留**所收到的最后 64 条**，类别计数只覆盖该有界子集。`activity_counts` 不是全程总数，`recent_activity` 不是运行最终 64 条；未观察不代表事件未发生，也不能据缺少 TOOL_CALL 断言工具从未调用。`idle_finish_reason` 单独保存，不以活动窗口里的最后一条代替；它仍只是 runtime-reported 停止原因，不是测试结果、shell exit code、平台完成或子代理清理证明。这里不保存工具参数、结果正文、异常原文、聊天或思考。

## 验收口径与剩余工作

2026-10-22 的独立远端隔离验收中，本入口相关 **46 项 SDK / CLI 测试通过（1.14 秒）**；测试源码快照摘要为 `908174496422380117ecc9ee4ce89ef2bda790c6c7fde7c328e4b8f705ab4d5b`，该快照不代表同时开发中的完整 Cloud 实现。随后在上述无网络、无认证隔离容器内安装官方固定双包，真实观察到启动、初始化、会话创建、关闭均成功，SDK / runtime 为 `0.2.1rc2`，wire 为 `0.0.1`，结果 `NO_PROMPT_SUBMITTED`。本机与远端私有原始记录目录为 `/tmp/hypertest-cloud-validation-20261022-f0c1c1c2`（日志直接位于该目录）。此前 `noexec /tmp` 的失败与修正独立保留，不能用最终成功掩盖运行前提。

兼容检查、fake-runtime 契约测试和真实官方 runtime 的无模型探针分别登记。fake-runtime 可验证官方 Python client 的方法、错误、超时与关闭行为，不能代替真实 DeepSeek 模型或外部子代理。实际运行结果须记录源码快照、测试环境、SDK / runtime wheel 身份、命令和原始报告；旧 Runner 或 Codex 的历史通过数量不计入本入口验收。

后续 r11 整合快照的 Cloud / SDK 探针 / SessionTask 与 MCP / TaskSyncCore 所选 21 个测试文件为 **370 passed / 2 条既有 warnings（57.59 秒）**；它覆盖本阶段预算、精确 handoff、本地 typed 拒绝反馈和独立控制器等回归，不等于全仓检查或真实模型任务成功。Ruff 当轮仅发现一个测试 import 排序，机械修正的 r12 远端 Ruff **全部通过**；两个快照分别登记，不外推后续改动。归档身份见[当前实现状态](CLOUD_IMPLEMENTATION_STATUS.md#当前增量验收)。

另有 r15 所选 Cloud / SDK / Local SessionTask 与 MCP / TaskSyncCore **23 文件、420 passed / 2 条既有 SQLAlchemy warnings（67.14 秒）**；r16 prompt 所选回归 **47 passed（5.23 秒）**，Ruff 对 `src/tests/alembic/ops/deepseek` 全部通过。两轮各有独立 source 身份，r16 archive SHA256 为 `43525ba8252cff0e0e9707d995e47eea817757eb5915917447050d9fbd34b974`，r15 来源清单摘要见实现状态；不将 r16 prompt 增量冒充 420 项全范围重跑，也不拼加成新的测试通过数量。

r17 的 host 诊断投影所选回归 **36 passed（6.27 秒）**、Ruff 全部通过，archive SHA256 为 `5db9e59ef97429d03880bff33599857c41e2c4f44245a7877bcafc067f9bc27c`；它验证固定诊断字段，不证明原生 child 或测试执行。

r18 的 Cloud 模型配置相关所选回归 **60 passed（6.76 秒）**、全范围 Ruff 通过；`source-r18` 快照 SHA256 为 `4e66b81e271f8ae97dc72d28656aeb89b0ac1ccf83f0f6dd49c4dee4a597624d`。仅 Cloud `cloud_codex_model` 默认选择改为现场目录支持且独立 host 请求已通过的 `gpt-5.6-sol`；legacy `codex_model=None` 和 Cloud / Worker 默认关闭均保留，模型默认改变不等于开启执行或完成原生委派验收。

source-r19含服务准备的所选回归实际为 **445 passed / 1 failed（74.16秒）**，Ruff全过。新增 OAuth 时效测试未恢复前半段的 payload 测试替身，使后续完整 admission 命中替身；这不是生产 OAuth 检查失败。仅修复测试替身的source-r20已完成 admission / runtime / private-file / resource所选 **66 passed（4.65秒）**及全范围Ruff；两份archive完整摘要见实现状态。原失败保留，66项复验不冒充446项全量通过，也不证明服务模板已安装 / 验收。

source-r21原402文件加四个native16修正overlay，远端所选 **29文件、535 passed / 1 skipped / 86条既有SQLAlchemy warnings（51.44秒）**，Ruff全部通过；跳过原因未独立核对，不当通过项。清单采集时Cloud关键80项均与共享树匹配，差异仅后续文档，完整archive / 清单 / 日志摘要及scope见实现状态。该结果只覆盖所选回归；新profile随后运行的真实Task已接受runtime-reported子文件原件，但typed资产引用遭拒，未完成交付。不把旧source-r18正式reported PASS外推到该任务。

source-r22仅在source-r21上替换模型可读契约与其测试两个文件：针对contract / rejections / runtime / delegation / controller / TaskSyncCore / SessionTask MCP的 **7文件、169 passed（15.39秒）**，两处变更文件Ruff通过；完整archive / 清单 / 日志摘要见实现状态。新契约明确Artifact只用于artifact_id，依赖只用前序接受的AssetRevision UUID；原文Upload→ANALYSIS(artifact_id, refs=[])→后续DESIGN引用accepted assets[].id的样例分开三类身份。UUID结构通过不能证明DB引用有效；平台HTTP拒绝不能变为LOCAL_REJECTED或授权替换POST。这是针对性复验，未重跑535项全量。

r14 另行运行无模型工具探针：官方 Agent 的 `ctx.tools.execute` 在原 SDK **workspace-write + ask** 政策下真实执行一次固定 printf，marker 正确、无 tool error，namespace 已停止，结果为 **status=OBSERVED，scope=SDK_FIXED_PRINTF_ONLY，test_result=NOT_RUN**。nested user namespace / bubblewrap、sh / bash 也已分别成功，未放宽隔离。探针使用独立空 workspace / home，不监听模型 socket，不读取模型身份或会话历史、不创建 Task / 执行 SUT；它排除该 profile 下 SDK shell 普遍不可用的假设，不证明模型曾调用工具、框架运行或任务交付。入口和前提见[隔离验收说明](../ops/deepseek/README.md#无模型-sdk-工具探针)。

另有固定官方 Codex CLI 无模型沙箱探针4项成功：outer printf、0.153.4版本核对、官方 sandbox printf、空工作区固定文件读写。脚本 SHA256为 `fe92eae3ca906866841572a2e50db77dbc9a5d849e07e1e004372d1285abf5f2`，沿用既有 outer / namespace和有限资源、新空HOME / CODEX_HOME、无SDK / 模型 / 认证 / Task / 真实SUT；scope为 **FIXED_OFFICIAL_CODEX_SANDBOX_WITHOUT_MODEL，test_result=NOT_RUN**。它证明固定CLI沙箱命令可运行，不覆盖正式子代理app-server / code-mode-host工具路径；单独不足以定位接受产物披露的SIGTRAP，也不能据该失败归咎于namespace或OAuth，后续精确定位另记如下。

更精确的无模型执行路径探针现已观察：**APPSERVER初始化 / ephemeral thread/start / 固定sandboxed command/exec全部成功，无turn**；同AS4GiB的官方 **CODE_MODE hello / session/open成功，EXECUTE阶段EOF、真实-5 / SIGTRAP**，只投影stderr99字节及MEMORY / V8闭集类别。两个namespace均停止，无身份 / SDK / 模型 / Task；`DIAGNOSED`不是能力PASS。

随后有限RLIMIT_AS=4 / 8 / 16GiB单变量对照已完成：每档新namespace，IPC / text source / V8flags逐字不变，物理cgroup精准2GiB / 0swap / 256pids及cap0 / NnP / payload / 隔离权限保持。**4 / 8GiB均EXECUTE实际-5 / SIGTRAP、stderr99字节 / MEMORY、V8；16GiB实际soft / hard17179869184，cell_started / cell_result / marker均true，SHUTDOWN exit0 / stderr0，三档namespace全部停止。**这支持该profile的V8有限地址兼容性因果，未发生OAuth / 模型调用，不能归为认证或namespace权限问题；16GiB是虚拟地址上限，实际聚合内存仍2GiB。固定纯text不调用delegate，仍NOT_RUN / native_agent_tool_execution NOT_PROVEN；native profile源码最小修正与随后真实Task的子文件原件证据另列；固定纯text不能替代该Task的完整交付验收。完整脚本摘要见实现状态。

真实 DeepSeek marker 探针已观察 HTTP 200 两次和正确原件，随后达到两次请求上限，SDK idle 的 `finish_reason=error`，因此 `sdk_turn_succeeded=false`；仅连通 / marker 被观察，`test_result=NOT_RUN`。首个真实 CloudTask 又运行了 86 秒 / 14 次模型请求，但 CASE.details 提案缺必需字段，平台未接受 Agent 资产或 Run；原 Task 经操作者独立 host proof 收尾为 v7 FAILED / NOT_RUN，完整模型和准备 hold 保留。反馈契约修订后，同 Project / 配置 / 固定双 SHA 的第二个关联 Task 实际运行 76 秒，观察 6 次 HTTP 200 完整响应、SDK 干净 CLOSE 及实际停止 / drain；但无 ready 文件、测试新增文件、产物或 Run，现为 **v6 RECOVERY_REQUIRED / NOT_RUN，EXPLICIT_HANDOFF_MISSING**。两个 Task 与 Attempt 的确切身份见实现状态；原失败、请求和预算历史不被覆盖。

本次 projection cache 仅有最后 step=6 / outputTokens=4096 等数值，未保存 root `turn/end.reason.kind/code`；`llmRetry` 在 turn/end 清空，不能据空 map 排除既往重试。4096 是逐请求输出 cap；官方 loop 的 max-tokens 可在执行该响应的工具前终止 turn，但达到 cap 仅是本次截断的线索，尚不能确认为根因，也不存在默认六次 step 上限。没有读取原始会话、正文 / 思考或重放旧 Task。

首次 Codex Task 的 `native-codex-r1` 在 prompt 前因 credential leaf 错配（Worker 引用 `deepseek-key`、LoadCredential 命名 `model-key`）报 MODEL_KEY_UNAVAILABLE；固定读回为 **v5 FAILED / NOT_RUN**，scope 为空、无 prompt-intent，无 SDK / 模型请求 / child，不标为 RECOVERY 或供应商执行失败。随后 `keyless-credential-probe-r3` 在同专用账户 / rootfs 用正确名字通过严格 reader 读取 DeepSeek key / 云端 OAuth，只报告布尔值，无模型请求。该准备通过不等于上游接受认证。

新独立关联 Task `01a163cc-9046-7c3c-a952-c3f5fded0e3b` / Attempt `01a163ce-777d-76c5-a7cd-317e99e4a9d3` 由 `native-codex-r2` / r16 源码执行，同 Project / 配置 / 冻结双 SHA，Root 输出 cap=16384、**ROOT20 / CODEX8 请求、900秒**与新授权预算；claim 前严格核对三类 credential path / reader，模型 key 与 OAuth 始终只在 host LoadCredential。当前固定读回为 **v11 RECOVERY_REQUIRED / NOT_RUN**：ROOT20次 HTTP200 完整响应，CODEX3次请求 / 0成功；**5份 UPLOAD_ARTIFACT 原件已接受并完整字节 / SHA256 读回，typed assets / runs / delegations 仍全部为0**。namespaceStopped、所有 broker closed / drained、inflight=0 均已观察。上传不是 typed 测试资产、Run 或正式 child 成功，停止也不自动结算原 hold。确切前序身份、失败与 HELD 历史见实现状态。

同轮另行 host 诊断对旧 `gpt-5.4` 的两次有界请求均 HTTP400，仅保留 `account/model/supported` 固定错误词。现场 `client_version=0.153.4` 的模型目录 GET 为 HTTP200，当前账户列表不含旧选择、包含 `gpt-5.6-sol`；随后 `hostprobe-r3` 以该模型单请求获得 **HTTP200 / response.completed / marker=true**。本轮现场目录和原回执证明当前云端 OAuth / 所选模型可用；这条 host 协议探针不经过官方原生委派生命周期，不称 native child 成功。

独立框架重放现已完成：固定旧 Attempt、双层只读原 workspace、新空 home、无 LoadCredential / SDK / 模型 / Task 写，实际 **17项 unittest 通过（exit0，1.18秒）**，namespace 已停止。双 HEAD 固定为 sampleproject 原 SHA、SUT clean，框架源树 before / after 摘要相同，完整 SHA 与证据身份见实现状态。结果仍为 **UNVERIFIED / Gate NOT_EVALUATED**，不是原 Task 正式 Run / 平台 PASS。上传 `test_add_one_boundaries.py` 原件与固定接受版本 / 实际重放文件的三方精确比对已通过，SHA256为 `4e4bcf1958739f6a6be7928f735962858b86e74c61cbc615e182d34cc1b5e684`，回执 `accepted-upload-linkage.json`；旧 Task 的 typed IMPLEMENTATION 资产仍为0，不称 accepted Implementation。

新的关联 Task `01a163df-8109-79fe-ae2d-562ce8da1269` / Attempt `01a163e1-2d84-72d1-a31a-60cdffe944d0` 由 `native-codex-r3` / r18 源码执行，同 Project / 配置 / 双 SHA、ROOT48 / CODEX8 上限、64 REQUEST_CREDITS、900秒、Root cap=16384、`gpt-5.6-sol`。现已**固定完整读回 v14 COMPLETED / reported PASS，assets15 / Run1 / delegation1 / originals_verified=2**；originals_verified 仅为原件完整字节 / 摘要核验。实际 ROOT27 / CODEX7 请求均 HTTP200完整完成、0 refusal / transport failure；namespaceStopped、所有 broker closed / drained、inflight0，root27step completed、native channel 干净关闭，证明本轮真实委派推理和平台接受。

该接受版本的独立语义审查已完成：资产为分析1 / 设计1 / CASE8 / 实现1 / REPORT4，8个RunCase精确引用8个唯一CASE修订且有PASS actual，设计原修订的NOT_RUN保留；Run原日志是8新用例加1基线、共9条ok。完整实现原件1245字节 / `e248a0ee…d6d9d5`与IMPLEMENTATION正文逐字一致，原报告1078字节 / `a531dd28…cf63ce`均匹配；接受记录内固定SHA、入口、Agent自报treeDigest一致，独立工作区关联另验，完整摘要与记录ID见实现状态。

`native_ref=49ba4d71-e8e6-4294-89ec-a82dfe62ab0e` / `run_id=230364df-4829-4de9-b3c2-cbb58259b8b5`的2个accepted refs指向本Task分析 / 设计，terminal source为official-plugin-runtime-reported、independent proof=false。接受的责任 / 分析 / final REPORT一致披露：子端工具反复SIGTRAP，未写`codex_analysis.md`、未改测试或运行套件，只在closing message给出建议；Root独立读SUT并完成设计 / 代码 / 执行。因此只验收native推理、身份配对和文本贡献，**该Task子Codex文件 / 命令工具仍保留BLOCKED**，不能从delegation COMPLETED推导工具通过。后续有限AS兼容性已有无模型因果证据，修正profile后新Task已观察runtime-reported子文件贡献，后续typed接受链遭拒、交付仍未通过；不放宽隔离权限。

completion required12均存在唯一、final REPORT的11refs有效、pending为空；接受预算SETTLED **34 REQUEST_CREDITS=27ROOT+7CODEX / 234秒**，原预留56和Task64上限保留，preparation同SETTLED、租约已清空，不表示供应商USD计费。准备元数据中的静态observed=false不覆盖后续正式delegation / 终态记录。

本轮已审独立重放脚本 SHA256 `45806252f325ba11dd84275c72fffc8110e8fdadf839ff51f9b1af0906ec3c42` 保持双层只读原 workspace、无 LoadCredential / SDK / 模型 / Task 写与有限资源边界。实际 **9项 unittest 通过（8新 + 1基线，exit0，1.233808秒）**，固定双SHA、SUT clean、source_tree_unchanged、namespaceStopped均已核对。接受实现原件、固定接受版本原文字节与实际重放文件三方精确匹配 `e248a0ee…d6d9d5`，Git原始状态只含这一份untracked新文件、无其他tracked修改；关联回执为 `framework-replay-evidence/replay-supported-r18/accepted-implementation-linkage.json`。

宿主清单tree摘要 `b526ba8d…e1cabc` 与Run自报 `execution.test_tree_digest=a825eecf…6dd6c` 没有规定相同规范算法，不能等同；完整摘要见实现状态。独立重放不写平台状态，仍为 **UNVERIFIED / Gate NOT_EVALUATED**；不将前一轮17项结果转移到当前Task，不将平台 reported PASS升级为legacy VERIFIED Evidence或全部P0通过。子Codex文件 / 命令工具的SIGTRAP边界、前序失败、原请求和HELD历史保留，Claude仍为placeholder。

source-r21 / native16的新独立Task `01a16539-e3bd-72e9-b7e3-e66155fbaee6` / Attempt `01a16540-aa01-7b4c-ac8f-dcf16d9fd9a8`已真实执行，固定完整读回 **v7 RECOVERY_REQUIRED / NOT_RUN，REPORT_RECONCILIATION_PENDING**，并非终态或测试FAIL。实际ROOT16 / CODEX5均200完整、0 refusal / transport failure，namespace与所有broker stopped / drained、inflight0；AS16GiB与实际2GiB / 0swap / 256pids保持。

该轮接受 `codex_analysis.md`原件Artifact `01a16542-f633-7f90-8cd8-792415be2b44`，4642字节 / SHA256 `e0b5c5d5114143700b088a60413027f3f53bf9ce886134bd5b3c23913234838d`精确读回。正文记录本人读取固定三份源码、只读AST命令 / exit0和12类边界设计；这是**runtime-reported子文件 / 检查贡献恢复**，不是独立writer proof、正式Run或已接受ANALYSIS资产。随后首个SUBMIT_ASSETS错把Artifact UUID填入referenced_asset_ids，确定首发4xx / REJECTED，持久码CLOUD_OPERATION_REJECTED；原HTTP状态未保存，不能把当前代码对应422写成历史捕获值。**typed assets / Run / delegation均0**，56credits / 900秒完整reservation与900秒preparation hold保持HELD。

原平台写均完整读回、无UNKNOWN；原拒绝key的GET为404且无accepted receipt / 无新POST / 不授权重试，继续保留REJECTED，不走本地纠错或新key重投。旧source-r18子工具SIGTRAP与reported PASS、本轮子原件接受但typed交付失败分别保留；新契约与新Task结果另验，不复用旧child文件或ID。准确读回身份、原因、预算与原件证据见[实现状态](CLOUD_IMPLEMENTATION_STATUS.md#native16新task子文件原件已接受资产引用拒绝后保持恢复态)。

source-r22新独立Task `01a16551-0b71-7fa5-83ee-f864f842e447` / Attempt `01a16552-5550-75ca-8474-0c98db018ab1`已真实执行并固定完整读回 **v17 COMPLETED / reported PASS，16资产 / Run1 / 8RunCase / delegation1 / 原件4份**。已核对预算SETTLED **41 REQUEST_CREDITS=36ROOT+5CODEX / 193秒**、原56credits / 900秒保留、Task64上限及preparation同SETTLED；当前lease generation2且owner / expires清空，namespace_stopped / brokers_drained与completion停止字段true、pending=[]。实际AS16GiB、cgroup仍2GiB / 0swap / 256pids，固定授权 / 双SHA / PRDv3一致。本Task原件 / case / Run / child引用已独立核对；另以受控host文件确认ROOT36 / CODEX5全部HTTP200完整、0refusal / transport failure、每scope closed / drained=true、inflight0、namespace stopped。SDK投影idle_finish_reason=completed / last_phase=DELEGATE_CLOSED仍不是测试结果；native channel CLOSED仅有完成前代码门禁，没有另存独立布尔，不编造观察。

4732字节子分析原件SHA256为 `93685b5f5a5c130ce58cefc7111a48d23505ff723e75d53df909c3e272d53a1e`，native_ref=`06b334f1-7287-4e5b-b565-3da942dfc237` / run_id=`f33b1665-04e3-4bb7-b7da-13e5a40a58a2`的两个accepted refs有效指向本Task分析 / 设计；子文件读 / 只读AST检查 / 写分析为runtime-reported，非独立writer身份。**本次PRDv3要求分析和设计都直接设置child artifact_id，但DESIGN.artifact_id=null，仅经DESIGN→ANALYSIS→child原件有效传递；这项精确交付要求未完全满足，不能称strict PRD全部PASS。** 平台允许该引用形式，接受版本和偏差都保留。

本Task另已独立只读重放 **9项unittest通过（exit0，0.619989秒）**，固定双SHA / SUT clean / source_tree_unchanged / namespace stopped。3272字节完整diff原件解析得到的2832字节测试文件，与实际重放文件和before / after清单精确关联；回执 `framework-replay-evidence/replay-native-io-r22/accepted-implementation-linkage.json`，完整摘要见实现状态。host tree `3cd167d2…22f886`与AgentRun tree `f8259ee3…e9c0b0`没有相同规范算法，不能等同。首次临时unit因脚本root0600不可读而exit2，未启动测试；授读0644后的新-r2 unit才成功重放，历史日志保留。重放无凭据 / SDK / 模型 / Task写，仍 **UNVERIFIED / Gate NOT_EVALUATED**。新账本不重放r4请求，不拼接旧Task证据；安全、原件、备份、精确偏差与source身份见实现状态。

历史r22轮隔离API已停止，自建验收 / PostgreSQL容器及空internal网络已移除，活跃 / 有租约Attempt与待解析数均0，旧RECOVERY / HELD保留；所有host证据、固定payload / venv archive与受保护凭据仍可复查。私有DB备份及 `pg_restore --list` catalog校验通过，未做完整恢复演练；该历史轮本会话未执行生产部署 / 配置更改，不保留该轮临时在线Task入口，详见 `validation-cleanup-r22.json`。

本说明不主张以下能力已通过：

- 旧PRDv3 Task的DESIGN直接child artifact_id要求（实际仅传递引用）保持NON_PASS；新PRDv4 Task已另行严格PASS。DeepSeek自行成功路径与Claude Code委派 / 原件回收仍未全验收。
- CloudTask / CloudAttempt在租约失效、凭据撤销、持久问答、重复调度与恢复方面的完整可靠性矩阵；受控fixture已接受的六步reported PASS及阶段报告按实际范围保留，不外推到该矩阵。
- 真实业务任务的完整进程树取消、远端副作用停止或原会话恢复。
- runtime 全部二进制、插件、策略组合的供应链准入。

官方 `Session.run()` 结束只表示其活动区间到达 whole-agent idle；根回答、`turn/end`、`session/wait` 与 in-process `subagent.finished` 均不足以证明外部委派收尾、任务业务完成或测试 PASS。[官方 SDK 协议](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)当前也不提供单会话取消 / 关闭或运行中动态审批。

只有全部满足实施计划中真实自行处理、两类委派、终态、可读产物和清理的退出条件，才可宣布整体 P0 完成；本次受控 Codex 路径的平台接受单独保留。SDK 未安装、探针失败或云端运行组件停止时，现有 [ADR-018 会话同步](CODEX_SESSION_TASK_SYNC.md)应继续独立可用。

本会话未执行生产部署或更改生产配置；其他并行任务已更新生产容器，当前生产全局状态不由历史验收uptime推定。r6 / SSH隔离服务的当前状态与退场须以各自新回执为准。
