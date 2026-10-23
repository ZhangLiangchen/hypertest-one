# DeepSeek Cloud 隔离验收

本目录包含无模型的协议 / 隔离探针、需要另行显式授权的模型连通探针，以及只访问独立验收 API / 数据库的 CloudTask 控制器；均不安装或启动生产服务。无模型入口不读模型身份、不提交 prompt；模型探针不创建平台 Task，测试结果为 `NOT_RUN`；`cloud_acceptance.py` 可在明确授权的独立环境创建 / 下发真实 CloudTask，但不加载 SDK、不执行模型或框架。实际执行仅由另行运行的 Worker 负责，入口间的授权不互相派生。SDK 与 runtime 固定为 `0.2.1rc2`，wire 固定为 `0.0.1`；初始化、模型连通和完整任务分别验收。

## 两种部署边界

生产执行要求独立非 root Worker、每 attempt 的 bubblewrap namespace，以及覆盖 Worker / broker / SDK 全部后代的有限独立 cgroup v2。默认 Docker 的 seccomp / AppArmor 策略可能拒绝内层 namespace；这时保持拒绝，不自动换后端或增加权限。

允许的另一种基线是专用宿主 systemd 服务：固定、独占的非 root 服务账户；固定镜像导出的私有只读 RootDirectory；只读源代码与 Python 环境；独立 cgroup；空外层 capability sets；no-new-privileges。Agent 仍进入同一 `BubblewrapSandbox`，不因此得到宿主文件、平台凭据或宿主网络。初次协议探针使用 `PrivateNetwork=yes`，不启动模型 broker。正式 Worker 的受控 Git / 模型网络与私有认证须另行验收，不能直接把探针单元改成生产授权。

当前宿主验收使用已建立的独占非 root 账户 `hypertest-cloud` 及其固定主组；运行前记录 `id hypertest-cloud`，不复用其他 `nobody` 服务身份。`hypertest-cloud-probe.service.in` 是无自动启动入口的 probe-only 模板，其中 `65534` 是早期无认证探针的历史示例，使用前须审核并替换为该专用账户。模板不改变任何现有服务、AppArmor、宿主 sysctl 或 Docker 配置，不使用 privileged、SYS_ADMIN 或 seccomp-unconfined。

## 一次性 systemd 探针

由有权操作宿主的执行者准备：记录固定 image ID，使用未启动的临时 `docker create` 容器导出 rootfs，再删除该临时容器。导出物需保留镜像内的 `/usr/local/bin/python3.12`、共享库和非 setuid bubblewrap；不要复制宿主认证或用户 HOME。venv 与源码使用下面的只读 bind。不要全局安装 Python / SDK 或切换生产入口。

当前验收材料的 canonical 位置在 `/var/tmp/hypertest-cloud-validation-20261022-f0c1c1c2` 与 `/var/tmp/hypertest-cloud-execution-20261022-7f75957a`；原 `/tmp` 同名入口只保留兼容 symlink。后续 RootDirectory、只读 bind、私有 state 与来源记录一律使用 `/var/tmp` 实际目录，不把 symlink 当成私有文件或运行状态的权威路径。单元内部 `/tmp` 仍是独立 tmpfs，不是这些宿主目录。

下面沿用固定验收路径；先核对 snapshot / image 来源摘要和专用账户。`User=hypertest-cloud` 默认采用该账户主组：

```bash
systemd-run --unit=cloud-ns-20261022-7f75957a --wait --collect --pipe \
  --property=RootDirectory=/var/tmp/hypertest-cloud-execution-20261022-7f75957a/rootfs \
  --property=User=hypertest-cloud --property=UMask=0077 \
  --property=WorkingDirectory=/validation/repo \
  --property='BindReadOnlyPaths=/var/tmp/hypertest-cloud-validation-20261022-f0c1c1c2/venv:/validation/venv /var/tmp/hypertest-cloud-validation-20261022-f0c1c1c2/repo:/validation/repo /sys/fs/cgroup:/sys/fs/cgroup' \
  --property=MountAPIVFS=yes --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=PrivateDevices=yes --property=PrivateNetwork=yes --property=ProtectControlGroups=yes \
  --property='TemporaryFileSystem=/tmp:rw,exec,nosuid,nodev,size=256M,mode=1777 /run:rw,noexec,nosuid,nodev,size=16M,mode=755' \
  --property='ReadWritePaths=/tmp /run' --property=NoNewPrivileges=yes \
  --property=CapabilityBoundingSet= --property=AmbientCapabilities= \
  --property=MemoryMax=2G --property=MemorySwapMax=0 --property=TasksMax=256 --property=Delegate=no \
  --property=KillMode=control-group --property=TimeoutStopSec=5s --property=RuntimeMaxSec=60s --property=Restart=no \
  /usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 TMPDIR=/tmp \
  PYTHONPATH=/validation/repo/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
  /validation/venv/bin/python /validation/repo/ops/deepseek/probe_host_profile.py \
  --allow-protocol-probe --timeout-seconds 30
```

该命令只创建独立短期 unit；不用 daemon-reload，不安装 unit，不操作已有平台服务。`/tmp` 是该 unit 的私有 tmpfs，`mode=1777` 使非 root 身份可写；`/run` 是独立 16 MiB、noexec 的私有 tmpfs，不开放底层 rootfs 的 `/run`。不要 chmod 宿主 `/tmp`。SEA native addon 需要从受控临时目录加载，故显式 `exec,nosuid,nodev`；`noexec` 失败不授权放开其他边界。

wrapper 在启动 SDK 前检查实际 UID/GID、NnP、五组空 capabilities、空环境白名单、只读根 / cgroup、临时目录权限与挂载标志、当前 PID 的有限 cgroup 归属，然后调用现有生产 bubblewrap 协议探针。rootfs / venv / 源代码应由可信执行者持有，运行期间不得被任务账户修改。该检查不证明镜像来源、账户独占性或测试业务结果；这些仍需部署记录与独立验收。

不要未经独立 A/B 验收加入 `ProtectKernelTunables` / `ProtectKernelLogs` 等 `/proc` 遮罩，或会安装额外 seccomp 规则的 guard；它们可能与非特权 PID namespace 的 procfs 建立冲突。遇到拒绝先保留 stderr 私有证据，定位具体 mount / syscall，不自动加权限。

2026-10-22 的 r7 一次性单元在上述最小 profile 下，实际观察到全部 outer guard、2 GiB / 0 swap / 256 pids，以及同一生产 bubblewrap SDK 无 prompt 初始化和关闭；12.276 秒，峰值内存约 290.4 MiB。r4 / r6 附加 guard 的失败独立保留，不能仅凭症状确定唯一原因。该成功不含真实模型或委派。

## 单独授权的模型连通探针

`probe_model.py` 默认 `NOT_RUN`；必须显式 `--allow-model-probe`、新的私有 `--state-directory`、私有 `--key-file` 和正整数 `--credit-reserve-microunits`。它先持久化固定请求与声明的额度保留，再由宿主 `ModelBroker` 读 key。固定官方 provider 使用 Anthropic Messages wire，base 为 `https://api.deepseek.com/anthropic`；不回退 Chat Completions。最多 2 次已准入请求，每次最多 1024 tokens，带绝对 deadline；SDK 仅有 socket 与 sentinel。无自动重放，已有 state 直接拒绝。

本探针需要一个另行创建的短期单元，保留 r7 的非 root / cap0 / NnP / RootDirectory / 只读源与独立 cgroup；为了宿主 broker 连接官方 API，该单元不要启用 `PrivateNetwork=yes`。Agent 仍由同一 bubblewrap 创建独立无网 namespace。使用 `LoadCredential=deepseek-api-key:<已授权私有文件>`，只向脚本传 credential 文件路径；不要把真实值放在命令、环境、rootfs、源码或日志。需要 DNS 时只读 bind 单个 `resolv.conf`，不要挂整个宿主 `/etc`。源码与 venv 始终只读；另 bind 一个专属 UID 持有的 0700 canonical state 目录到 `/validation/probe-state`，仅该目录与私有 tmpfs 可写。

普通 key 文件继续仅接受 owner-only `0400/0600`。标准 systemd `LoadCredential` 的 `root:root 0440` 是 ACL mask，并不代表 root 组获得读取权限：统一 reader 仅在文件/单元目录只读、文件无硬链接、目录精确匹配 host 的 `CREDENTIALS_DIRECTORY`，且 access ACL 只允许 root 和当前非 root 服务 UID（group / other 均为零）时接受。`env -i` 后须显式传入该非秘密目录 metadata；用于 `systemd-run` 时传实际目录字面值，不假设命令参数里的 `%d` 会展开。service 文件的 `ExecStart` 可使用 systemd specifier。

例如，固定新的 transient unit 名为 `cloud-model-probe-example.service` 后，D-Bus argv 必须使用实际目录字面值。保留前述隔离属性、另行配置 LoadCredential 和 state bind 后，最终命令为：

```bash
/usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/nonexistent LANG=C.UTF-8 TMPDIR=/tmp \
  PYTHONPATH=/validation/repo/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
  CREDENTIALS_DIRECTORY=/run/credentials/cloud-model-probe-example.service \
  /validation/venv/bin/python /validation/repo/ops/deepseek/probe_model.py \
  --allow-model-probe --state-directory /validation/probe-state/new-run \
  --key-file /run/credentials/cloud-model-probe-example.service/deepseek-api-key \
  --credit-reserve-microunits <已批准额度> --model deepseek-flash \
  --timeout-seconds 60
```

这是新单元命名示例，不是历史验收 unit ID。若更换 unit 名，`CREDENTIALS_DIRECTORY` 与 `--key-file` 两处实际目录必须一起更换；`new-run` 必须未存在。只有 `.service` 文件的 `ExecStart` 可使用 `%d` specifier；传给 `systemd-run` 的命令 argv 不会自动把 `%d` 展开为凭据目录。

为 Type=oneshot 设置 `TimeoutStartSec`（例如 90 秒），并保留 `TimeoutStopSec=5s` / `KillMode=control-group`；不要仅依赖该类型不生效的 `RuntimeMaxSec`。额度数字是本次私有意图中的声明保留，不是供应商计费或退款证明；真实约束由请求 / token / deadline 和事先批准的模型资源共同提供。保留不确定请求的意图，不在 UNKNOWN 后重新执行。

仅当真实上游 HTTP 2xx 且响应完整、固定 marker 原件正确、SDK 返回有界 idle 观察、完整 namespace 停止且 broker drained 才输出 `OBSERVED`。这表示连通、marker 与清理被观察到；`sdk_turn_succeeded` 仅在 idle 且 `finish_reason=completed` 时为 true。已保留的 root 实际探针观察到 HTTP 200 两次与正确 marker，之后触及请求上限并以 `finish_reason=error` 结束，因此不能称 SDK turn 成功；不为改变该结果增加请求或自动重试。结果仅含允许 metadata，拒绝原因仅为固定类别计数，不保存原文响应；`test_result=NOT_RUN` 且不创建平台 Task。该探针不验收测试任务完成、业务 PASS、真实额度结算或委派能力。

### 分块读取与已保留失败

SDK driver 输出 NDJSON 多行 `runtime_phase` 与终态。`StreamReader.read(n)` 返回当前可用数据，第一行 phase 不代表 EOF。旧 model r5 探针在首行 `CONFIGURATION` 后立即等待退出并提前停止 SDK，实际模型请求为零；这是探针读取边界错误，不能记为 SDK / 模型失败。保留该次原始记录与私有 intent，不据此自动重放 prompt。

当前两个入口共用有界读取：累计最多 64 KiB，持续读取到真正 EOF、完整 ERROR 或总 deadline；完整 ERROR 先按闭集投影 phase / type / RPC 数字 / boundary code，再单独观察进程退出。后续退出或清理超时不覆盖首错，最后 phase 也不等于错误发生阶段或业务完成。无模型协议终态、root 模型 marker 与 native child 分别验收。当前 native 模型委派仍为 **NOT PROVEN**；无模型初始化 / metadata ready 不能升级为真实 child 成功，更不能证明六步流程完成。

同日原生无模型记录 `native-probe-r7` 的四个能力标志（provider、tool、subprocess shim、Node）、官方初始化 / 会话创建及干净关闭均已观察，结果 OBSERVED；没有 OAuth、模型推理或 child 请求。云端既有 OAuth 的 LoadCredential 安全读取与有效期已核对，上游认证 / 真实 child 尚未观察。先前 READY 不可用或关闭失败的记录仍保留，不能用该组件通过覆盖它们。

正式 Worker 的空 namespace 显式设置 `SHELL=/bin/sh`，启动前确认该普通可执行文件解析到只读 `/usr` 或 `/bin`，不挂宿主 `/etc/passwd`。新提案的 typed 校验失败发生在冻结请求之前，可生成 `.hypertest-cloud/rejections/<key-sha256>.json`：状态只能是 `LOCAL_REJECTED`，保留 handoff / key 摘要与最多八条静态字段位置和错误类型，不保存输入或异常原文。每 attempt 最多十六个被拒 key；原 key 永久保留拒绝记录，修正使用新 handoff key。它不创建 journal intent、平台操作或 ACCEPTED receipt；pending / UNKNOWN、权限、秘密和平台 HTTP 拒绝继续按原恢复流程处理。

Worker 的 `worker-error.json` / `worker-cleanup.json` 只保留首错及次级清理错误的闭集类型、固定仓库文件 / 函数 / 行号；CLI 使用同样投影，不输出 traceback 原文、源码、locals 或异常消息。`host_model_observation` 与 attempt 私有 `model-observations.json` 单独记录 scope 聚合请求计数、完整响应计数及停止 / drain 的宿主观察，不保存响应原文，也不能给多个 native child 逐一归因；不把静态 SDK import 检查中的 `model_started=false` 当作最新执行事实。诊断不改变历史结果或未结算的预算保留。

## 无模型 SDK 工具探针

`probe_sdk_tool.py` 必须显式 `--allow-sdk-tool-probe`；沿用前述同生产 bubblewrap、非 root RootDirectory / 独立有限 cgroup 和只读来源基线，在新的私有空 workspace / home 中取得官方 Agent，通过公共 `ctx.tools.execute` 执行一次固定 printf。它保留官方默认 **workspace-write + ask**，不覆盖政策、不绕过 ToolsService；模型 UDS 只 bind、不监听，不提交 prompt、不读身份或历史、不访问 SUT / 平台 Task。只有固定 marker、工具无错误、官方关闭与 namespace 停止均观察后才成功。以下命令只供已授权的远端一次性单元使用：

```bash
/validation/venv/bin/python /validation/repo/ops/deepseek/probe_sdk_tool.py \
  --allow-sdk-tool-probe --timeout-seconds 30
```

r14 的真实结果为 **status=OBSERVED，scope=SDK_FIXED_PRINTF_ONLY**，tool_registered / executed / marker_match 为 true、is_error 为 false，sandbox_mode=workspace-write、approval_policy=ask，namespace 已停止；无模型 / 鉴权 / 真实 Task，`test_result=NOT_RUN`。另行 nested user namespace / bubblewrap、sh / bash 探针均成功，未放宽隔离。这排除同 profile 的 SDK shell 普遍不可用，不证明模型实际使用过 shell、任意项目工具都可执行或完整六步成功。

## 独立六步验收控制器

`cloud_acceptance.py` 只经 typed HTTP API 操作独立验收数据库，Operator key 从受保护文件读取；完整非秘密请求 / key / expected_version 在唯一 POST 前持久到私有 state。`prepare` 建立公共 sampleproject 双角色资源与新 Task 并请求解析，独立 Worker `--once` 完成解析，`dispatch` 核对原接受版本 / 双 SHA 后下发，再由另一次独立 Worker 执行；`readback` 完整读取固定版本及原件字节，不推断测试 PASS。SENT / UNKNOWN / NOT_FOUND 均只 GET 原 key，不自动重新 POST、换身份或新建替代 Task。

显式 `reconcile` 使用独立新 state 和操作者私有 `--host-proof-file`，严格绑定原 Project / Task / Attempt / version；只按真实停机 / fencing 材料将 RECOVERY_REQUIRED 协调为 FAILED，声明模型 drain 未观察、KEEP_HELD，完整读回核对原两个 hold 不变，不伪造用量 / 结算。原平台写必须先完整读回；proof 不是 Agent handoff。原任务终态后才允许显式 `start-followup`：同 Project / 配置、原冻结双 SHA、related_task_id、新授权 / 预算与独立账本，只 CREATE / RESOLVE，不自动 dispatch 或重开原 Attempt。保留原 state / 请求 / 失败和预算历史。

2026-10-22 原真实 Task 的 CASE 提案失败，未接受资产 / Run；已协调为 v7 FAILED / NOT_RUN 并保留 HELD。第二个关联 Task 收到 6 次 DeepSeek HTTP 200 完整响应、76 秒后 SDK 干净 CLOSE，实际停止 / drain 均已观察；但无 ready / 测试新增文件 / 产物 / Run，现为 v6 RECOVERY_REQUIRED / NOT_RUN，EXPLICIT_HANDOFF_MISSING。派生 cache 只确认最后 step6 / output4096，不含 root 结束原因；截断仅为线索，不读会话正文 / 推理或重放来补证据。下一新 Codex Task 的 16K 有限请求执行尚未发生。r11 所选 21 个文件隔离回归为 370 passed / 2 条既有 warnings（57.59 秒），r12 Ruff 全部通过；源码身份和各次结果见[实现状态](../../docs/CLOUD_IMPLEMENTATION_STATUS.md#当前增量验收)。这不是生产部署、测试 PASS 或真实委派成功证明。

## 一次远端回归的固定范围

以下只是交给主控的执行清单，本文件不启动验证。应在已获授权的一次性远端环境使用固定源码 snapshot、固定 SDK/runtime、独立测试数据库和已准备依赖，迁移 `0023_cloud_tasks` 的结果单独记录。无需真实模型身份的契约测试不能替代上面的显式运行探针。

```bash
python -m pytest -q \
  tests/test_cloud_acceptance_controller.py \
  tests/test_cloud_api.py \
  tests/test_cloud_budget.py \
  tests/test_cloud_delegation.py \
  tests/test_cloud_handoff_contract.py \
  tests/test_cloud_handoff_rejections.py \
  tests/test_cloud_model_broker_diagnostics.py \
  tests/test_cloud_model_probe.py \
  tests/test_cloud_node_probe.py \
  tests/test_cloud_private_file.py \
  tests/test_cloud_resources.py \
  tests/test_cloud_runtime.py \
  tests/test_cloud_sandbox_probe.py \
  tests/test_cloud_sdk_diagnostics.py \
  tests/test_cloud_tasks.py \
  tests/test_cloud_worker_diagnostics.py \
  tests/test_deepseek_probe.py \
  tests/test_deepseek_sdk_adapter.py \
  tests/test_task_sync_core.py \
  tests/test_interactive_client.py \
  tests/test_session_tasks.py \
  tests/test_session_task_pages.py \
  tests/test_session_task_mcp.py \
  tests/test_local_sync.py \
  tests/test_local_sync_integration.py \
  tests/test_local_deepseek_bridge.py

python -m ruff check --no-cache \
  src/hypertest tests ops/deepseek alembic/versions/0023_cloud_tasks.py
```

最后七个 pytest 文件覆盖保留的 Local / 会话客户端同步边界；两种 Task 身份、writer 和凭据不合并。Ruff 使用 `--no-cache`，避免只读源码挂载下的 cache 写入失败被误记为产品 lint 错误。记录实际测试数量、失败和 skipped，不沿用旧 snapshot 的通过数。

## Docker 拒绝的诊断边界

2026-10-22 现场环境为 Docker `26.1.5+dfsg1`、bubblewrap `0.12.0`、Linux `6.12.111+deb13-amd64`。宿主非 root + NnP 的 user / mount / net / PID namespace 探针成功；同约束 Docker 中 `unshare(0)` 与 `unshare(CLONE_NEWUSER)` 均为 EPERM。该结果与 Docker 默认 seccomp 拦截 namespace 系统调用一致；没有内核审计行不能排除后续 AppArmor mount 拦截。

如需另一容器 profile，应固定与已安装 Docker 版本相符的官方 seccomp 来源、完整摘要和每项增量，在 cap-drop ALL / NnP / 只读 / 独立 cgroup 下逐项取证。只允许 clone / unshare 不足以完成 bubblewrap 的 mount / pivot_root / umount；默认 AppArmor 也可能独立拒绝 mount。这里不生成或自动装载未经现场验证的 syscall / LSM 例外。

来源：[Docker seccomp](https://docs.docker.com/engine/security/seccomp/)、[Docker AppArmor](https://docs.docker.com/engine/security/apparmor/)、[bubblewrap 0.12.0](https://github.com/containers/bubblewrap/tree/v0.12.0)、[systemd 执行边界](https://www.freedesktop.org/software/systemd/man/systemd.exec.html)、[systemd 资源控制](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)。

## 生产启动配置准备（未安装、未验收）

新增 `hypertest-cloud-worker.service.in`、`cloud-worker.env.example` 与可选 `hypertest-cloud-worker-codex.conf.in` 仅供审阅和显式部署准备；本仓库变更不安装、启动或 enable 任何服务，不更换现有 Compose / Docker Worker。基 unit 使用长期入口 `python -m hypertest.cloud`，无 `[Install]`、`Restart=no`；现有 probe-only unit 继续独立保留。服务使用已建立且独占的 `hypertest-cloud` 账户 / 主组，保留已验证的非 root、cap0、NnP、同一 bubblewrap、2 GiB / 0 swap / 256 pids 和私有可执行 tmpfs，不加入未经 A/B 验收的额外 syscall / procfs guard。

部署者须先固定生产 release：可信 image ID 导出的无认证 rootfs、Python 3.12 独立 venv（含 Cloud extra、exact SDK/runtime `0.2.1rc2`）、源代码 archive / commit 与可选的冻结 Codex payload；记录并独立核对摘要。它们由可信部署者持有、对任务账户只读，不能把 `/var/tmp` 的验收 venv / source 当成默认生产安装，也不能套用仍运行旧 Worker 且没有 Cloud 依赖的现有生产镜像。渲染每个 `@...@` 占位符后，source、venv、release manifest 固定 readonly bind 到 `/opt/hypertest-cloud/{source,venv,release.json}`；rootfs 须提供对应父目录、git、非 setuid bubblewrap、Python / 共享库、CA 与只读单个 DNS 配置。另行准备 canonical、服务 UID 持有的 **0700 持久 runtime**，只把它 rw-bind 到 `/var/lib/hypertest-cloud/runtime`；升级、停止和失败均保留原账本 / 请求 / 证据，不清理后自动重放。

外部 `release.json` 使用以下精确字段，所有占位摘要必须换成部署者实际核对的值；文件须 root-owned、只读且无 symlink / hardlink，模板里的 `@RELEASE_MANIFEST_SHA256@` 是该文件完整字节的可信 SHA256：

```json
{
  "profile": "hypertest-cloud-worker-release/v1",
  "source_commit": "REPLACE_WITH_40_LOWERCASE_HEX",
  "source_archive_sha256": "REPLACE_WITH_64_LOWERCASE_HEX",
  "rootfs_image_sha256": "REPLACE_WITH_64_LOWERCASE_HEX",
  "venv_archive_sha256": "REPLACE_WITH_64_LOWERCASE_HEX",
  "sdk_version": "0.2.1rc2",
  "runtime_version": "0.2.1rc2"
}
```

`ExecStartPre` 调用 `hypertest.cloud.worker_admission`，在任何 Worker / 数据库领取之前只读检查有效 outer guard、有限独立 cgroup、固定只读 source / venv、实际 Python / 已安装包版本、release manifest 可信摘要和私有持久目录，再用现有严格 reader 读取 wrapping / DeepSeek key；启用 Codex 时还验证冻结 payload 与整个最大 attempt 窗口所需的 OAuth 时效。release 中的 archive / image 摘要标记为 **OPERATOR_DEPLOYMENT_RECORD**，不是该进程递归重哈希完整 rootfs / venv 或证明挂载来源的声明。输出只含非秘密摘要、布尔值和固定错误码，不保存任何 key 值、长度或 key hash，不连接 DB / Git / provider，不启动 SDK，不创建 Task。`ADMITTED` 只表示服务启动前提，不能当生产部署、上游认证、模型执行或测试 PASS。

unit 还显式配置 `HYPERTEST_CLOUD_SERVICE_RELEASE_SHA256`：Worker 首次在导入 DB 之前复核完整门禁，此后每次 `run_once` / DB 领取之前只执行 `admit_credentials`（同名路径、strict wrapping / DeepSeek reader 与可选 OAuth 全窗口时效），不重新 hash 大型 payload、不联网。凭据过期、撤销或路径不匹配时退出非零，`Restart=no`；失败观察的 `check_*` 只描述本次门禁未做的动作，不否认该服务此前已执行的请求，也不改写旧 Task / UNKNOWN / HELD。该新字段默认空，原 CLI、Local 与非此部署 profile 的入口保持原行为；单独 `ExecStartPre` 成功不代替长期凭据就绪。

基 unit 统一 `LoadCredential` leaf 为 `wrapping-key` / `deepseek-key`，配置路径取当前 unit 的 `%d`。可选 Codex drop-in 追加 `codex-oauth`、只读 payload 和可信 manifest SHA，显式选择 `gpt-5.6-sol`；基配置不要求 Codex 或 Claude 身份。不要把 credential 路径或 Codex 开关再放进 env 文件：`EnvironmentFile` 的优先级高于 `Environment`，门禁会拒绝 leaf / unit 目录不匹配。API 与 Worker 必须由部署者配置相同 wrapping key / key-id；门禁不访问数据库，不能替部署者确认两端一致。unit 文件里的 `%d` 会展开；D-Bus `systemd-run` 的命令参数不会自动展开它，临时命令仍须传实际字面值并保留当前 `CREDENTIALS_DIRECTORY`。普通 0400/0600 与标准 LoadCredential 的 readonly / exact ACL / NOFOLLOW 要求保持原样；OAuth 不自动登录、刷新或复制本机身份。

env 示例默认两个 Cloud 开关为 false、请求费率为 0，保持拒绝执行；必须在独立授权后填写真实 DB endpoint、明确模型 / token / 请求数 / deadline 和保守费率，不能把示例值当价格或本轮实际 profile。host Worker 需要实际可达的数据库与受控 Git / 模型网络，因此基 unit 不使用 `PrivateNetwork=yes`；Agent 仍由 `--unshare-all --clearenv` 进入无一般网络的 namespace，平台 DB / 包装 key / 模型身份不进入它。现有容器环境里的 `postgres` hostname 不自动适用于该宿主服务。没有自动启动或重启：安装、启动、迁移、生产连通与真实任务验收仍须另行授权并保留原 UNKNOWN / HELD 状态。
