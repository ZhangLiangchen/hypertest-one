# Cloud Worker 首轮进展（2026-10-29）

## 源码与验证

Cloud Worker 在领取解析或 Attempt 前进行无模型、无项目数据的 bubblewrap namespace 基础探针；已有 lease 过期处理先执行。探针失败不领取新工作，Worker 输出有界诊断并退出；超时或取消时停止探针进程组。该探针不替代每次 Attempt 的工作区、SDK、凭据或实际执行检查。

后续补充：基础 Worker 在领取 Attempt 前检查固定 SDK 契约、模型私有密钥可读性与正请求费率，失败不领取或启动模型；SDK 准入结果仅在当前进程缓存，密钥每次检查。基础轮询路径中的版本解析独立于该 Attempt 预检；受管 service-admission profile 原有的启动凭据门禁不变。定向回归 95 passed。

Cloud 报告固定版本读回增加完整快照 SHA-256、Run 身份/执行/用例/报告关联和完成终态/结果/清单核对。读回失败保持待对账，恢复仅查询原接受版本，不重发原操作。

首次本机 Worker 镜像构建在项目 wheel 元数据阶段失败：窄构建上下文遗漏了 `pyproject.toml` 强制包含的 Skill 文件。Worker Dockerfile 与发布构建上下文已按明确文件清单补齐，SDK 固定 wheel 安装拆为独立缓存层；发布构建上下文定向回归 43 passed。

使用已推送 Git `fe85a11437bcc08faffe1f18521b2cd30438afb3` 重建镜像成功：`hypertest-mac-cloud-worker:fe85a11`，image ID `sha256:c94596f28fc785efac07a64d86f272c5c6129d4bae35c8608fed010bb5c58072`。一次性无网络、无凭据、非 root、cap0/NNP、只读根容器检查确认 SDK/runtime 均为 `0.2.1rc2`、未启动模型，cgroup 为 2 GiB / 0 swap / 256 pids；真实 namespace 探针仍返回 `NAMESPACE_SETUP_FAILED`。镜像已构建，Worker 未部署或准入。

定向回归：Worker namespace、资源、SSH Worker、诊断和启动相关检查 108 passed；Cloud reporter、handoff 与数据库操作 76 passed / 1 skipped（本机虚拟环境未安装固定 DeepSeek SDK）；其他 reporter 相关检查使用短临时路径 86 passed。相关 Ruff 通过。首次 reporter 扩展回归使用 macOS 默认长临时路径出现 6 个 Unix socket 路径过长失败，改用短路径后复验通过；不把前次失败改记为通过。

框架回归在临时合成 Git 仓库实际运行 Python unittest 的 PASS / FAIL，再通过 Worker collector、reporter、原件与 Run/最终报告固定版本读回。PostgreSQL 使用新建的专用临时测试容器，完成后移除，不写业务数据库。本回归不启动 SDK、模型或隔离 namespace，不证明真实 SUT 运行或执行来源的独立认证。

## 本机环境与未完成事项

现场 Docker 为 OrbStack Linux ARM64 / cgroup v2，业务 schema 为 `0036_cli_global_authorization`；无独立 Cloud Worker 容器，API 的 Cloud / Worker 开关关闭。默认非特权容器在创建 user namespace 时返回 EPERM。以 Docker 29.8.2 官方 seccomp 默认 profile 作基线的临时诊断中，限定 user namespace 调用的规则可使简单 unshare 成功，但进一步的简化 bubblewrap 测试在挂载 `/proc` 时仍 EPERM；未确认唯一原因或形成验证通过的部署 profile。诊断期间另有一次误用 `seccomp=unconfined` 的无业务数据、无网络临时探针；它不作为方案或通过证据，临时资源均已清理。

本轮没有部署或启动 Cloud Worker，没有开启 Cloud 执行，也没有启动模型或真实 SUT 测试。需要完成实际 Docker 隔离准入、Cloud 专用模型身份与包装密钥、预算配置后再按固定 Git 提交构建和部署。测试服务器服务健康或源码回归不等于 Cloud 可用。

用户提供的独立模型密钥文件已验证为用户拥有的 0600 普通文件；一次性无网络、只读非 root 容器中的私有文件校验可读取。未显示或持久复制密钥，未请求模型，不能据此确认服务端认证有效。

补充探针：以默认 Docker seccomp 为基线的限域诊断确认，Docker 默认 `/proc` 子路径遮蔽阻止了新 PID namespace 中的 proc 挂载；临时移除遮蔽后可创建，但外层 `/proc/sys` 等挂载由只读变可写，不能当作等价防护或部署 profile。试图单独恢复只读挂载被 OCI proc-safety 检查拒绝；诊断资源已清理。[单次任务容器替代提案](architecture/ADR-029_CLOUD_ATTEMPT_DOCKER_ISOLATION_PROPOSAL.md)仍须独立实现并验证，不是当前实现。

无业务数据的一次性 sibling 容器探针显示：通过独立 named volume 子路径可访问专用 UDS、只读 SUT、写入 framework 工作区，Agent 看不到父容器私有文件与 Docker socket；非 root、cap0、NNP、无外网。停止父 Worker 后独立 Attempt 容器仍运行，故须另有独立 watchdog、硬截止和可核验停止，不能由父进程退出或 attach 断连推定终态。两容器与卷已清理；合成卷初始化临时用了宽权限，不能作为真实部署的目录权限。资源总额、原容器 ID/失答、独立凭据、可信镜像、Docker 控制面及收尾准入尚待实现和验证。

追加容器内 PID 1 监督实验：同 UID 的 Agent 可用 ptrace 暂停普通 PID 1，导致其硬截止延误，且可读取其合成环境和 memfd；`PR_SET_DUMPABLE=0` 后同条件的 ptrace、environ 与 fd 读取被拒绝，SIGKILL/SIGSTOP 未使 PID 1 退出或暂停，合成容器到截止时退出。新增仅允许固定 SDK driver 的候选 `container_guard`，检查非 root、cap0、NNP 与 non-dumpable、限制控制帧和元数据输出，并按原截止退出；原始无模型 SDK tool probe 与合成独立 session 子进程截止检查通过，定向回归 42 passed。Docker 观察为 exited / pid=0 不独立证明原 cgroup 空或 broker drain。该组件未接入 Worker，仍需独立外部 watchdog、容器身份与原 key、资源总额和收尾准入；不能用其结果宣称 Worker 已部署或可执行。

后续候选 guard 增加认证心跳：真实 RUN 须先收到绑定固定 Project/Task/Attempt、generation、spec、原截止与密钥摘要的 INIT 和 HMAC 心跳；心跳严格递增，过期、伪造、重放或控制通道 EOF 均停止，诊断专用 SDK 工具探针仍可无心跳运行且不能提交任务。合成 Docker 探针确认第二个 attach 的伪造帧被拒绝、原 watchdog attach 进程崩溃后容器退出、连续合法心跳不能延长原截止；SDK 工具无模型探针及定向回归 46 passed。心跳 key 不进入 SDK 子进程、环境或输出。当前仅验证 guard：尚无独立 watchdog 服务，guard 不核验 Docker 实际 spec、原容器身份或 DB lease；Worker 接线、共享 monotonic 时钟域、broker drain 和合计资源限额均待实现与验证。

包含认证心跳的镜像从推送 Git `9556f2a4e82d7ae164dc2a90fe62c6f157d51492` 构建，`hypertest-mac-cloud-worker:9556f2a` 的 image ID 为 `sha256:0bd3f2109268a4c7b77ba940031d5d31d920d9b5b9ede36499cc90d90e0ec3ee`。以该镜像的 guard 为 PID 1，在无网络、无凭据的默认 Docker 防护容器再次观察官方无模型 SDK 工具探针成功；镜像仍未作为 Worker 部署。

已从推送 Git `1d84678acb7eb5fe633584589a4661a196ad59a4` 构建 `hypertest-mac-cloud-worker:1d84678`，image ID `sha256:6a23a291fd4292df4f6e2b020a48ee98034c14cc043cdfb8f70269c1ecb8758a`。直接以该镜像中 `container_guard` 为 PID 1 运行无网络、无凭据、非 root、cap0/NNP 的固定 SDK 工具探针，SDK 初始化、工具 marker 和关闭均观察成功，`workspace-write / ask` 未变；容器自动移除，没有模型 prompt 或 SUT。此镜像尚未部署为 Worker。

进一步在默认 Docker 防护的独立无网络容器直接运行固定 `SDK_TOOL_PROBE`（无模型、无凭据、无 SUT）：SDK `0.2.1rc2` 初始化、创建会话与关闭成功，工具已注册且尝试调用，但官方工具返回 `is_error=true / error_code=OTHER / marker_match=false`，默认 `workspace-write / ask` 策略保持。无秘密合成探针的受控错误分类观察到 `/home/agent/` 下共享对象映射失败；核对实际挂载标志后对该 tmpfs 作 noexec / exec 单变量对照，两组均显示 `OTHER`，但进一步分类显示错误不同：exec 组不再出现共享对象映射错误，转而提示当前宿主的 workspace 沙箱不可用。具体是否由 seccomp / namespace 引起尚未核验。单次任务容器因此还不能声称支持 SDK 工具或项目框架执行。临时容器自动移除。

固定的 [DeepSeek Harness 上游源码](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/sandbox/sandbox-local/README.md)列出 Linux 的 bwrap 与 Landlock 后备链。Docker 29.8.2 的官方默认 seccomp 已允许三个 Landlock syscall；合成容器内 ABI 查询为 10，另外两个系统调用以无效 fd 进入内核并返回 EBADF。SDK 运行后的可观察 wheel、home 与临时目录未发现 landlock launcher；诊断插件导入官方 launcher 模块失败，但其模块解析边界不等于 SDK 内部打包，因此不能据此断言 launcher 未包含。官方 `--probe` 未运行，Landlock runner 实际状态仍未知；不能仅凭内核 ABI 宣称工具沙箱可用。

**本轮后续定位和修复：** 同一 SDK provider 的实际解析路径已确认缺少 `landlock-run`，原官方 `--probe` 为 ENOENT。SDK 固定版本对应的官方 `@deepseek-ai/node-addon-system-linux-arm64@0.1.2` 经归档 SHA-512 校验后提供该启动器，默认 Docker seccomp/proc、非 root、cap0/NNP、无网及只读根的合成容器内，官方 Landlock probe 报 full，原始 SDK 固定工具探针观察到 marker 成功，保持 `workspace-write / ask`。SDK home 需可执行且有足够空间；64 MiB 的合成 tmpfs 出现 ENOSPC，512 MiB 通过，不据此声称通用最低值。构建输入固定官方包完整性并校验架构、成员及许可证；定向回归 49 passed。诊断资源已清理。这是 SDK 内层工具修复，Worker 外层 bubblewrap 准入、正式模型和真实项目测试仍未通过。

已从推送 Git `fd160a6aeeb4c159b7e702c6df56690d792f01ad` 构建 `hypertest-mac-cloud-worker:fd160a6`，image ID `sha256:0a567fb3156a14c3d5fcce95d5b1061ba6bda5d250c349e4e82beb2fce5e0d13`。该镜像以默认 Docker 防护的无网络、无凭据短生命周期 ARM64 容器运行原始 `SDK_TOOL_PROBE`，确认初始化、会话创建、固定工具 marker 与关闭均成功，没有模型 prompt 或 SUT；容器自动移除。x86_64 包只核对过 registry 完整性元数据，没有执行测试。该镜像未部署为 Worker，既有服务和业务状态未改变。

后续镜像从已推送代码 `397a7ff9a9cb394c093f5fe4ae22f1d9c94cfcf6` 构建，image ID `sha256:3d2d8e5ca600a80c81f4bec8a0cb8f0ef04cc1a5618a9eddf831eaa6ae436833`。无网络、只读非 root 容器以合成请求额度测试 SDK 与用户提供的私有密钥文件的本地前置条件通过；未发送模型请求，真实 namespace 探针仍为 `NAMESPACE_SETUP_FAILED`。镜像未部署，模型服务端认证、SUT 和兑换结果均未观察。

用户选定 XBlock MR 1146 和 `hypervise_pure` 框架，以 staging 的 TRON_TEST USDT→TRX DEX 为目标。MR 已合并不证明 staging 已部署对应版本。当前受控 HTTPS 仅支持公开、无认证、无副作用的固定 GET/HEAD；认证及兑换写操作尚不支持，XBlock 需要 SSH / 服务器操作的路径仍遵守 Local-only 路由。具体框架依赖、授权和目标观察需另行核实；没有发起兑换或推定测试结果。

## Docker Attempt 候选接线及恢复（2026-10-29）

候选代码接入独立 Docker Attempt：受信 Worker 持 Docker socket，Agent 以非 root、cap0、NNP、只读根、私有 PID/IPC 和无普通网络运行，使用分开的 named-volume 子路径访问 workspace、只读 SUT、home 与受限 broker socket；Agent 不挂 Worker 私有运行目录、恢复凭据或 Docker socket。首片拒绝 Codex native delegation。Worker 自身、共享卷、镜像、配置和资源须经 Compose / Engine 准入；单 Worker 私有锁及原回执关联用于排除不明或尚未收口的旧成员。资源上限按 Worker 与 Attempt 合计，Engine 报告不等于独立读取 Attempt cgroup。

容器创建、原 ID 确认、单次启动意图和停止观察使用不可变原回执；重启恢复凭据仅用于原容器观察，不授予启动、续租或业务写。控制流失联时 guard 停止，原 ID 的 Engine 观察与 broker 排空分别决定能否收口。创建失答时只按原名和 spec 核对原 ID；仅在未登记启动意图、Engine 确认从未启动时记 `NEVER_STARTED`。已有启动意图、NOT_FOUND 或观察不充分仍保留 UNKNOWN / HELD，不能重发。

实际 OrbStack Linux 合成探针覆盖了专用 PostgreSQL 意图、原 ID 和启动登记、真实 DB 租约认证心跳、官方 SDK 固定工具 marker、原 ID 停止观察；另验证丢失创建回执后的原名恢复、未决/未知成员拒绝，以及空闲模型 broker drain。Mac 与 Linux 的单调时钟不相同，候选将 Linux boot ID 和 time namespace 偏移摘要固定并在 guard 校验。探针不调用模型、不使用真实项目或凭据；部分 Worker 资源和 reporter 为合成输入，不代表真实服务准入或 SUT 测试。临时容器、测试数据库、网络和卷已清理。相关代码定向回归 163 passed / 1 skipped；跳过的是本地虚拟环境缺少固定 SDK 的检查，SDK 固定镜像无模型探针已单独通过。

Docker 画像、release manifest 工具和 Worker 路径仍是默认关闭候选。`CONTAINER_CREATE_INTENT_ENABLED` 为 false，示例 Compose 的 Cloud 开关也为 false；**本轮没有部署独立 Cloud Worker、开放 Cloud、调用模型或发起兑换**。还需从推送的完整提交构建镜像并现场配置、核验独立卷、Engine socket、API 与 Worker 共用的包装身份、预算、实际服务准入和真实 Worker 全生命周期。认证写请求及原业务订单对账尚未实现；等待用户完成框架推送后重新核对固定版本、staging 实际部署与钱包使用协调，再执行授权的四笔测试。

后续准入复核发现已关闭容器的 Engine 状态校验因缩进不可达，且仅按标签枚举会遗漏无标签的共享卷挂载者；均已修复并覆盖运行中、身份或 spec 不符、伪造从未启动状态与未知卷成员拒绝。OrbStack 合成探针确认按卷可发现无标签子路径容器。首次固定提交镜像构建在下载官方 Landlock 包时因 TLS EOF 失败；构建现在可选用本机的完整性寻址缓存，仍验证官方 SHA-512、包身份、架构与成员，损坏时直接失败，不将包留在镜像。离线安装已在无网络合成构建中验证；这不代表 Worker 已部署。

## 2026-10-30 继续实施

固定 Git `53fa86afdc55a605fb71be6994321b7aa71845d8` 的 Worker 候选镜像 `sha256:c6d888e7f610d3a0f30c4d16b301db183968a4112355acc113436c32545509d3` 已构建。在本机实际 Compose 画像中，Worker 服务启动、Engine 成员、私有/共享卷与资源准入及专用模型密钥的单次请求均已观察成功；没有领取真实任务。候选身份、环境与测试数据见本机受限 observations。该镜像不包含本轮后续 action 变更，不能冒充其部署版本。

受控 action 候选增加原身份、单次发送和不可变观察的独立账本及 `0037_cloud_action_ledger`，隔离项目 signer，按固定公网 DNS/TLS 目标执行请求，使用原订单身份和项目观察器区分 HTTP、业务终态与链上结果。Agent 源码仅从固定 Git commit 按明确文件和摘要白名单导出，完整 Git 对象库与凭据保留在 Worker 私有侧；秘密扫描依赖已登记凭据和白名单审核，不保证发现所有未知秘密。新功能默认关闭，需 API 与 Worker 显式配置并通过各自准入。合成数据库已覆盖原 key、并发、撤销、未知状态与不可变终态；隔离容器以合成密钥运行项目 signer，并拒绝访问 Worker 私有账本、Docker socket 和网络。相关定向测试通过，不能替代真实任务结果。

已核实 GitLab 的 `testing` 最近成功部署记录对应 test 分支头 `3e99ad7a3d103656d2929cfa60492aa9aac91cf8`，该分支包含 MR 1146 的合并提交；这不是运行实例版本的独立证明。项目框架修复位于私有分支并固定到 `54568a5e115c0ca78c2bb914a90318ed3aba021f`；用户 master 不变。只读核查目标身份 OAuth、钱包余额、币种与已有历史订单查询可用；报价权限返回 403，服务器是否接受真实 RSA 签名须由受控请求实际观察。钱包候选和凭据不写入本文件。test 源码显示同时省略最小值与滑点会采用默认滑点，冻结动作按用户要求不发送 `minOutAmount`、显式使用 `slippagePercent=0`；仅源码和部署记录不能证明运行实例行为。

用户明确说明 Memory Service 已迁移到 PowerContext、本次无需处理，并将移除旧公告规则；不得把旧规则当作本次前置。**截至本条记录，四笔兑换尚未发送**；最终源码固定、API/Worker 部署、独立 GitLab 及环境凭据登记、任务执行和每笔结果仍需现场完成并如实记录。

后续本机按推送 Git `f72ab8905b540a1dbfbff417406547a584f221ae` 部署 API 与独立 Worker，schema 升至 `0037_cloud_action_ledger`；API 健康、Worker 实际服务与成员准入通过，独立模型 broker 的一次小额度请求返回 HTTP 200 并完成排空。XBLOCK Project 的 Cloud 配置和五项用途限定凭据已录入。Task `01a18bdb-89d1-71c3-85b3-2a990b602074` 的输入解析固定 MR HEAD `e1a50a00093f41b7d9ca078433a63d76b2f89e9c` 和 framework `54568a5e115c0ca78c2bb914a90318ed3aba021f`；唯一 Attempt `01a18bdc-6c48-7b06-92ec-01f68bc18345` 在执行前因 `REMOTE_NETWORK_UNSUPPORTED` 失败，状态 NOT_RUN，受控动作数 0，不重写原结果。原因是旧 SandboxPolicy 未识别新的受控 HTTPS action；本次修复只允许与冻结任务、目标和读写授权精确匹配的受控 profile，不授予 Agent 普通网络。定向回归 95 passed / 1 skipped；四笔兑换仍未发送，后续操作须使用新的明确任务身份。

Worker 修复版 `0dec8347e33fd714f700fcd8efe3d5740cb75d92` 部署后，新 Task `01a18be1-4170-709d-bf82-78f4e2fe59e1` / Attempt `01a18be1-9510-7739-b954-79c0081082c4` 运行框架并归档摘要与 JUnit，reported result 为 BLOCKED：2 USDT 被预检阻断，4/5/7 跳过；动作 identity、send、observation 均为 0。该框架运行记录来自 Agent 的来源声明，不升级为独立执行证明。只读诊断确认 staging OAuth 返回 token 长度超过原 4096 上限；候选上限调整至 8192 并保留校验，增加脱敏阶段错误码。以原冻结目标在真实 Worker 内只读重现，OAuth、地址和余额 GET、隔离项目 adapter 及独立字段校验均通过；未发送兑换，也未改写原结果。定向检查 70 passed，修复尚须按新提交部署。

### 自动观察和报告收尾修复

后续真实 Cloud 任务中，一笔已发送动作获得 HTTP 响应，但自动业务终态未及时写入，终止 handoff 因未决 action 被拒绝而进入恢复；历史运行没有保留足够的失败阶段，无法追认当时的唯一根因。原动作后来通过受限只读恢复追加 BUSINESS_TERMINAL，原任务仅按 Operator 对账收尾为 FAILED、预算保持 HELD；原 Agent 报告与原动作回执均不改写。

本轮修复一个可复现的时限缺陷：串行 OAuth、原订单与明细查询共享的 25 秒总窗口不足以容纳各自合法的 DNS/TLS 等待，观察上限调整为 90 秒，仍受原 Attempt 截止、租约和逐次权限检查约束。Worker 在 Agent 停止后先关闭动作入口并等待已有处理，再只按本 Worker 已发送的原 key 做有界只读观察；业务终态确认后才继续原 handoff 和 broker drain，无法确认、超时或租约失效仍保留 RECOVERY_REQUIRED / HELD。观察不生成新业务身份、不重发，也不将后续观察结果改写为已形成的 Agent 报告或 PASS。

定向代码检查 155 passed / 1 skipped；专用临时 PostgreSQL 的跨模块合成回归中，框架进程仅发送一次合成动作、退出后由真实 broker 自动观察并写入 BUSINESS_TERMINAL，再由 collector / reporter 完成 Task 和固定版本读回。该回归使用合成 signer 和内存 HTTP 目标，未运行真实 Docker Agent / SDK 或真实 SUT，不能作为其完整端到端验收。用户已暂停尚未发送的后续真实兑换，不得重发既有原订单或由合成结果推定真实任务全部通过。部署与实际复验另记。
