# 云端任务实现状态与接入入口

**最新 P0 工作：** [Web 未决保全与 Cloud 安全收尾](P0_RECOVERY_DELIVERY_20261023.md)。本轮开始时实际部署为 `55de50e`，下文 C4/6d49 属于旧轮次；本次实现、回归和部署身份以新记录为准，用户功能验收仍由用户负责。SDK 原会话续接未实现，人工收尾不清 UNKNOWN、不释放 HELD。

## 正式 Git 集成与当前部署边界

正式迁移已接续管理路径的 `0024_local_task_binding`：先 `0025_cloud_tasks`，再 `0026_cloud_ssh_operations`。C4 Git `d065ae2e27b6ff37c87a8ebe0c549a96dda45a73` 已部署到单人专用测试服务器，当前库备份后从管理 `0023` 向前升级至 `0026`；API / Web / nginx 与原 Worker / PostgreSQL 五角色健康，独立 Cloud Worker 以 Codex=true / SSH=false 空闲运行。新空库迁移、组件回归、构建、doctor、基础健康和路由检查分别记录为部署检查，用户验收 `PENDING / USER_OWNED`，未经用户明确要求不擅自开展。Web Cloud详情步骤勾选显示修正已按6d49单独部署；API / Worker / schema保持C4身份。精确 Git / image / 各轮结果见[本轮交付记录](CLOUD_GIT_DELIVERY_20261023.md)。旧隔离 fixture 的 `0023_cloud_tasks` / `0024_cloud_ssh_operations`、source pins 和接受记录保持历史身份，不以新编号改写；统一入口 / Local 绑定由[独立管理交付](UNIFIED_TASK_CREATION_DELIVERY_20261023.md)记录，不由 Cloud 部署检查推定真实 native bind 通过。

服务器允许开发中断，按本地修改 → Git commit/push → 服务器拉固定完整 SHA 构建、向前迁移、重启 → 必要部署检查交付。纯文档变更只做静态检查，不额外要求生产维护窗口、恢复演练或业务验收。代码开关默认仍关闭；当前服务器配置与默认值分别记录，不由当前进程存活推定每 Attempt 准入。

API 镜像只安装 `cloud-crypto` extra（cryptography）处理项目凭据的加密与解密；不安装官方 Harness SDK/runtime，不加载模型身份或执行 Agent。受控 Worker 独立安装 `cloud` extra。Cloud 写入持有与人工 DELETE 冲突的 Project 共享行锁，拒绝已删除项目；保留任意 CloudTask（包括 CANCELLED）时禁止删除 Project，归档不删除任务。旧 key 回执仍在当前授权和原提交者约束下只读。混合目录隐藏已删除 Local 任务；integration actor 只见 BOUND owner 或 UNBOUND 精确 intended actor 对应的记录，未绑定和首次同步前的来源与同步时间保持 null。

ADR-022 的 Memory Gateway 是独立 Proposed / NOT IMPLEMENTED 提案，不在本次 Cloud 交付中。经验服务与 Canonical 测试状态、TaskSyncCore 分离；`task:sync` / `cloud:work` 不授权经验访问，服务管理 key 不进入 Agent，外部 Generation / Embedding 默认关闭。

### 能力响应：实现支持、配置与准入分别读取

`GET /cloud/capabilities` 返回静态实现能力，不读取秘密或文件、不 import SDK，也不探测当前凭据、进程或模型。

- `support_semantics="IMPLEMENTATION_NOT_ADMISSION"`：`supported.codex_delegation=true` 表示本候选具有 Codex 实现，不表示当前 Attempt 可执行；`claude_code_delegation=false` 保持占位。
- `supported.ssh=false` / `remote_ci=false` 表示一般 SSH / CI 不支持；固定诊断单列为 `ssh_fixed_diagnostics=true`、`ssh_profile="SSH_FIXED_DIAGNOSTICS_V1"`。`environment_connections=["NONE"]` 保持现有连接语义，不能据此否定或扩大这个独立受控 profile。
- `configuration` 分别给出 `cloud_enabled`、`worker_enabled`、`codex_enabled`、`ssh_fixed_diagnostics_enabled`；这些是当前开关值，不是认证、payload、网络、预算或隔离预检成功。
- `admission={"state":"NOT_CHECKED","scope":"PER_ATTEMPT","checked_by":"WORKER"}` 明确本 GET 未做准入。原 `profile` / `enabled` / `worker_enabled` / `sdk_package_version` / `not_proven` 保留；模型身份、执行和委派仍由 Worker 在具体 Attempt 领取前检查并单独留证。

**更新：2026-10-23，Asia/Singapore。部分实现、代码默认关闭；C4 常驻部署可供用户操作，用户验收未执行、由用户负责。本轮未创建用户验收业务数据、未启动新的模型或SUT执行；组件回归使用的合成fixtures按各自范围登记。source30 Worker / source29 helper的r8 Task已固定完整读回v19 COMPLETED / reported PASS，canonical固定SSH专项PASS；source31只读验收器对同一v19固定快照的SNAPSHOT_REASSESSMENT为strict PASS，未进行新的current GET、模型 / SSH / SUT执行或canonical写入。source30初次NON_PASS及两个码永久保留。独立只读重放19项通过、原件链联核，私有备份 / catalog核验与owned隔离服务退场完成。旧source-r22直接引用缺口、r7 UNKNOWN / HELD及r6严格PASS分别保留；仍非独立writer证明或legacy VERIFIED / Gate通过，故障矩阵与其余P0未全退出。Claude占位、CI与一般远端shell不支持。**

本次加入 [ADR-019](architecture/ADR-019_CLOUD_TEST_TASKS_WITH_DEEPSEEK_SDK.md) 的独立 CloudTask / CloudAttempt 路径，采用官方 `deepseek-harness-sdk==0.2.1rc2` 与同版本 runtime。现有 ADR-018 SessionTask 同步、旧 Run / Runner 与各自历史继续保留；Cloud 的执行和同步权限不由 `task:sync` 派生。

## 第一阶段：严格直接原件验收已完成

物理执行使用source-r23，Task `01a166bd-059c-7107-acc9-0bafe7ceb781` / Attempt `01a166be-3ee5-7f9f-bd73-88ea855cb3d4`固定完整读回 **v20 COMPLETED / reported PASS**。19资产为ANALYSIS1 / DESIGN1 / CASE14（7个key各两修订）/ IMPLEMENTATION1 / REPORT2；Run1的7个RunCase精确引用后7个CASE修订。ANALYSIS与DESIGN均直接设置同一4543字节child Artifact `01a166c0-1a77-7a15-8493-55e2e2776f88`，SHA256 `b8c8878c4d1458baf45e2b2c422ca918a7343b53875c8ba9049a37ddec25487b`。native_ref=`2916a437-a91c-478d-93ab-6d9cc4cba1f9` / official run_id=`063a84ee-1d11-49f1-a961-d42c0a1761b4`与本Task接受贡献配对，来源仍是official-plugin-runtime-reported，非独立writer证明。

完整接受读回SHA256 `88c50114f46453cefc13d15fa21dea4a921da98a12abc9a6677722f23c441c7b`。实现同时保存1635字节原始测试文件和1886字节完整unified diff，分别为 `d52edc2a95f9a89bdd747e86bdc4570266758904df581d93df921fcfab4a04bf` 与 `c2ec3721597699e6150c4f8ecec2ad1480ac73c79dbf49543256b0e2fa52c917`；diff重建逐字等于raw，原件归属 / refs / hash / bytes与实际重放文件、host日志已联核。独立双层只读重放 **8项unittest通过（7新+1基线）**、树前后不变，关联回执为私有证据目录内 `r6-accepted-implementation-linkage.json`，不写平台状态，仍UNVERIFIED / Gate NOT_EVALUATED。

预算SETTLED **47 REQUEST_CREDITS=ROOT41+CODEX6 / 224秒**，原预留56credits / 900秒与Task64上限保留、preparation同SETTLED。接受settlement核对namespace_stopped / brokers_drained=true，lease generation1→2且owner / expires清空；AS16GiB、实际cgroup2GiB / 0swap / 256pids不变。请求计数不补造逐HTTP成功统计，也不表示供应商USD。SDK idle、原件上传与reported PASS分别保留，不升级legacy VERIFIED或全部P0。

source-r23物理源码archive `a765288f6465aecf294d1c8f7b1497f9c349676e269429fe7685380df9bda5f0` / manifest `5ee09d2f62fca6d1ac19c4e3df001989aefdc38f72a61062078ee92c33b49304`，所选回归 **201 passed（10.62秒）**及四文件Ruff通过。初次严格NON_PASS的三个码来自验收器误把actual_sut_build限定裸SHA、把显式raw+diff双原件误当diff-only，以及只接受旧JSON成功literal；不是框架断言FAIL。source-r24仅两个验收器 / 测试文件有限等价解析修正，逐字校验双原件、精确repo@SHA和成功闭集，未改Task / 原件 / prompt或重跑模型。

source-r24 archive `372f5fb9c1e7a78214b791b2bdc7956139fbd6400d199066789cdee7fe8a643a` / manifest `a65f9182c89704d5ac1e545c36f4e99ab0ece50952b664420a5a0567f5959ca9`，远端所选 **231 passed（10.81秒）**、Ruff通过。同一v20只读严格重评 **PASS / failures=[]**，assessment SHA256 `b80c6ab449f95e117ef8869208fa588fded7bbb90022993b5b283ca94797000c`，canonical aggregate未变；旧source-r22 v17仍只有DESIGN_DIRECT_ARTIFACT_MISMATCH的NON_PASS。保留初次误判、旧失败 / RECOVERY / HELD历史，不拼接不同Task完成验收。

第二阶段[固定SSH诊断](architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)的r8 canonical专项及source31同v19固定快照strict重评均通过，旧source30 NON_PASS保留；独立开关默认关闭，C4服务器也保持SSH=false，真实staging及取消 / 失联矩阵未验收。上述隔离服务已按独立回执退场，历史r22退场记录保持原轮次范围；C4常驻部署单独记录，未重放旧r8 Task或启动新模型 / SUT。

环境路由硬边界：XBlock staging需SSH / 服务器日志 / 操作的任务仅Local，由用户Mac经Workbench CLI访问；166dev内网自建链仅Local。纯Web / API可选Cloud仍需独立实现并验收HTTPS访问，网络可达不等于当前runtime支持；在本SSH小片之后另行接通。禁止Cloud直连受限环境、转发绕过 / 扩IP许可或复制Mac登录 / 本地环境秘密。固定 SSH 诊断仅在隔离 fixture 中实施；通用 SSH 仍不支持，不改变Project共享双模式；见[执行环境路由](CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

## SSH实施回归与transport试点

source25从source24作Cloud-only overlay，共421文件，新增`0024_cloud_ssh_operations`在独立验收DB向前迁移成功。archive SHA256为 `e37b744a5a199422842e8533e8f53783890538ba9032509d40599bc83e3aa948`，manifest为 `2ce40505650c0d2b87a4b00a108c7f0c37b1ed9e3c3cf78689f8a361c4db30f1`。远端所选 **32文件、685 passed / 1 skipped（50.17秒）**，pytest日志SHA256 `63ae4184ceb5a1db5caf565e6200f5c79653ca0054704084e6259f899858c1c5`。跳过未计通过、具体原因未在本次独立审查核定。source25的Ruff有4个I001导入排列失败，原结果保留。

source26仅将Cloud schema、SSH authority测试、catalog renderer和SSH Worker测试的导入机械换行 / 排列，其他417文件保持原字节。archive为 `5689fc4d7e9327867ffbfe93885f5ba18956af9ebd42b1f714c9ab2999fe6087`，manifest为 `64af46361a16c57948788806163a93a897d6102bef5a5805286c128aeae185fc`。SSH三个所选文件实际 **91 passed（9.70秒）**、broad Ruff通过；pytest / Ruff日志SHA256分别为 `8794c909e79a18b938d007dcb3a85cb13e3d6f7e8455760d58e486a29491a8b5` / `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`。不将91与685合计，也不称685项重新执行或整个共享dirty工作树已验收。

当前SSH增量包括独立开关、typed固定profile、canonical远端意图 / 追加观察 / 不可变终态、短票据、host UDS代理、forced helper和受信只读OpenSSH准入。Agent仍无网络 / SSH / signing / 平台身份；每操作≤30秒、每流≤64KiB、最多8个串行动作。SSH动作截止从含Git准备的原Attempt截止固定提前30秒，准备前后不足窗口即拒绝；现有Worker循环到cutoff只关闭SSH scope，root / 模型仍可在原总预算内继续工作区工作，未知仍Recovery / HELD，不推断Task完成或PASS。

首次真实loopback transport探针已执行，但未通过：fixture unit的`PrivateTmp=yes`遮蔽了位于`/var/tmp`的固定配置，sshd在读取配置前退出、没有监听。89字节诊断原件SHA256为`62afd86d81e40d97945ec63ddd1616d8da13b10c69eeb93bd70765f7ac6feb2c`。驱动只发出一个START；合成操作`79711fe2-b2e4-4e83-ad69-f3d39a5069fa`保留UNKNOWN / remote_closed=false，原ID只读观察到操作目录与unit不存在，不将NOT_FOUND、无监听或票据到期改称终态，也不重发原START。

source27仅对fixture unit模板增加固定实例目录的`BindPaths=@FIXTURE_ROOT@`，保留PrivateTmp；archive为`c0e1d5b8bc7e279d8496fbcf5f4234708276f94d54f9f815fba6aaee10ec1632`，manifest为`e50b41f8b03e1b87c0ab391731d127eb470df630dea990d08a5ff1f0e87412f8`，其他420文件字节不变。新独立unit / Attempt / 操作key / 证据目录在核对原驱动与daemon整树停止、原票据 / hard deadline及偏差窗口已过后执行；旧失败与UNKNOWN继续保留，不与新探针拼接为一次通过。

新source27探针实际观察到daemon active、SSH banner、认证、forced helper与固定action执行，命令exit0；但收口未通过。新操作`f7059fbf-0148-4452-b8fb-7ac08f912898` / 合成Attempt`99ab37e7-f935-4f36-86d2-646d5fecac7a`仍UNKNOWN：原unit为loaded / active / exited，相同InvocationID、request digest描述与command-result一致，Result=success；systemd已清空ControlGroup，helper因要求非空原组而退回START_UNCONFIRMED。原件只有boot / unit / invocation，没有执行前实际cgroup记录，不能从空字符串、确定性路径或成功exit补造停止证明。操作者按精确原身份行政stop已获ACK及post inactive / not-found，但仍不补写terminal / remote_closed。source28候选仅修helper与测试：action启动前持久化实际原cgroup，后续绑定boot / invocation / request / unit / uid，并在真实STOP ACK、post状态及原组empty / removed后封存；已静态审查，尚待远端回归与新独立实测。旧closure / catalog和UNKNOWN保留；该轮暂停后续r7，新独立transport结果另列如下。

source28已归档但未测试。为保留旧helper闭包，source29再加仅host运维CLI可选的严格版本化`unit_wrapper`路径，默认旧路径保留，不进入Agent / action schema；新版本closure / catalog / unit / state均独立安装。source29 archive为`921bb3a38d6ee99b4dde9428dfaa17d6944e93e28b788270eb5fa2dab55cf1e3`，manifest为`26d277dcaa5c8387f87de8b300be5006abb32bfb290f765f70cc901de5aff817`，相对source28仅helper与测试两文件变化。远端第一轮 **111 passed / 1 failed（7.38秒）**，失败为既有可信SSH客户端测试返回SSH_CLIENT_UNTRUSTED，日志SHA256 `27b96617b995c4f8db7e3669271f35bed9ec6f8380121ca21f05f2cc0d96b8dc`；该轮Ruff未执行。实际元数据探针确认测试容器遗漏原profile的`/tmp`执行挂载：noexec=true、uid0 / mode755的文件仍X_OK=false，准入正确拒绝，并非原cgroup修复失效。

恢复既有`/tmp:rw,exec,nosuid,nodev`后，同一source29字节、无源码 / 校验放宽的独立复验实际 **112 passed（8.76秒）**、broad Ruff通过，pytest / Ruff日志SHA256分别为`e6b5fc45c303851384c61763a8909dbc1f7d1512c05b4af4d00a8f0cb138df76` / `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`。保留前轮失败、不合计两轮计数。

versioned安装首次在启动前被临时脚本误将合法shell`$@`识别为未替换模板而中断，仅创建部分新版本文件，没有probe / Task / 模型启动。原安装意图与已有字节保留；独立审查的`finish_install_r29.py`在完整核对原意图、原闭包及现存文件后，以新O_EXCL completion意图补齐精确4个缺件并运行`sshd -t`，不重跑原install或覆盖旧文件。修正只识别`@[A-Z][A-Z0-9_]*@`占位符，导入前拒绝额外编译缓存 / 模块并逐字核对源码。恢复已完成，新catalog摘要为`256b83f91a75adce1cb993a6ae74bd1a0bf0d4995fa7fff80850aec9b6bbddd8`；该运维恢复不改变source29 runtime或112项回归身份。

新r29独立transport试点已实际 **OBSERVED**：合成Task `17706625-3d02-49e3-bf55-242eefcde7aa` / Attempt `cb06165d-b97e-4581-acb4-751c608fc0bc`有两个真实远端terminal；host独立核对执行前原cgroup、对应Invocation / stopproof与当前空组，`independent_original_cgroup_check=true`。四项检查全部true：同key不第二次START、丢ACK后原ID查询收口、NOT_FOUND查询不START、错误host pin拒绝。私有fixture目录内`launcher-r29/host-observations.json`与`launch-result.json`保留原件；旧两个UNKNOWN不改写。scope为合成MemoryAuthority / canonical_cloud_task=false / sut_test_pass=false，没有SDK / 模型或正式CloudTask；取消 / 超时 / 后代场景仍NOT_RUN。

安全投影证据SHA256：`launcher-r29/host-observations.json`为`d862961321c6cc3b51c00c3551390c5e86d211c830f9c02e5a55a395c295a9b7`，`launch-result.json`为`a4881e466df6c6df08d97f4cfd99e4140cdfad8e6bb2fa5b3593dbdcf64c8085`，独立driver summary为`920b2cae5175fe8c136e5dae1b4a51e89ef5645004c54d0adead56e23036aa42`。它们只证明该独立probe，不迁移为正式任务结果。

独立transport通过不替代canonical SDK Task或故障矩阵。后续r7以CloudWorker source26 / helper source29执行但未收口；r8以source30 Worker / 同helper的专项通过另列如下。canonical同Task未决远端操作仍阻止完成、结算和新Attempt；新Task通过不倒写旧UNKNOWN。source23 / 24已有严格六步证明继续按原身份保留。本会话未执行生产部署或更改生产配置；其他并行生产更新不由本轮源码快照覆盖。

r7已按明确步骤开始：credential一次POST与原key GET核对scope后，创建同Project、关联原r6 v20的新CloudTask `01a1673a-2ea3-7596-b44f-b71c16676c09`；该时点固定读回v2 DRAFT、resolution `01a1673a-2eef-7535-be5a-47977022c350`为PENDING，pending keys与其他queued均0。此创建 / 解析准备尚未启动SDK / 模型，也不是SSH集成通过；原请求与后续接受版本分别读回，最终执行证据待补。

r7真实执行现已固定读回 **v17 RECOVERY_REQUIRED / NOT_RUN，SSH_RECONCILIATION_REQUIRED**，Attempt为`01a1673c-1efa-7d90-8d5a-970246afbacc`。21资产 / 5原件 / Run1 / delegation1已经接受；ROOT25 / CODEX8均HTTP200完整且drained，namespace_stopped=true，但它们不能替代远端SSH收口。72 REQUEST_CREDITS / 900秒原reservation保持 **HELD**，已观察33credits / 208秒不标SETTLED。准备时capability的native observed=false未因本次缺少final完成证明而改写，也不据此否定已有模型调用 / 贡献记录。

唯一canonical SSH操作`01a1673d-93ba-7807-ac3f-52e65943f97a`、key=`deployment-read`保持UNKNOWN，两条观察为TRANSPORT_UNKNOWN / CONTROL_UNAVAILABLE；没有远端操作目录或接受终态result。request固定helper source29 / catalog摘要与试点一致。CONTROL_UNAVAILABLE是清理链的有界错误类别，覆盖授权、签票、传输及记录异常，不能单凭该词判为凭据失效。此恢复态不是框架断言FAIL或终态失败，也不覆盖原r6 v20严格PASS、独立transport29通过或旧两UNKNOWN历史。

同一固定image、`997:988`、无网络 / 私钥的独立keyless诊断已复现本地启动差异：`pwd.getpwuid(997)`没有记录，`ssh -G -F none`在连接前exit255、固定类别`No user exists for uid`为true，stdout0；根因是image缺服务UID的NSS记录，原root driver的UID0存在。证据为私有`r7-keyless-local-uid-diagnosis.json`，不是SSH key、host pin或远端action失败。原r7不重START / prompt、不自动reconcile或新Attempt，UNKNOWN / HELD不因定位根因而释放。

source30仅改Worker admission、run_once preclaim seam及SSH Worker测试：SSH开启时先懒加载pwd，核有效UID与NSS记录UID / 进程主GID匹配，缺失以`SSH_LOCAL_IDENTITY_UNAVAILABLE`闭锁；只输出resolved / primary_gid_matches布尔，不输出用户名、home或shell。service profile和无profile的run_once都在DB / resolution / attempt claim前检查；默认SSH关闭路径不查询NSS，原outer nonroot规则不变。新固定image仅增加服务997:988的合成passwd / group记录，保留旧image / rootfs，不换root或挂宿主`/etc`。后续新独立关联Task须另行完成准入，不能把此修正拼接到原r7验收。

NSS-only新image已实际构建为`sha256:797050fea7d083d90bfac3a4ce1625560b4f088ca9d9e3843ffaf060e08ba93c`，独立rootfs位于私有验收目录`runtime-rootfs-r30/rootfs`；导出归档226000384字节，SHA256 `d71bdf314e29f0b2bcd03b4051cb9bc3daae48c981561e08a6b0dc4371fcded4`。同UID997 / GID988、无网络或key的keyless检查从pwd未解析 / ssh-G exit255变为pwd解析成功 / ssh-G exit0，固定SSH二进制与`/usr/local` / `/opt` payload清单不变；外部venv / delegate未挂入构建容器，旧image / rootfs保留，没有SDK / 模型 / 平台写。该结果只证明本地NSS与客户端配置读取，尚不证明实际SSH连接或r8 Task。

source30 archive `669fa4368f4fb6bce1762f16b06d0bbf98e7363003b955b6066d3faab3072223` / manifest `e3c660ebfd0dd530942467865cf4034ae6df6f1f2ae130bffbabe887821dcf9b`在上述新image实际执行所选32文件，结果 **717 passed / 1 skipped / 86条既有warnings（41.37秒）**，broad Ruff通过。pytest / Ruff日志SHA256分别为`79ff5106d64035f55b59bcb41bf8c6aaed631ad7c7dd3055b02203ec329dcd51` / `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`。跳过为`test_local_deepseek_bridge.py:173`的Node前置条件，不计通过、也不代指真实native probe；86条为既有SQLAlchemy DISTINCT ON告警。该兼容快照继承冻结的Local payload，未重做其他owner当前Local三宿主全链，不声明整个共享dirty树已测。

### r8：SSH专项与固定快照严格验收

新独立Task `01a16762-5fc8-7207-842a-286dd9ede3e0` / Attempt `01a16764-b2bc-703a-8fc5-d4586fd267ec`使用source30 Worker、新NSS rootfs与source29远端helper，固定完整读回 **v19 COMPLETED / reported PASS**，26资产 / 5原件 / Run1 / 19 RunCases（18新+1基线）。读回文件141601字节，SHA256 `dba59ecc7bbaa04385014f80ad3d743c7eab984dfb06e42edb9b032a16378bd2`。host观察ROOT30 / CODEX5请求、全部broker closed / drained、inflight0与namespace停止；接受预算 **SETTLED35 REQUEST_CREDITS / 238秒**，原72credits / 900秒reservation保留，不代表供应商账单。

ANALYSIS `01a1676c-fb32-7c9c-aec4-445b9a64ce09`与DESIGN `01a1676d-20fb-79a0-b0e7-b7b670273e72`均直接引用本Task child Artifact `01a1676c-ba7a-7ffa-833b-6aa8100b8baf`，5670字节 / SHA256 `418170dbe8761613242cb91beac12d8665c8181cfb18d2e4959b2fd9ea15d1dd`。native_ref `39f003a0-207e-4835-8d04-a0dea472a28a` / official run_id `c7c0ac89-fbf4-46a7-8481-7ef196c5498a`及接受贡献链一致，来源official-plugin-runtime-reported，非独立child writer证明。

canonical SSH操作 `01a1676b-70e6-7b2d-ac07-f4d8581766a5`有真实终态。独立只读SSH专项assessment **PASS / failures=[]**，2840字节，SHA256 `7477844a7ab3ea13727fd8f66e94696c48ba1d7aab702bde082830618514fd99`；该有限判定联核固定Task / 原操作 / helper闭包、canonical result、原cgroup / STOP证明、精确只读action输出与host收口。它不证明任意remote SUT部署或故障矩阵，也不把准备期native observed=false改写为独立writer证明。

完整workspace strict按source30原规则初次实际为 **NON_PASS**，失败码为`ACTUAL_RUN_EXECUTION_MISMATCH`、`READBACK_STRUCTURE_OR_SUPPORTED_ORIGINAL_FORMAT_INVALID`，原报告SHA256 `c6108e4dbf7050f33b75a4c80d75791c834280c18f52eea0912a11a2bf0e1c37`永久保留。独立规范对照确认：PRDv6未要求actual_sut_build只能两种literal，未禁止测试 / child合并diff，也未禁止固定baseline CASE。source30有限checker拒绝合法完整表示，不能称框架断言FAIL；source31仅增加精确描述性build、逐字相同child块和独立operator baseline的有限支持，不以substring或Agent自报补证明。原reported PASS、Task / PRD / 原件不修改，不重跑模型或SSH。原expectation 704字节 / SHA256 `554f1001aa3d74ff4a71930f965cfc60b264f72e86b2d10303831e7183f700ef`、canonical读回摘要 `6354dee94f1f2bd1c2b4ea7486e0dfc2cb6c29a3815ad698b48cd2f962a41a1e`保持。

运维host venv入口最初不可用，后续对固定抽取CPython的keyless import探针实际READY；原expectation freezer还因读取CloudAssetRevision不存在的project_id失败，独立v2仅删除该错误字段检查，保留Task.project_id及asset.task_id / attempt_id精确绑定。原r7 v17 UNKNOWN / HELD、两次合成UNKNOWN和r6 v20严格PASS分别保留；source31的新只读报告不覆盖旧assessment。

本r8的独立双层只读重放已实际 **19项unittest通过（18新+1基线），exit0**。namespace停止，无SDK / 模型 / canonical写入；before / after树摘要均为`de03fc232b04afb60ebc619fd1f53e60a9ee03537eb9652da2305ad357ada6bb`。accepted raw child / 测试code / 双块diff与实际只读树逐字SHA绑定；stderr2487字节末尾OK，SHA256 `b09188ef9e3fbdc9eb63dcb1c8f5706ee826a2425a8ee89b5ce73f036b9ad76e`与接受raw log逐字相同。私有回执`framework-replay-r8-evidence/replay-r8-v19/observation.json`为5534字节、SHA256 `7addb75d84020a2f6faf6cf12a8c0c30c73f7052f2c5dba45cc3ca94d23ed658`。重放采用120秒命令上限、2GiB / 0swap / 256pids、无委派profile的4GiB RLIMIT_AS、无网络 / 凭据 / 真socket的原隔离profile，仅挂固定SUT / framework和接受材料只读；不将成功重放当strict修复、独立writer证明或legacy VERIFIED / Gate通过。

私有最终custom dump已完成，1182203字节、SHA256 `e7ff6c747247e085d0037d0576149710899a60d767d26fdbc0be84054a9aef39`；PGDMP头与`pg_restore --list` exit0通过，catalog70454字节、SHA256 `8e5267650483e1f4f2644e6ca1b16115c254ff220006081f75e988e171e0d555`。回执`r8-final-private-backup-cleanup/backup-result.json`保留全部原件、旧备份与UNKNOWN / HELD；这是归档 / catalog核验，**未做restore演练**。

最终owned cleanup已完成：固定r30 fixture daemon与API26停止、精确隔离PG container停止、其空internal network移除。全部目录 / 镜像 / container / volume / 备份 / key / session与旧UNKNOWN / HELD保留，专用user manager未停止；回执`r8-final-private-backup-cleanup/cleanup-result.json`。该隔离轮次退场时尚未更新测试服务器常驻Cloud服务；已停止的临时入口不代表常驻Cloud服务已经启用。后续checker重评使用已有固定完整快照，不恢复模型 / SSH执行或创建新Task。其后C4常驻部署见[独立交付记录](CLOUD_GIT_DELIVERY_20261023.md)。

hypertest-one是用户明确允许中断的单人专用测试环境。C4已沿Git固定SHA构建 / 迁移 / 重启完成部署检查，不默认增加生产维护窗口、恢复演练或业务验收。正式迁移已顺延为0025 / 0026并接续管理0024，当前库已向前升级；原隔离DB迁移编号与source pins保持历史事实，不倒写旧数据库或验收记录。

source31仅修只读验收器与对应测试两文件，其他419份source30 payload逐字保留；archive SHA256 `751ef85fd850d2804b348a7a3ea603e3bfa5cda78d36c50bf9939a3af34843bf`、manifest `db105141570888fc751d4dbd702b6d95f0765405602c26e72ad5b72cd2f197ec`。独立静态审查确认：只增加一个精确build表达并联核完整SHA / import path / report；combined patch只接受声明的新测试与逐字相同child；baseline只收独立operator提供的固定Git原件 / commit / path / hash / count，新增AST方法仍须CASE / JSON / log完整覆盖，direct child、归属与失败闭集不变。

远端非root有限隔离unit已实际执行controller测试 **117 passed（0.90秒）**及两文件Ruff通过，pytest / Ruff日志SHA256为`57ba70afc9dc38f664b3d579fcd393e2b3a97f37e73ff146d34c4c367fdde33f` / `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`，checks observation SHA256 `5a9e983a81fb8f1e10bae0bcd92b26a2493ed891e7b6a123fcdc02a6e1207446`。只覆盖两个变更文件的有限验收语义，不等于717项重跑或SUT测试；无DB / API / 模型 / SSH / SDK启动。

随后独立显式的source31 **SNAPSHOT_REASSESSMENT对同v19固定快照实际strict PASS / failures=[]**。新报告`r8-source31-snapshot-reassessment-evidence/r8-v19-snapshot-source31/assessment.json`为2100字节 / SHA256 `0aa4ccff98848fc877f9e82274890ce3d7cc45d9f3b08aacbc4ee4fd26a94928`；observation为724字节 / SHA256 `1712db0b1569fa4b78facdc90c737d3bc54509cffc59fe56f3a9199272faa87a`。四输入为原完整GET / verified originals快照、原expectation及独立host从冻结Git对象 / 停后只读workspace逐字核得的417字节baseline与provenance，SHA256分别为`a6e7e6eb5be79c975dcbda6dfa87ab53b8806ec1297b07a710bc01ba889ec76a` / `d52166c6440141df818cfd39b098e82a166b343729110e4e5deeb16deb955dda`。19 CASE / Run / child直接引用与原件全部核对通过；`current_get_performed=false`，不是重新请求当前head，不启动API / DB / SDK / 模型 / SSH / SUT测试，不改canonical、旧expectation或旧assessment。两个有限unit均inactive / dead、PID0、cgroup empty。物理Worker source30、helper source29与只读checker source31身份分开，不升级为独立writer / legacy VERIFIED / Gate或全部P0退出。

最终host只读回执`source31-final-host-observation.json`为2335字节 / SHA256 `132a1a88af37b221d48ae697e211a12f33aa5fc908f9dff1f820d198231c15a4`：source31 checks / reassess、r8 Worker / replay、r30 sshd与API26六个owned unit均inactive / PID0、当前ControlGroup为空，原隔离PG ID为exited。原v19快照 / expectation / 旧NON_PASS / SSH专项报告 / 新PASS逐字摘要不变；本次观察没有服务变更、DB / API / 模型 / SSH调用或canonical写入。

## 可以审查的实现

| 六步流程 | 已加入的代码与入口 |
| --- | --- |
| 1. 项目资源 | 复用 Project；保存 SUT / framework Git 与环境元数据、版本化加密凭据。Web：`/projects/{projectId}/cloud` 的项目资源页签 |
| 2. 任务输入 | 创建 CloudTask 草稿，保存分支 / 完整 SHA / MR + base ref、PRD / 目标 / 流程、框架入口、资源修订、授权与累计预算 |
| 3. 解析与下发 | 独立 Worker 解析双仓并接受固定 SHA；任务页先显示原解析身份，再按原 resolution 下发。dispatch 不解析移动分支 |
| 4. Harness | 独立 Cloud Worker 使用官方 SDK client，通过 `sdk` profile 调用 runtime；每 Attempt 独立工作区 / home、lease / generation 和 namespace |
| 5. 产物 | 显式工作区 handoff manifest，经唯一 Worker broker 提交分析 / 设计 / CASE / 实现 / 报告修订；正式 REPORT checkpoint 持续回写，原 key 与固定版本完整读回 |
| 6. 执行与结果 | 原项目框架执行由 Agent 发起；保存原报告 / 日志 / Run / case actual 和 reported result，FAIL 与修订历史保留。完成仍要求明确 completion manifest |

已有受控fixture验收包括 **HTTPS Git 仓库、工作区内项目框架**与独立隔离fixture内的**固定SSH诊断专项**，source31对r8同v19固定快照strict重评通过。C4常驻部署已可供用户操作，未启动新模型 / SUT或代替用户验收。其余目标能力仍属于完整方案范围：

| 能力 | 当前支持情况 |
| --- | --- |
| DeepSeek root 使用官方 SDK | source-r18与source-r22两个Task分别完成受控六步；后者固定v17 COMPLETED / reported PASS、16资产 / Run1 / 原件4份，关联核对与本Task独立重放9项通过。每轮证据独立，不升级legacy VERIFIED或全部P0 |
| Codex 原生推理 / 文本贡献 | 代码默认关闭，C4服务器显式启用但保持idle；source-r18文本贡献与source-r22实际子分析原件分别接受。后者ROOT36 / CODEX5全HTTP200完整完成，native_ref / run_id及分析 / 设计引用已核验；来源为official-plugin-runtime-reported，非独立writer证明 |
| Codex 子代理文件 / 命令工具 | source-r23新Task的ANALYSIS / DESIGN直接引用当前子原件，source-r24对同v20严格PASS；实际框架8项只读重放通过。子贡献仍runtime-reported，非独立writer证明；source-r18 SIGTRAP、source-r21 RECOVERY和source-r22 transitive-only / NON_PASS历史保留 |
| Claude Code 外部子代理 | placeholder；未实现 / 未验收，不能由 Codex 路径推定支持 |
| SSH固定诊断 / 其他远端能力 | ADR-023默认关闭；source29合成transport与source30 Worker的r8 canonical专项PASS，source31对同v19快照strict重评PASS、旧source30 NON_PASS保留；取消 / 失联矩阵及真实staging未验收。CI、一般远端shell和Git写入仍不支持 |
| 精确旧会话恢复 | 仍阻塞；不会自动重放 prompt、恢复旧 shell 或创建替代 session |
| 常驻测试服务器Cloud服务更新 | C4固定Git已部署、schema26、五角色healthy与Cloud Worker active-idle；部署检查不等于用户验收。本轮无新模型 / SUT；Web步骤显示修正已按6d49单独部署，API / Worker / schema保持C4身份，见[交付记录](CLOUD_GIT_DELIVERY_20261023.md) |

## 服务端 API 与权限

API 主进程只管理输入、授权与持久化，不运行 SDK、Git 或框架命令。

- `GET /api/v1/cloud/capabilities`：声明配置支持范围，不探测模型登录或启动 runtime。
- `POST /api/v1/cloud/operations`：严格类型化管理操作，固定 `profile/project_id/operation_key/expected_version`；不接受外部 `cloud:work` 写入。
- `GET /api/v1/cloud/projects/{id}/configuration|credentials|tasks`：项目资源与任务元数据；凭据不返回原文。
- `GET /api/v1/cloud/projects/{id}/operations/{key}`：只查询原操作，不授权重发。
- `GET /api/v1/cloud/tasks/{id}?project_id=...&version=...&offset=...&limit=...`：固定接受版本分页原文。
- `GET /api/v1/cloud/tasks/{id}/summary`、`.../artifacts/{artifactId}`：当前投影及受控原件读取。
- `GET /api/v1/projects/{id}/task-directory`：Cloud / Local 只读类型化目录，写入仍分别归属原 profile。

项目管理使用独立 `cloud:configure`、`credential:manage`、`cloud:dispatch`、`cloud:control`、`cloud:read`；短期 `cloud:work` 仅由当前 fenced Worker 内部使用。根 / 子 Agent 不获得平台 writer token、Operator key 或数据库访问。未知写、失答或接受后读回失败只查询原 key 和原固定版本，不能换 key 重新 POST。固定接受版本读回与当前运行态分开：`summary` 返回当前 Attempt、解析运行状态与数据库观察时间；UI 仅在 Project / Task / Attempt / version 一致时使用该运行投影，版本前进则重新读取固定快照，不改写历史产物。凭据原回执按不可变 credential-version ID 与版本核验，后续授权轮换不应让原接受结果永久 UNKNOWN。

## Worker 运行前提

历史隔离环境按原编号完成依赖、向前迁移 `0023_cloud_tasks` 和运行基线验收；正式候选接续管理 `0024_local_task_binding`，依次迁移 `0025_cloud_tasks` → `0026_cloud_ssh_operations`，最终树迁移与测试服务器部署尚未执行。两个开关默认均为 false，关闭时 Worker 不领取任务、不构造模型 runtime：

```text
HYPERTEST_CLOUD_ENABLED=true
HYPERTEST_CLOUD_WORKER_ENABLED=true
```

在已有受保护的服务配置中，分别指定数据库连接、独立运行目录、凭据包装密钥文件和模型身份文件。主要配置名为：

```text
HYPERTEST_CLOUD_RUNTIME_ROOT
HYPERTEST_CLOUD_CREDENTIAL_KEY_FILE
HYPERTEST_CLOUD_MODEL_KEY_FILE
HYPERTEST_CLOUD_MODEL_BASE_URL
HYPERTEST_CLOUD_MODEL
HYPERTEST_CLOUD_MODEL_MAX_TOKENS
HYPERTEST_CLOUD_MODEL_MAX_REQUESTS
HYPERTEST_CLOUD_MODEL_REQUEST_COST_MICROUNITS
HYPERTEST_CLOUD_ATTEMPT_TIMEOUT_SECONDS
```

包装密钥与业务数据库分离；模型身份由云端预配，不复制本机 HOME、Codex / Claude 登录或 SSH 目录。密钥文件须私有，秘密不放命令参数、普通环境示例、提示词、仓库 URL 或产物。模型请求预留率默认 0 会阻止执行；缺省 `CONSERVATIVE_MICROUNITS` 要求能形成保守费用上限，不能用未知费率放行。另行批准的试点可冻结 `accounting_unit=REQUEST_CREDITS`，费率表示每次请求额度，不表示 USD / 供应商费用；Codex OAuth 仅接受该显式单位。旧任务不被迁移或改写。

固定官方 DeepSeek provider 实际使用 Anthropic Messages，默认 base 为 `https://api.deepseek.com/anthropic`，由 host broker 仅转发固定 `/v1/messages`、模型和受限文本 / thinking / 客户端工具，不回退 Chat Completions。Codex child 则使用单独的固定 Responses OAuth relay。真实认证始终留在 host，namespace 只有限定 socket 与 sentinel。普通秘密文件仅接受 root / 当前 UID 的 0400/0600；systemd LoadCredential 的 root:root0440 文件 / 0550 unit 目录例外要求当前 `CREDENTIALS_DIRECTORY` 精确匹配、readonly fs、无硬链接、exact ACL 仅 root / 当前服务 UID，其他 user / group / other 均无权。逐组件 NOFOLLOW、同 FD 校验 / 读取；该例外不等于普通文件允许 group-read。

运行基线要求 Linux、bubblewrap namespaces 和独立 Python 环境；隔离工作区只读挂载 SUT、可写框架工作区，禁止一般网络，通过宿主 Model Broker 限定模型访问。官方 runtime 的 native addon 需要私有可执行临时目录。早期一次性 Docker 沙箱探针因不能创建非特权 namespace 返回 **BLOCKED / NAMESPACE_SETUP_FAILED**（EPERM）；该默认 Docker 路径仍受阻，没有放宽主机权限或用普通进程替代沙箱。后续 **r7** 在专用非 root systemd RootDirectory、只读源码 / venv、cap0 / NnP、独立 cgroup（2 GiB / 0 swap / 256 pids）中，已通过同一生产 bubblewrap 的真实 SDK 无模型初始化 / 关闭（12.276 秒，峰值内存约 290.4 MiB）。这是独立部署 profile 的通过，不能覆盖 Docker 失败，也不含模型 / Git 网络或真实任务验收。精确前提见[隔离验收](../ops/deepseek/README.md)与[SDK 说明](DEEPSEEK_HARNESS_SDK.md)。

Worker 在领取任务之前还必须通过只读资源门禁：专用 cgroup v2 具有有限的聚合 `memory.max`、`memory.swap.max` 与 `pids.max`，有效 memory + swap 总上限不得超过 **4 GiB**，进程上限不得超过 **256**，并能从 `cgroup.procs` 核验当前 PID 归属。门禁不创建、修改或委托 cgroup；部署操作者须预先提供独立资源包络，不与生产服务共享。原source-r18的 `RLIMIT_AS=4 GiB` 限制的是单进程虚拟地址空间，不能代替物理 RSS / 聚合内存与进程数控制；配置缺失或无法核验即阻塞领取。后续native Codex profile的有限AS16GiB修正源码已冻结并独立只读审查，root-only仍4GiB，聚合内存 / swap / pids和任务预算不变。RUNNING / 私有prompt-intent分开记录配置AS、聚合准入上限和实际cgroup的memory / swap / pids，仅保留闭集数值、不含cgroup路径或环境；聚合准入上限4GiB不伪称现场物理额度，现场仍2GiB / 0swap / 256pids。source-r21所选回归已通过；其新真实Task已接受runtime-reported子文件原件，但后续typed资产引用遭拒，仍RECOVERY_REQUIRED / NOT_RUN。任务与旧source-r18成功分别登记。

具备以上独立准入后，Worker 启动入口为：

```bash
python -m hypertest.cloud --once
python -m hypertest.cloud
```

这两条是启动入口说明，不代表已运行真实模型或测试。API 不在请求中启动 Worker。关闭准入后，历史查询和 Local 同步应继续可用；活跃 / 未知 Attempt 仍须 fence、停止与逐项对账，不能靠关闭开关宣称已取消外部动作。

已新增可审阅的[服务准备模板](../ops/deepseek/README.md#生产启动配置准备未安装未验收)：基 unit、默认关闭 / 请求费率0的 env 示例，以及显式 Codex drop-in。它们**尚未安装、启动或通过生产验收**；下述真实临时unit仅验证服务文件启动准入，未启动长期Worker。基 unit 无 `[Install]` 且 `Restart=no`；包装 / 模型 / 可选 OAuth 的 leaf 统一为 `wrapping-key`、`deepseek-key`、`codex-oauth`，路径由当前 unit `%d` 与 `CREDENTIALS_DIRECTORY` 核对。`EnvironmentFile` 优先于 `Environment`，不得另行放入 credential path / 目录或 Codex 开关来覆盖模板；错配应阻塞启动。

该准备 profile 通过非空 `HYPERTEST_CLOUD_SERVICE_RELEASE_SHA256` 启用 `worker_admission`：`ExecStartPre` 和长期 Worker 首次导入数据库前只读核验 outer guard、只读固定 release、Python 3.12 / exact SDK双包、0700持久 runtime与严格凭据；每轮 `run_once` 前仅复核凭据和可选 OAuth全窗口时效，失败退出且不领取新任务。release manifest完整字节核对可信 SHA；其中 source archive / rootfs / venv摘要仍为 **OPERATOR_DEPLOYMENT_RECORD**，不是门禁递归重哈希整个部署或证明模型身份的声明。门禁不联系 DB / provider、不启动 SDK、不刷新 OAuth。source-r19 的445通过 / 1失败保留；测试替身修正后的source-r20已完成 admission / runtime / private-file / resource 所选 **66通过（4.65秒）**及全范围Ruff。本页完整reported PASS与独立框架关联仍对应 **source-r18**；后续source-r21子文件原件与拒绝恢复记录另列，不外推到长期服务准备代码。该配置默认空，不改变原 CLI、Local或现有生产服务。

source-r20另已完成真实服务文件准入：已审renderer SHA256 `40e8bbf9db60ccf03328918a3ae9e7287a08df22cf7d4a9cec69fa6508a91b72`仅生成固定临时 `hypertest-cloud-service-admission-r20.service` / Codex drop-in，沿用模板的真实 `ExecStartPre` doctor、`%d` / LoadCredential与rootfs，只将 `ExecStart`换为`/usr/bin/true`、`PrivateNetwork=yes`、RuntimeMax180秒。实际doctor **ADMITTED**，三类凭据仅验证可读 / OAuth本地时效，2GiB / 0swap / 256pids、cap0 / NnP均已核验；**无DB / SDK / 模型 / Task领取**。release manifest SHA256为 `f352d4ef96e8e285ba56b32f0a2164399e2e83be9596bedf6f154782dd62a498`，私有回执为 `service-admission-r20-start-result.json`。主控已精确停止并移除该唯一 `/run` 临时unit / drop-in、daemon-reload，证据保留、生产未触及；不保留可自启unit。该结果证明服务文件的启动准入与真实credential挂载配合，不证明长期Worker轮询、真实Task执行或生产已部署；native16的真实Task证据另列。

## 累计预算、handoff 与 Codex opt-in

claim 在任何 Git 前持久 `preparation_budget_reservation` 时间 hold；RUNNING 前，Worker 把含准备时间的完整截止、ROOT / 获准 CODEX 的请求次数与每次额度写入严格 `budget_reservation`。各 scope 共用剩余 Task 预算。原 hold 是保留上限，不能当实测用量；累计按 `max(observed,held)` 计入，lease 丢失、取消、UNKNOWN 与人工对账不返还。只有整 namespace 已停、所有 broker 关闭 / join 且无在途请求，当前 fenced Worker 才提交相同单位和完整 scope 请求计数的结算，保存 SETTLED 与原 hold 历史；缺少证据继续 HELD。预算 / 进程观察不接受 Agent 自报。终态、结算、fencing 同事务接受，数据库终态不可变约束保留。

模型可读契约由 `hypertest.cloud.handoff_contract` 从实际 typed schema 派生，给出完整 payload 与 receipt ID 用法。source-r22再明确Artifact UUID只用于artifact_id，AssetRevision依赖只取先前ACCEPTED SUBMIT_ASSETS的assets[].id，首批referenced_asset_ids=[]；原文→ANALYSIS→DESIGN的三步样例使用独立ID并核对字节 / SHA，结构UUID不能代替DB身份核验；原子发布 `.hypertest-cloud/ready/KEY.json` 后先等待原件 / CASE revision 的接受回执，再发布依赖引用。Worker 负责平台 key / expected_version / auth、上传字节及主机观察。SDK idle 不是 COMPLETE；真实失败发生时保留原报告和修订，不要求制造首轮 FAIL。

契约补充 CASE.details 必需键、正文 / Artifact 条件、同批复合唯一与 REPORT checkpoint、Run 时间 / 缺失观察说明及引用约束，不能假定 Pydantic model validators 都会自动出现在 JSON Schema。仅 typed 预检失败且尚未冻结 / 提交时，允许本地 `LOCAL_REJECTED` 反馈，目录 `.hypertest-cloud/rejections/<sha256(handoff-key)>.json`；只含固定错误类型 / schema 路径、原件哈希与 `platform_operation_submitted=false`，不含正文、秘密或任意输入 key。这不是平台 ACK / 已接受资产，不推进业务版本；修正用新 handoff key，原拒绝原件保留。SENT / UNKNOWN / 已冻结、秘密 / 安全或平台 HTTP 错误不能改走这条路径，仍 GET 原 key，不自动重投。

Codex opt-in 配置仍默认关闭，独立使用：

```text
HYPERTEST_CLOUD_CODEX_ENABLED
HYPERTEST_CLOUD_CODEX_PAYLOAD
HYPERTEST_CLOUD_CODEX_PAYLOAD_SHA256
HYPERTEST_CLOUD_CODEX_OAUTH_FILE
HYPERTEST_CLOUD_CODEX_MODEL
HYPERTEST_CLOUD_CODEX_MAX_REQUESTS
HYPERTEST_CLOUD_CODEX_REQUEST_CREDITS
```

固定官方 Harness source `687f282e8625c6b8d11ff58211a90524be2e4317`、`@deepseek-ai/dsh-subagent-codex@0.2.1-rc.2` 与 `@openai/codex@0.153.4`；预装 Node / npm lock / 全 payload 均核对可信 manifest 摘要，当前冻结 payload manifest 为 `412df5f55ec16ad37ad63ac9dff9f4217c4a0144db08ab5045709c1f6dce0d77`。此摘要只标识该 payload，不覆盖整个共享源码，也不证明真实模型或 CLI 已执行。host OAuth 不刷新 / 不导入本机账户，过期拒绝。官方 provider 使用 app-server；shim 仅将精确 argv 映射到受控 Node，不另写 provider。

官方 plugin 通过有界私有 UDS 的序号 / ACK 传 READY、DELEGATION、CLOSED。READY 只是组件加载；`native_ref` 是官方工具的 external activation child UUID，另有官方 run UUID，不是 Codex 产品 thread ID，也不能恢复原 thread。Agent 只提供责任与资产，Worker 核对 start / terminal 后注入状态；终态须观察通道已关闭、全部 child 终态、每个 child 的父任务贡献回执、整 namespace 停止和所有 broker drain。来源仍为 runtime-reported，不升独立执行证明。原生无模型记录 `native-probe-r7` 的组件通过、host CODEX 单请求与后来真实 native 推理 / 平台接受分别登记；source-r18的 native_ref 与产物引用已按固定接受版本完成独立语义核对，该Task子工具SIGTRAP历史保留；后续native16已观察runtime-reported文件贡献，但该轮未形成typed资产 / delegation接受链。

运行诊断只消费当前 root 的实时 SDK 标量通知，不读历史正文 / 工具参数 / 结果文本 / 思考。SDK driver 最多发出**前 512 条 runtime 活动**，Worker 再保留**已收到活动的最后 64 条**，并对固定类别计数；达到上限后不继续采集活动。因此 `activity_counts` 不是全程总数，`recent_activity` 不是整个运行最终 64 条，未观察事件不代表未发生。单独保存的 `idle_finish_reason` 不受该活动窗口替代，但仍是 runtime-reported 结束原因，不是平台 Task 终态、框架 exit code 或测试 PASS；停止 / drain 和 handoff / 读回证明保持独立。

专用六步 API 验收控制器为 `ops/deepseek/cloud_acceptance.py`，只用 HTTP，不加载 SDK、不运行框架：`prepare` 创建独立 Project / 双角色公共 sampleproject 仓库 / 新 Task 并请求解析；独立 Worker `--once` 完成解析后，`dispatch` 核对接受版本 / 双 SHA 后下发；另一次 Worker `--once` 执行，`readback` 仅 GET 原 key、固定版本和全部原件字节。Root 与 Codex 分别新 Task / 私有 state；SENT / UNKNOWN / NOT_FOUND 不重 POST。Operator 从受保护文件读取，完整非秘密请求 / key / version 在写前持久化。公共 fixture 用实际 unittest 与只读 SUT，不创建模拟 SessionTask、不修改生产 DB；控制器输出不推导模型成功或测试 PASS。

失败恢复新增显式控制器路径：`reconcile` 使用独立账本与操作者私有 host proof，严格核对原目标 / version、旧 owner fence、整树停止与无未决平台 / 获准外部测试操作；固定协调为 FAILED，声明模型 drain 未观察、KEEP_HELD，接受版本完整读回再核对原完整 hold / preparation hold 未变。`start-followup` 仅在源终态和原平台写完整读回后，复用同 Project / 配置 / 双 SHA，以 related_task_id、新授权预算和独立账本创建 / 请求解析关联 Task；不自动 dispatch、不改原 Task、旧请求或 hold。上游模型完成未知仍保留预算，不借新任务重发已知未决外部动作。

## Web 接入

项目页的云端入口保留现有 Ant Design 工作台。资源、草稿、解析 SHA / dispatch、混合任务目录、原报告与每轮结果分开显示；完成不显示成测试 PASS。取消控件只发送固定 `OPERATOR_REQUESTED_CANCELLATION` 原因；受控 API 路径可在包装密钥暂不可用时 fence 当前写权，其他输入仍保持秘密扫描。客户端不在 503 或 UNKNOWN 后改 key 重发。私钥用隐藏输入或私有文件读取，首次提交时清空；浏览器 journal 只保留原 key、版本、状态与非秘密摘要，不持久保存请求正文、PRD 或秘密。该元数据目前使用 `sessionStorage`，只覆盖同一标签页刷新后的查询 / 对账；关闭标签页后的原 key 保全、跨标签页唯一写流和持久恢复账本尚未实现。因此不能宣称 Web 生产 journal 可靠性已完成。未决请求须保留原 key，不以关闭标签页或新开标签页代替对账；后续需要有并发协调的持久账本，不能仅改为无锁 `localStorage`。

浏览器仅访问 `/api/cloud/*` BFF。部署使用以下服务端配置，均不得使用 `NEXT_PUBLIC_`：

```text
HYPERTEST_CLOUD_WEB_ENABLED=true
HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE
HYPERTEST_CLOUD_WEB_OPERATOR_KEY
HYPERTEST_CLOUD_API_ORIGIN
HYPERTEST_CLOUD_WEB_ORIGIN
```

优先使用私有 key file；只有其未配置时才使用服务端 key 值。`HYPERTEST_CLOUD_API_ORIGIN` 优先于原 `HYPERTEST_API_ORIGIN`，须指向可信 HTTPS API，不能照用生产容器的 `http://api:8000`。BFF 不下发 Operator key，保留同源写入检查和固定路径 allowlist；这里仍是既有可信单操作者 / VPN 边界，不宣称新增用户登录或多租户隔离。

反向代理后的浏览器站点可能与 Next 内部监听地址不同；服务端用 `HYPERTEST_CLOUD_WEB_ORIGIN` 固定可信站点的规范 `http(s)://host[:port]`，不含用户信息、路径、查询或 fragment，生产使用实际可信 HTTPS 站点。POST 的 `Origin` 必须与该配置严格匹配，跨站或缺少 Origin 仍拒绝；不依赖 Referer 或客户端 `X-Forwarded-*` 建立信任。未配置时保留直接访问的 `request.nextUrl.origin` 检查；配置无效则 503 闭锁。Cloud API origin 与浏览器 Web origin 是两个独立配置。

只有独立验收可使用显式 loopback 例外，并令 BFF 与 API 共享网络命名空间，经 `127.0.0.1` 访问且不新发布端口。该例外不授权修改生产 TLS、VPN 白名单或 SSH 访问规则。

## 当前增量验收

本阶段独立 PostgreSQL 已完成 `0023_cloud_tasks` 向前迁移，未使用生产数据库。各次失败与后续检查保留独立身份：

- 预算 / handoff / controller / CloudTask 的 r2：**41 passed / 1 failed（42 项，36.37 秒）**。失败为终态第一次 autoflush 后再写结算 / fencing，被终态不可变 trigger 拒绝；修复改为结算完成后再设置终态并一次 fence，没有放松数据库 trigger，回归断言同时核对 generation / 租约清空和原 RUNNING 固定快照仍 HELD。
- r11 整合源码归档 **391 文件**，archive SHA256 `b158dda44988285187bb45cefbec639f786abe82c2856ece8ead92d8dd4ec2d0`。实际所选 Cloud / SDK 探针 / SessionTask 与 MCP / TaskSyncCore **21 个测试文件，370 passed / 2 条既有 warnings（57.59 秒）**；包括上述预算修复、精确 handoff、本地 typed 纠错、人工协调与关联 Task 控制器。它不表示全仓测试，也不覆盖后续实时工作树。
- r11 Ruff 仅发现 worker diagnostics 测试 import 排序；机械修正后的 r12 归档为 `9b573462a838579782a897452a17fc6ca988474c90884ac9555887c8905000a7`，远端 Ruff **全部通过**。r11 的 370 项结果与 r12 的格式增量分别保留原快照身份，不能外推后续源码均已回归。
- Docker 默认 namespace 失败与 r7 非 root systemd / 同生产 bubblewrap 的完整无模型通过分别保留，不能互相覆盖。原生无模型记录 `native-probe-r7` 为 **OBSERVED**：`provider_registered`、`tool_registered`、`subprocess_shim`、`node_available` 均为 true，官方初始化、会话创建及干净关闭已观察；该探针无 OAuth 请求、无 child、无推理。当时仅核验云端 OAuth 的安全读取 / 时效，之后的 host 认证与模型验证另记如下，不能倒填为该无模型探针已推理。
- r14 官方 SDK 工具探针为 **status=OBSERVED，scope=SDK_FIXED_PRINTF_ONLY**：通过真实 Agent 的 `ctx.tools.execute` 执行一次固定 printf，在 SDK 原有 **workspace-write + ask** 政策下注册 / 执行成功、marker 匹配且无错误，namespace 已停止。没有模型 prompt、鉴权、真实 Task、SUT 或框架执行；独立空 workspace / home 内未启动模型 broker。nested user namespace / bubblewrap 与 sh / bash 也已分别成功，未放宽隔离。它排除了该受控 profile 下 SDK shell 普遍不可用的假设，不能证明模型实际调用过工具或任意项目工具权限均可用。
- r15 的 Cloud / SDK / Local SessionTask 与 MCP / TaskSyncCore 所选 **23 个测试文件，420 passed / 2 条既有 SQLAlchemy warnings（67.14 秒）**。其独立来源为 `source-r15`；私有 `source-r15.manifest.json` 的 SHA256 为 `3f2d7295de8fd3f2c74ef2698a10cc112c2ff63331a2a66151179ab9a99401aa`（源码清单摘要，不是 archive 摘要）。该所选范围与 r11 分别保留，不能称全仓或真实模型验收。
- r16 的 prompt 所选回归 **47 passed（5.23 秒）**，远端 Ruff 对 `src`、`tests`、`alembic`、`ops/deepseek` **全部通过**。r16 snapshot archive SHA256 为 `43525ba8252cff0e0e9707d995e47eea817757eb5915917447050d9fbd34b974`；这条 prompt 增量与 r15 的 420 项不是同一轮全范围重跑，不把两次计数拼成额外通过项。
- r17 新增 host 诊断投影所选回归 **36 passed（6.27 秒）**，Ruff 全部通过；archive SHA256 为 `5db9e59ef97429d03880bff33599857c41e2c4f44245a7877bcafc067f9bc27c`。该范围只按实际所选检查登记，不替代 r15 / r16 或真实任务验收。
- r18 Cloud 模型配置相关所选回归 **60 passed（6.76 秒）**，Ruff 对 `src/tests/alembic/ops/deepseek` 全部通过；`source-r18` 快照 SHA256 为 `4e66b81e271f8ae97dc72d28656aeb89b0ac1ccf83f0f6dd49c4dee4a597624d`。Cloud 的默认 `cloud_codex_model` 改为现场目录支持、已由独立 host 请求验证的 `gpt-5.6-sol`；legacy `codex_model=None`、Cloud / Worker 默认关闭均保留，不将 Cloud 模型默认迁移应用于旧执行路径。
- source-r19 含服务启动准备的所选回归实际为 **445 passed / 1 failed（74.16秒）**，Ruff 全部通过；archive SHA256 为 `fe5bca6dccd9e811ec0a76c29e2f3172d3191c53d8069dd9efa2bb1e0f4bc122`。失败在新增 `test_codex_opt_in_requires_payload_and_real_private_oauth_freshness`：用于断言逐轮凭据复核不重哈希 payload 的测试替身未恢复，后续完整 admission 检查仍命中该替身；不是生产 OAuth 过期检查逻辑失败。该轮失败保留，不能记为446项通过。
- 仅恢复测试替身的 source-r20 archive SHA256 为 `9c092e4c3851d8b456656729ff18d20713c0e78bd9df795fe972909810d6d131`；admission / runtime / private-file / resource 所选回归已 **66 passed（4.65秒）**，Ruff全部通过。这是修正后的实际所选复验，不是原446项范围全量重跑，也不是服务安装 / 模型认证 / 真实Task验收。
- source-r21将native16修正的四文件overlay纳入402文件archive，SHA256为 `fb2e28357620e044b21e77d9e286876b10da3b2ec78b3e8ec7a16f02b1672be4`；远端所选 **29文件、535 passed / 1 skipped / 86 warnings（51.44秒）**，Ruff全部通过。86条为既有 `session_tasks.py:199` 的SQLAlchemy DISTINCT ON deprecation；跳过项原因未独立核对，不计入通过。私有回执为 `source-r21-validation.json`，pytest日志SHA256 `93840f4eb29f6b262e5064c4a0eceda0923f20c86c1e1183bf5c9afeb754d04a`，Ruff日志SHA256 `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18`。所选回归通过不表示新真实Task / 子文件工具成功。

source-r22仅替换上述source-r21中的 `handoff_contract.py` 与其测试，其他400文件保持原字节，共402文件；archive SHA256为 `6d27ec52689babd39c54916784931a168615de6122e54f495c77d60850c27dfe`、manifest SHA256为 `50feae7a5fd2c80c94e3dd4f51f89c27b58fc0f11c6aef730fc33ed64289fa4f`。远端针对contract / rejections / runtime / delegation / controller / TaskSyncCore / SessionTask MCP的 **7文件、169 passed（15.39秒）**，两处变更文件Ruff通过；pytest日志SHA256为 `956cdcdd8187874bd420f42a484150ba6f94ed43e6805f779545da4045b1586c`。该轮澄清Artifact / AssetRevision身份及顺序样例，不放宽DB验证、HTTP拒绝恢复或原key语义，不冒称535项全量重跑或新真实Task成功。

对本地r21清单的独立只读核对：`source-r21.manifest.json` SHA256为 `b686c83bb4ea87bba7ec8c6c338a290ae2caddcd24fd6d2b3a362c677f08c321`（清单摘要，不同于archive），采集时402项中395项与共享树匹配、7项仅文档不同、没有缺失。Cloud关键80项源码 / SDK / Cloud API、application、domain / migration / config / main / pyproject / lock / ops / tests全部匹配且无当前关键文件遗漏。文档差异为本次后续更新的4份Cloud文档，及其他owner在AGENTS / domain / protocol中的共享文档更新；未并入该快照、不推定为Cloud代码回归或回滚其他owner修改。该核对仅声明采集时状态，不宣称整个动态共享树始终等于受测快照。

固定 CLI 无模型沙箱探针另已完成4项：outer printf、固定 `codex-cli 0.153.4` 版本、官方 `codex sandbox` printf，以及空工作区固定文件读写均成功。已审脚本 SHA256 为 `fe92eae3ca906866841572a2e50db77dbc9a5d849e07e1e004372d1285abf5f2`，使用固定只读 payload、新空 HOME / CODEX_HOME与既有 outer / namespace、AS4 GiB / 聚合2 GiB / 0swap / 256pids，没有 SDK / 模型 / 认证 / Task / 真实仓库或 SUT，未放宽权限。其 scope 为 **FIXED_OFFICIAL_CODEX_SANDBOX_WITHOUT_MODEL / NOT_RUN**，不能据此证明模型 turn / app-server / code-mode-host 中的子工具；该探针单独不能定位正式任务披露的 SIGTRAP，也不能认定 namespace 普遍不可用或 OAuth 失效，后续专用定位结果如下。

随后无模型执行路径探针（脚本 SHA256 `39145ce4d7ae60e528c0658a30102a9eb2b6ca25f7fb3e0618cca21654993179`）在每个case独立、相同AS4GiB / 聚合2GiB / 0swap / 256pids的namespace内诊断：**APPSERVER初始化、ephemeral thread/start和固定sandboxed command/exec均成功**，未发送turn；**CODE_MODE的hello / session/open成功，在EXECUTE阶段EOF，实际return_code=-5 / SIGTRAP**，stderr仅投影99字节与闭集MEMORY / V8类别，两namespace均已停止。没有读取认证或调用模型 / 平台；`DIAGNOSED`只说明拿到诊断，不表示子工具能力通过。该定位缩小了失败路径，错误类别仍不足以直接判定AS、物理内存或namespace根因。

已审临时副本 `probe_native_codex_address_space.py`（SHA256 `0e6e122fc1ffd5aef3e1f105bdd85e24d2f87df8eaed02c96309b34c5febb546`）的单变量对照已实际完成：仅对CODE_MODE分别设置有限RLIMIT_AS=4 / 8 / 16GiB、每档新namespace；IPC / text source / V8 flags逐字不变，物理cgroup精准2GiB / 0swap / 256pids、cap0 / NnP / payload / 隔离权限均不变，三档全部停止确认。**4 / 8GiB均在EXECUTE阶段实际-5 / SIGTRAP，stderr99字节 / MEMORY、V8；16GiB的实际soft / hard均17179869184，cell_started / cell_result / marker均true，SHUTDOWN后exit0、stderr0。**这支持该受控profile的V8有限地址空间兼容性因果，不能归为OAuth失效或namespace权限故障；虚拟地址额度不等于RSS / 物理内存。该探针只执行无delegate的固定纯text，仍为NOT_RUN / native_agent_tool_execution NOT_PROVEN，不代表正式子代理文件 / 命令工具已通过。正式native profile的最小调整与新真实Task验收分开登记，不改旧Task结果或HELD历史。

真实 DeepSeek 模型连通探针观察到 **HTTP 200 两次、完整响应两次、固定 marker 原件正确**；随后达到两次请求上限，SDK idle 的 `finish_reason=error`，停止 / drain 观察成立。它证明连通 / marker 与清理，`sdk_turn_succeeded=false`、`test_result=NOT_RUN`，不为获得成功标记增加请求或自动重跑。早期首行读取就提前停止、零模型请求的 r5 探针读取问题保留为探针失败，不冒充供应商失败；更早 noexec、namespace 与 READY / close 失败也保留原记录。

首个真实 RootTask `01a16368-a113-78c0-b6f2-a46496e3e0b2` 实际运行 **86 秒 / 14 次模型请求**。唯一 ready 提案为 SUBMIT_ASSETS，其中 CASE.details 缺 typed 必需字段；没有平台接受的 Agent 资产、Run 或 handoff 回执，不能称步骤 5 / 6 已完成。原状态为 v6 RECOVERY_REQUIRED / NOT_RUN。操作者实际核对旧 Worker unit / cgroup 已停止、原平台写完整读回、未准入远端 SUT / SSH / CI / 一般网络后，独立冻结 host proof；`reconcile` 已接受并完整读回 **v7 FAILED / NOT_RUN**，原完整预算 hold 和 preparation hold 两个值均保持 **HELD**。模型上游完成未知，未伪称 drain 或释放额度。这次是任务未交付，不是框架用例 FAIL，也没有制造 FAIL→PASS 证据。

后续明确创建同 Project `01a16368-a010-7416-99b1-8d22f90bb4e6` 的关联 Task `01a163a0-d1db-7031-bd0b-c3e362b1d7dc`，源为上述失败 Task，复用同配置；公共 sampleproject 的 SUT / framework 两角色冻结 SHA 均为 `621e4974ca25ce531773def586ba3ed8e736b3fc`。新授权 / REQUEST_CREDITS 预算、state `root-followup.json` 与原件分离；解析已接受，dispatch 接受 **v4**，Attempt `01a163a2-2d3f-7996-9cd7-4a5b808919db` 由 r11 Worker 独立执行 **76 秒**，观察到 **6 次 DeepSeek HTTP 200 完整响应和 SDK 干净 CLOSE**，实际 namespace 停止 / broker drain 均已观察。任务现为 **v6 RECOVERY_REQUIRED / NOT_RUN，EXPLICIT_HANDOFF_MISSING**；没有 ready 文件、测试新增文件、接受产物或 Run。这仍是任务未交付，不能把 HTTP、idle 或关闭成功当步骤 5 / 6 成功。

该次只从官方派生 projection cache 数值确认最后 step=6、outputTokens=4096；没有保存可用的 turn 结束原因。官方 loop 的 maxTokens 是逐请求输出上限，达到上限可终止 turn；但数值达到 4096 只是截断线索，不能据此认定 `max-tokens` 根因。官方 loop 没有默认六次 step 上限，默认五次请求重试也不足以仅凭总请求数确认发生。cache 不保存 root reason/code，llmRetry 在 turn/end 清空；未读取原始会话正文 / 推理、未重开 SDK 或重放该 Task。后续改用明确新 Codex Task / 新预算，不重新打开旧 Attempt、不改原 key、失败和 HELD 历史，也不替代原未知操作对账。

首次新 Codex Task `01a163c2-906d-7b5a-a638-661c09619a1a` / Attempt `01a163c5-2661-77b4-8b49-8f134672f760` 已 dispatch v4，但 `native-codex-r1` 在 prompt 前因 **MODEL_KEY_UNAVAILABLE** 结束。精确原因是 Worker 配置引用 credential leaf `deepseek-key`，实际 LoadCredential 却命名为 `model-key`；这是启动配置错误，不是模型或 Codex 拒绝。固定读回为 **v5 FAILED / NOT_RUN**，scope 列表为空、prompt-intent 不存在，没有 SDK / 模型请求 / child 执行，不标成 RECOVERY 或委派失败。随后 `keyless-credential-probe-r3` 在同专用账户 / rootfs 下使用正确 `LoadCredential=deepseek-key`，已通过严格 reader 安全读取 DeepSeek key 与云端 Codex OAuth，均只输出 true，不输出值、不发模型请求；可读仍不证明上游接受认证。

新独立关联 Task `01a163cc-9046-7c3c-a952-c3f5fded0e3b` / Attempt `01a163ce-777d-76c5-a7cd-317e99e4a9d3` 使用同 Project / 配置 / 双 SHA、新 state 和授权预算；独立 unit `native-codex-r2` 使用上述 r16 源码，Root 逐请求输出 cap=16384、ROOT 最多 **20** 请求 / CODEX 最多8请求、900秒，不能将后续计划的48次 ROOT 上限写回这一轮。claim 前严格核对包装密钥 / DeepSeek / Codex OAuth 三个 credential path 与统一 reader，真实身份只在 host LoadCredential。该 Task 已固定读回 **v11 RECOVERY_REQUIRED / NOT_RUN**：ROOT 观察到 **20次 HTTP 200 完整响应**，CODEX 为 **3次请求 / 0成功**；平台接受了 **5次 UPLOAD_ARTIFACT**，五份原件均完成全部字节 / SHA256 读回，但 **typed assets=0、runs=0、delegations=0**。原件上传接受证明传输与保存，尚未形成测试分析 / CASE / 实现资产、正式 Run 或成功委派，不能称完整交付。namespace 已停止，所有 broker closed / drained、inflight=0；停止 / drain 不将任务状态、测试结果或原 hold 自动改为完成 / PASS / SETTLED。

独立 host CODEX 排障保留了两次针对旧 `gpt-5.4` 的有界请求：均 HTTP400，错误只投影固定词 `account/model/supported`。随后现场只读 GET 模型目录，以 `client_version=0.153.4` 得到 HTTP200；当前账户列表没有旧选择，包含 `gpt-5.6-sol`。`hostprobe-r3` 对 **gpt-5.6-sol** 的单次请求观察到 **HTTP200、response.completed、固定 marker=true**，证明当前云端 OAuth 与该模型在受控 host 协议路径可用。依据为本轮现场目录 / 原请求回执，不推定其他账户或任意模型可用；host 探针没有走原生 provider / CLI 委派，不计入 Task 的正式 delegation、Run 或平台测试 PASS。

独立只读框架重放已执行：固定上述旧 Attempt 的 sampleproject / unittest，原 workspace 在外层 unit 与内层 namespace 均只读，采用新空 home / 私有证据目录、无 LoadCredential / SDK / 模型 / 平台 Task 写。实际 **17项 unittest 通过，exit=0，1.18秒**；双仓 HEAD 均为 `621e4974ca25ce531773def586ba3ed8e736b3fc`，SUT clean，框架源树清单 before / after SHA256 同为 `579b7fd8ee86f34006d416f517f40d6f3e4e76eb7206c007a4c52d0b96c298b3`，namespace stopped=true。它证明这次固定框架重放实际可运行，仍为 **UNVERIFIED / Gate NOT_EVALUATED**，不生成或补写原 Task 正式 Run / PASS。已接受 UPLOAD 原件 `test_add_one_boundaries.py` 的 SHA256 为 `4e4bcf1958739f6a6be7928f735962858b86e74c61cbc615e182d34cc1b5e684`；上传原件、固定接受版本原文与实际重放文件的三方精确比对现已通过，私有回执为 `accepted-upload-linkage.json`。这证明该上传文件的精确关联；旧 Task 没有 typed IMPLEMENTATION 资产接受回执，仍不能称 accepted Implementation。

后续明确创建同 Project / 配置 / 固定双 SHA 的关联 Task `01a163df-8109-79fe-ae2d-562ce8da1269` / Attempt `01a163e1-2d84-72d1-a31a-60cdffe944d0`，dispatch v4 接受后由独立 `native-codex-r3` unit 执行；使用上述 r18 源码、ROOT48 / CODEX8 上限、总预算64 REQUEST_CREDITS、900秒、Root输出 cap=16384 和 `gpt-5.6-sol`。该 Task 已完成**固定 v14 全部分页与两份原件完整读回：COMPLETED / reported PASS，assets=15、runs=1、delegations=1、originals_verified=2**。其中 originals_verified 仅表示原件字节 / 摘要读回，不是 legacy VERIFIED Evidence。host 实际观察 **ROOT27 / CODEX7 请求均 HTTP200 且完整结束、0 refusal / transport failure**；namespace stopped、所有 broker closed / drained、inflight=0，SDK root27step 的结束原因为 completed，native channel 干净关闭。它证明本轮真实委派推理与平台接受的完成 / reported PASS，不能改写先前 Task 的失败、原 key 或 HELD 历史。

已对授权的固定接受读回 `codex-supported-model.readback.json` 做独立语义审查（文件 SHA256 `a31beed917ea0752c54611a5b019c88d76847a6df668f42c3afa09b12899d425`），未读取 SDK 会话或隐藏推理：

- 15条资产为 ANALYSIS1 / DESIGN1 / CASE8 / IMPLEMENTATION1 / REPORT4。8个 RunCase 逐一引用这8个唯一 CASE revision，actual均非空、reported PASS；设计时 CASE 修订的 NOT_RUN / Not executed 原值保留，执行 actual 位于独立 RunCase，不重写设计历史。Run 的原日志为 **9 tests / 9条 ok / OK**，包含8个新增用例和1个原基线。
- IMPLEMENTATION `01a163e5-1ed5-78c1-b68c-88e0d18f583f` 引用完整新文件原件 `01a163e4-d360-746c-b22c-56015ef1f363`：1245字节，SHA256 `e248a0eebc06f2f5c08126fb6a6bea57dede61a242f89262aaf245ce6d76d9d5`；正文 Python 块与上传字节逐字相同。仅新增 untracked `tests/test_add_one_boundaries.py`、tracked dirty为空，提供完整原件与重建元数据，不缺额外 tracked patch。Run `01a163e5-3fe5-71b7-9943-f8138bd9677b` 的固定 SHA / 入口 / Agent自报 tree digest 与该资产记录一致，原报告1078字节、SHA256 `a531dd280e6137d72f22239106fac4531158a15eec34f6cb0c871ff775cf63ce`；两份原件长度 / 摘要均匹配接受记录。实际文件的独立关联结果另见下文，不将 Agent tree digest 当作宿主独立证明。
- delegation 的 `native_ref=49ba4d71-e8e6-4294-89ec-a82dfe62ab0e`、官方 `run_id=230364df-4829-4de9-b3c2-cbb58259b8b5` 与本 Task / Attempt一致，2个 accepted asset refs 精确指向 ANALYSIS `01a163e4-64ce-7ca7-a21d-e43fd5c7ac0a` 和 DESIGN `01a163e4-9ad0-7257-add4-d02564cc3811`。来源为 official-plugin-runtime-reported、`independent_execution_proof=false`。责任、分析和最终报告共同披露：子 Codex 工作区工具反复 SIGTRAP，未写 `codex_analysis.md`、未改测试 / 执行套件，仅在 closing message 给出边界建议；Root自行读SUT、设计、实现、运行和交付。delegation COMPLETED 表示该原生运行终态与文本贡献被接受，不能称子文件生成或子命令工具通过。
- completion manifest 的12个唯一 required资产为分析1 / 设计1 / CASE8 / 实现1 / final REPORT1，全部存在；final REPORT 的11个引用均同 Task 且有效，final_report_revision正确、pending keys为空，停止 / 外部协调观察为true。预算原预留 **56 REQUEST_CREDITS ≤ Task64** 保留，当前 fenced Worker已接受 **SETTLED34=27ROOT+7CODEX、234秒**，preparation hold 同为SETTLED，lease已清空、generation2。该额度不是USD或供应商账单；旧任务的HELD历史保持原样。

本轮独立只读框架重放现已完成：使用已审脚本 SHA256 `45806252f325ba11dd84275c72fffc8110e8fdadf839ff51f9b1af0906ec3c42`，仅将硬编码 Attempt ID 换成当前已停止的 Attempt，保持双层只读原 workspace、新空 home、无 LoadCredential / SDK / 模型 / Task 写与有限资源边界。实际 **9项 unittest 通过（8个新增用例 + 1个基线，exit=0，1.233808秒）**；双 HEAD 仍为固定 SHA，SUT clean、source_tree_unchanged、namespace stopped均为true。宿主清单 tree SHA256为 `b526ba8db4c938195a880192de28ebf495b3a3443b476d930828559221e1cabc`；Run中 Agent自报 `execution.test_tree_digest=a825eecfe99f4f183c77c7f5cc52c496850603233d891627eb5322acb306dd6c` 未规定与宿主相同的规范算法，两者不等同，也不据其不同认定源码变化。

实现关联已由操作者独立完成：接受上传原件、固定接受版本原文字节、实际重放文件三方精确匹配上述 `e248a0ee…d6d9d5`，并核对 IMPLEMENTATION 资产的原件引用。Git porcelain 原始状态字节 / 摘要确认只有该一份 untracked 新测试文件，没有其他 tracked 修改；私有回执为 `framework-replay-evidence/replay-supported-r18/accepted-implementation-linkage.json`。这补充了本轮真实框架可运行与接受实现的精确关联，未新增 / 改写平台 Run 或 reported PASS，重放本身仍为 **UNVERIFIED / Gate NOT_EVALUATED**；也不将旧 Task 的17项结果转移到本轮。

因此当前可验收的是正式平台任务 / 资产 / Run / case原文与引用、真实 native 推理和文本贡献，以及本轮独立重放 / 实现关联；**子代理文件 / 命令能力仍保留 BLOCKED 的正式任务记录**。有限AS兼容性已用上述无模型单变量对照定位；下述新native16 Task观察到runtime-reported子文件恢复，完整typed交付仍因引用错误未通过，不放宽namespace权限或实际聚合内存。准备阶段 runtime_metadata 的静态 observed=false 标志不覆盖后续正式 delegation / 终态记录，也不单独证明当前动态能力。当前不称 legacy VERIFIED、Gate已评估或全部 P0 退出；Claude 仍为 placeholder。

### native16新Task：子文件原件已接受，资产引用拒绝后保持恢复态

source-r21真实执行的 Task `01a16539-e3bd-72e9-b7e3-e66155fbaee6` / Attempt `01a16540-aa01-7b4c-ac8f-dcf16d9fd9a8`使用同Project / 固定双SHA、ROOT48 / CODEX8上限、64 REQUEST_CREDITS、900秒、16K输出及 `gpt-5.6-sol`。固定完整读回为 **v7 RECOVERY_REQUIRED / NOT_RUN，REPORT_RECONCILIATION_PENDING**；这不是终态、框架FAIL或任务完成。接受原件1份，**typed assets / runs / delegations均0**。已授权读回 `codex-address-profile.readback.json` 的SHA256为 `729999aece90f5b88c80dd09ff1b5a0fc08350bdd1227559453c12c52461b135`。

- host观察到 **ROOT16 / CODEX5请求均HTTP200完整结束、0 refusal / transport failure**；namespace stopped、所有broker closed / drained、inflight0。实际AS为16GiB，cgroup仍精准2GiB / 0swap / 256pids；没有放宽权限或物理额度。
- 已接受Artifact `01a16542-f633-7f90-8cd8-792415be2b44` 的 `codex_analysis.md`为 **4642字节**，原文字节与SHA256 `e0b5c5d5114143700b088a60413027f3f53bf9ce886134bd5b3c23913234838d`已完整核验。正文列出固定SUT与framework三份源码、字节 / hash、实际只读AST检查命令、exit0、12类边界设计，明确未运行正式unittest套件。结合真实native推理，这支持**runtime-reported子文件 / 只读检查贡献恢复**；正文中的命令与writer归属仍为贡献者报告，不是独立writer身份或正式Run证明。
- 首批SUBMIT_ASSETS的ANALYSIS把该**Artifact UUID同时填进referenced_asset_ids**；原件上传接受不产生AssetRevision，因而该资产操作首发4xx / REJECTED，持久安全码为 `CLOUD_OPERATION_REJECTED`。首批REPORT的refs=[]与checkpoint选择本批REPORT正确。原始HTTP状态未保存；当前服务对应验证会返回422，但不能倒称现场捕获了422。
- 原UPLOAD、journal与RECOVERY变更均READBACK_COMPLETE，没有UNKNOWN。对原拒绝key补作GET仅得到 **HTTP404 / accepted_receipt_observed=false / post_sent=false / retry_authorized=false**（私有 `controller/codex-address-profile.rejected-receipt-observation.json`）；继续保留REJECTED，不重发、改写或以新key重复同一操作。HTTP拒绝不转为LOCAL_REJECTED反馈。
- 已观察的21 REQUEST_CREDITS=16ROOT+5CODEX不等于释放保留；完整56 credits / 900秒reservation与900秒preparation hold均保持 **HELD**。不因为stop / drain就补造结算或强改任务终态，也不套用先前“模型drain未观察”的host proof收尾。

后续修正通过source-r22模型可读契约和新独立Task验收，不修改上述被拒请求、原Task、原件或HELD历史；新Task须重读固定源码、产生新child原件与接受引用，不复用旧文件 / UUID / 模型会话。原source-r18的v14 reported PASS与本轮恢复态分别保留；本轮尚无完整typed子贡献 / delegation / Run交付或独立框架重放，不称legacy VERIFIED、Gate或P0全部退出。

### source-r22新Task：正式reported PASS，安全结算已核对

新独立 Task `01a16551-0b71-7fa5-83ee-f864f842e447` / Attempt `01a16552-5550-75ca-8474-0c98db018ab1`的prepare / resolve / dispatch均按原key接受并完整读回，真实执行后已固定 **v17 COMPLETED / reported PASS，assets16 / Run1 / RunCase8 / delegation1 / verified_originals4**。接受读回 `codex-native-io-contract.readback.json`的SHA256为 `42a18ca950e6abc1850dc5a427d267d5a5a7b48c6b2b1dd4ce7be1786d9865c2`。四份原件verified表示字节核验，不是legacy VERIFIED Evidence。

已独立核对的完成安全 / 预算字段如下：

- Task / Attempt均COMPLETED / PASS，当前Attempt身份一致，lease generation从reservation / settlement的1前进到2，lease owner / expires已清空；服务端完成事务按原fenced权限接受并清理租约。公开读回不包含work-grant撤销行，不冒称另做了DB权限审计。
- 完整reservation保留 **56 credits / 900秒**，本轮按 **36ROOT + 5CODEX = 41 REQUEST_CREDITS / 193秒** SETTLED，ROOT48 / CODEX8的scope上限及Task64 / 900秒不变；preparation hold同SETTLED且保留原900秒。依据明确为观察请求数乘预留率，不是供应商USD账单。
- 接受的settlement中namespace_stopped / brokers_drained均true；completion manifest的all_local_processes_stopped / external_operations_reconciled为true、pending_operation_keys=[]。授权与冻结manifest逐对象一致，仅git:read / framework:execute、network_targets=[]、同固定双SHA / PRDv3；没有新增SSH / CI / 一般网络。
- 资源元数据明确区分AS16GiB、聚合准入上限4GiB和实际cgroup2GiB / 0swap / 256pids，只含闭集数值。委派terminal为official-plugin-runtime-reported / stop_reason=completed / independent_execution_proof=false；准备时observed=false静态标志不否认后续正式记录。

当前接受读回本身不含逐broker HTTP / closed / inflight或native channel CLOSED字段；另已独立核对Worker保存的受控host观察 `r5-host-model-observations.json`（SHA256 `541a7cf55a3cba9d5ee3f8d2170affa567fd3ff7eb2c7a9e9e8942c5815b4576`）：**ROOT36 / CODEX5均HTTP200、success / completed与请求数相同，refusal0、transport_failure_counts={}，每scope closed / drained=true、inflight0，namespace_stopped=true**。`r5-runtime-diagnostics.json`（SHA256 `29a5afb6348c8938209dbb985cc1bc05e312aa201c51d87db22b1dc0c1e4a527`）只保存允许的活动投影，idle_finish_reason=completed、last_phase=DELEGATE_CLOSED；计数仍遵守前512 / 最近所收64条窗口，不当作全程审计。native channel关闭是完成前的代码门禁，未另持久化独立布尔，不能编造此证据。

已接受的16条资产为ANALYSIS1 / DESIGN1 / CASE8 / IMPLEMENTATION1 / REPORT5，Run1关联8个CASE修订与actual；四份原件包括4732字节子分析、3272字节完整实现diff、1152字节实际unittest日志和2328字节Run报告。子原件 `codex_analysis.md` SHA256为 `93685b5f5a5c130ce58cefc7111a48d23505ff723e75d53df909c3e272d53a1e`，Artifact `01a16554-bb8c-7456-9429-8f05d493d799`。native_ref=`06b334f1-7287-4e5b-b565-3da942dfc237` / run_id=`f33b1665-04e3-4bb7-b7da-13e5a40a58a2`的两个delegate资产引用指向本Task的ANALYSIS和DESIGN，来源保持runtime-reported，不提升独立writer身份。

**精确PRD偏差：** ANALYSIS `01a16554-dcf9-7825-9c88-6146e6a7f651`直接设置上述child artifact_id；DESIGN `01a16555-082e-7d88-af2f-40cb1fc33dce`的artifact_id为null，仅通过referenced_asset_ids指向ANALYSIS，形成有效的DESIGN→ANALYSIS→child原件链。平台schema允许这种引用，广义六步与实际子原件交付成立，但没有字面满足本次PRDv3“ANALYSIS和DESIGN都直接设置child artifact_id”的要求；**不能称strict PRD全部PASS**，也不修改已接受资产或任务结果来掩盖偏差。

本Task的独立只读框架重放已完成 **9项unittest通过（exit0，0.619989秒）**，固定双SHA、SUT clean、source_tree_unchanged和namespace stopped均确认；无LoadCredential / SDK / 模型 / Task写，原runtime在外层和namespace内均只读，新evidenceleaf为 `framework-replay-evidence/replay-native-io-r22`。首个临时unit仅因root0600脚本不可读而python打开失败 / exit2，没有输出leaf或测试启动；授读0644后新-r2 unit才完成实际重放，旧stdout / stderr保留，不把准备失败隐去或计作测试FAIL。

原3272字节实现diff的SHA256为 `fa4c8a579f4879b61cd6574f48c6bc8ddbc76edc7fc80190c43b36ca4aedef14`；独立解析其新文件原件后，与host before / after清单和实际2832字节测试文件三方精确匹配，测试文件SHA256为 `8d7bac4de16a1a4a6cb1c5fd1b101a7e9a9fabab83c5f0d8a289986c7d0a9ec4`，对应IMPLEMENTATION `01a16555-7678-7b0e-9e18-f875255fd098`；关联回执为 `framework-replay-evidence/replay-native-io-r22/accepted-implementation-linkage.json`。host树摘要 `3cd167d2d45daf2539c47b0af5753e2acf9e1ec2db51c27f91c17e138522f886`与AgentRun自报 `f8259ee367abf75071a9c20ad8e814eb3e2ce2c4e202edec9d18fd0d9de9c0b0`算法未约定相同，不等同。独立重放保持 **UNVERIFIED / Gate NOT_EVALUATED**，不写回或升级平台结果。

独立验收DB另已保存私有备份 `private-backups/cloud-e2e-v17-r22.dump`，702779字节 / SHA256 `894241fc7703d5c969a843de96dbc42f3db7052eac8829fff7b51cb65a046d3a`；`pg_restore --list`的header / catalog校验通过，但未做完整恢复演练，也不涉及生产DB。新PRDv3和账本没有重放r4拒绝请求、不改变r4恢复态 / HELD；本轮原件、Run、关联和重放均使用本Task身份，不拼接source-r18或r4证据。默认关闭、未部署生产，Claude仍占位、SSH / CI不支持；精确PRD偏差和其余P0未被平台reported PASS覆盖。

历史r22轮隔离服务已退场，回执为 `validation-cleanup-r22.json`：活跃 / 持有租约的Attempt和PENDING / RESOLVING解析均为0，隔离API已停止，仅本轮自建test-r3 / PostgreSQL两个容器及空internal网络已移除；原RECOVERY / HELD历史不删改。全部host证据、固定SDK payload / venv archive与受保护凭据保留；当时只读观察生产5容器healthy。本会话未执行生产部署或更改生产配置，其他会话的后续生产更新不在该历史回执覆盖内。没有临时在线Task入口继续运行；结果可由固定读回 / 原件 / dump / 日志复查，不声称完整数据库恢复演练或生产部署。

本阶段私有原始日志 / state / snapshot 位于 canonical `/var/tmp/hypertest-cloud-execution-20261022-7f75957a`；Operator、模型 key 与 OAuth 不进入文档 / 源码 / 原件。组件、原件、真实推理、平台 reported result与独立重放证据分别登记；首个受控 Task 的平台完成与实现关联已核验，其余 P0 条件未被略过，生产部署未执行。

## 首轮控制平面 / Web 历史证据

已完成的独立远端 SDK / CLI 首轮检查为 **46 passed**；真实官方双包在 `network=none` / 只读根文件系统 / 无模型认证条件下完成初始化、会话创建和关闭，wire 为 `0.0.1`，无 prompt。第二轮所选后端链路 **115 passed**，并完成独立空库向前迁移，分别保留原源码快照身份。

首轮最终所选后端范围 **153 passed（39.61 秒，54 条既有 SQLAlchemy warnings）**，覆盖 Cloud / 资源 / SDK 与探针 / ADR-018 / TaskSyncCore / 控制平面 fixture；该快照远端 Ruff 对 `src`、`tests`、`alembic`、`ops/deepseek` 通过。官方 runtime 地址空间诊断探针返回 `status=OBSERVED / reason=NO_PROMPT_PROTOCOL_OBSERVED`（无 prompt）；当时 Docker namespace 沙箱为上述 BLOCKED，后续 systemd r7 另记。这组历史结果不覆盖本阶段新增预算 / Messages / Codex 代码，也不等于全仓测试、真实模型或六步闭环。

第四轮 Web（canonical Web origin 修正前）**152 项测试通过、0 失败（165.39 秒）**，TypeScript 和 production build 通过；包含实时运行态、凭据轮换读回与固定取消原因修复。第三轮旧快照的 148 项测试 / TypeScript / build 保留原身份。

真实浏览器 POST 首次被同源检查以 403 拒绝，未写入 API；新增 canonical Web origin 修正后，**8 项 BFF 回归通过（3.43 秒）**，TypeScript 和 production build 再次通过（exit 0）。实际浏览器资源配置 POST 为 200，后续 configuration / credentials / directory / capabilities GET 均为 200，页面显示“已接受并完整读回”、资源基线为 1。该增量未重跑全部 Web 测试。浏览器另创建隔离任务 `01a16324-a874-79e3-8cc8-184f16258593`，完整读回 version 1 / DRAFT / NOT_RUN、原任务输入和框架命令；Worker 关闭，dispatch 控件保持 disabled，未下发执行。资源与草稿两页分别实测 1440px / 390px：document scrollWidth 分别等于 1440 / 390。四张本机截图已独立只读检查，当前所见资源表单 / 草稿页未发现阻塞交互或页面横向溢出；这不覆盖资产、真实 FAIL 长文本、私钥轮换与其他任务状态。截图位于私有证据目录的 `output/playwright/cloud-{resources,task}-{desktop,mobile}.png`。这些结果不证明模型 / 测试执行。

源码身份与本次验证范围分别保留：

- 原始第四轮快照：`d1c87923f151c4b05c813a602bb6d1cbc1cc2b119d51af2e42b1a8aacb989243`。随后叠加 Worker 两文件修复与九文件 import 修正的代码清单为 `c921aac16ed968d39bf804872d7cbb442058ff3bb946f678089a2300b2ffecbc`。
- canonical Web origin 修正清单：`daf1ce12a766777bf73f3998552e31567747aa40d41ff040ff16d02476c4a034`，对应追加 BFF 回归及 TypeScript / build。
- 实际受测远端 370 文件清单：`7d9911529b66f2ab37f6a1be957c2648a29ccc12977925fd749d7078ad2096e5`；含只读 `/bin` / `/sbin` shell 路径与断言，最终所选后端 153 项和 Ruff 通过。
- 采集时的共享工作树 370 文件清单：`d795193986f038b677fdbd6888cc9bbfb2f032876bc436d30d0663b5448891cc`。相较实际受测快照，采集时已有 13 个 Local 文件由另一会话继续修改，不在本轮受测清单内；其交付与验证由该会话独立记录，未回滚这些改动。

`final-source-match.json` 核对结果为：采集时本次 Cloud 与共享责任文件均匹配实际受测文件。不能宣称整个共享工作树已通过上述 153 项测试，也不能把旧快照检查覆盖后续 Local 改动；其他会话仍可能继续更新，以上摘要不是对实时工作树的持续保证。文档证据补记与源码验证时点分别保留。

远端 SSH 一度在握手 / banner 阶段关闭连接，退避后严格公钥连接恢复；没有改用密码 / ASKPASS 或放松主机密钥校验。追加修正的 Web 构建、真实资源配置 POST / 固定读回、桌面 / 移动截图与 DRAFT 创建按上述范围核验完成。清理回执为 **CONFIRMED**：本次验收专用的 4 个带标签容器（Web、浏览器、API、私有 PostgreSQL）已移除，剩余相应标签容器为 `[]`，私有网络已移除，证据保留；未修改生产服务。

首轮结束前既有 `ops/check-remote.sh` 返回 exit 1，停在 legacy host nginx 的 failed 先决条件；stack 与 Bridge 仍 active。只读元数据记录该 nginx 状态于 07:00:18 UTC 改变，早于约 09:00 UTC 的隔离验收，5 个生产容器均 Up 7h / healthy，未 reset / restart。该已有前置失败不能称新 Cloud 回归，也不宣称整个平台健康检查通过。

私有原始记录位于本机与远端的 `/tmp/hypertest-cloud-validation-20261022-f0c1c1c2` 工作目录（日志直接置于该目录，未放在 `validation/` 子目录）；这里不公开主机地址、登录配置或密钥。

Cloud 控制平面 fixture 使用合成原始报告验证关系、幂等、固定版本读回、FAIL 历史、凭据保护及 Local 兼容；它不证明真实框架 / 模型执行。源码存在、SDK 协议成功、测试 fixture 接受或页面可打开均不证明完整六步已完成。

正式Git迁移顺延与C4常驻部署已经完成，用户验收保持PENDING / USER_OWNED；未经明确要求不继续业务验收。尚未完成的能力或证据包括：SSH取消 / 失联矩阵、旧任务未交付原因收尾、DeepSeek自行路径完整成功、另行授权后的Claude实现 / 身份预配、真实目标准入与CI / 网络adapter、项目依赖与入口范围强制、真实模型下的整树取消 / 故障与恢复，以及staging项目完整流程。已有隔离、固定工具、所选回归、接受版本和独立重放不重复标为全未实现，也不代替这些未完成项；后续由用户选择实现 / 部署或明确要求验收，不自动开始。P0三种真实路径尚未全部退出，P1–P4范围见[实施计划](CLOUD_TEST_IMPLEMENTATION_PLAN.md)。

环境路由的仅收紧字段`cloud_access_policy=LOCAL_ONLY|WEB_ONLY|None`保持旧None序列化省略；LOCAL_ONLY拒绝Cloud创建 / 解析 / 下发和执行，WEB_ONLY限制HTTPS且当前HTTPS执行仍闭锁。未配置真实XBlock / 166dev资源，详见[环境路由](CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。

历史隔离轮次归属说明：上述fixture仅操作独立API / 数据库 / SSH资源，不代表当时常驻服务已部署；其清理按各轮实际回执，不沿用r22退场结论。此后单人测试服务器C4 Git交付另见[部署记录](CLOUD_GIT_DELIVERY_20261023.md)，不以旧uptime或旧fixture通过替代本次部署检查，也不据此宣称用户验收完成。
