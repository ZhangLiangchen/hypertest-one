# ADR-013 正式部署与验收记录

> **历史或兼容资料：** 本文中的实施计划、配置步骤和部署/验收状态仅适用于所述 profile 与记录时点，不代表当前部署。现行入口见[文档导航](README.md)和[当前 TODO](TODO.md)；新 Local 接入见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)及 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)。旧合同、事实和恢复边界按各自范围保留。

日期：2026-10-19，Asia/Singapore。正式容器切换、旧数据保全及正反两条真实链路
已完成；稳定性观察结果见下文。
部署就绪不代表新的测试 Run 已获得质量结论。架构边界以
[ADR-013](architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)
及四份奠基文档为准，操作步骤见[容器部署与恢复](CONTAINERIZED_DEPLOYMENT.md)。

## 发布身份

| 项目 | 实际值 |
|---|---|
| PR #9 合并提交 | `740a74d3bf66edfe916a2f3e80e459edf63e61dc` |
| 首次正式切换，含备份/巡检修复 | `2ceff17fe7d4e090e651e12c3a57e4d1d802ffe2` |
| 正式运行补丁 | `95e92c584897ff18bc1a0006823891ca45a619be` |
| 执行目录 | `/opt/hypertest/container-current`；运行构建来源为 `95e92c5`，最终文档提交的源码同步单独登记 |
| Compose 配置 | `/etc/hypertest/container/compose.env` |
| 部署模式 | `/etc/hypertest/deployment-mode` = `container-v1` |
| 数据库迁移 | `0012_api_environment_v2` → `0013_run_bindings` → `0014_harness_operations` |
| PostgreSQL 原卷 | `hypertest_pgdata` |
| 正式 PostgreSQL 容器 | `hypertest-production-postgres-1` |
| 服务账号 | UID `999` / GID `989` |

首次2ceff17的97个platform、46个Web构建输入与已验收Linux镜像逐项一致。
95e92c5补丁只改变platform的`persistent.py`，因此重新构建API/Worker并建立同源Bridge
环境；46个Web输入保持一致，继续使用原镜像。新旧API/Worker/Bridge各29个Python
包版本逐项相同。Git提交和下表实际image身份分别核对，不相互替代。

| 组件 | 实际 image ID |
|---|---|
| API | `sha256:40c0e2f14f5bed143c5fc849889cafff628ad5dd0498a94cc48a4390c62fa4fe` |
| Worker | `sha256:4ca27762b9e62746e9cdce443445730fc4d5b8c567cdbb43ed25ccfeb3d63eda` |
| Web | `sha256:c698b031557bf297e389e970676cc9f33f256872431947eef23ff4c7a4af29fe` |
| PostgreSQL | `sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c` |
| nginx | `sha256:8f59ff5046a70e421d35ed7d1e862a963215c9689b36cb8f64a6c42f9cf2955d` |

四种 Runner 配置固定实际 image ID；补建服务器原先缺失的 `python-api-v1` 镜像
`sha256:56e59c0e1d3a9d0c141af3c38e9c44b65c8dea5d1b0116fc9f3b795ca1675e6b`，
没有替换既有 Runner 历史镜像。Host Bridge 的独立 venv 位于
`/opt/hypertest/bridge-releases/95e92c584897ff18bc1a0006823891ca45a619be/.venv`，
其应用源码与正式提交一致。

## 切换与旧数据保全

维护开始于 `2026-10-18T19:01:56.010161+00:00`，即本地 2026-10-19 03:01:56。
操作沿用 `/run/lock/hypertest-maintenance.lock`：先关闭旧定时器与 API 写入口，
确认没有 QUEUED / RUNNING / WAITING_INPUT / CANCEL_REQUESTED Job，再停止旧
Worker、Web、nginx。没有将旧 profile 的暂停任务迁移到持续主会话。

切换前配对冷备为 `/var/backups/hypertest/adr013-precutover-20261018T190207Z`，
包含数据库、Artifact、Workspace 和新建但尚为空的 Bridge ledger。相同备份已实际
恢复至独立 staging 数据卷中的新库 `hypertest_verify_prod_740a74d_pre`，文件恢复至
`/var/lib/hypertest/adr013-production-restore-pre`，未覆盖正式库或目录。

旧 `hypertest-postgres` 容器保留，状态为 stopped、`restart=no`。新容器是原卷的
唯一运行 owner。新 Worker 启动前执行迁移并逐表比较：33 张旧表的全部原字段、
行数与行 SHA-256 完全一致，5 个旧 Verdict 保留，新 Binding 数量为 0。
没有 downgrade、删卷、清库、旧 Session 合并或主会话回填。

独立审计在新正式 Run 创建前再次核验：

- 32 张旧表仍逐行、逐字段 hash 完全一致，包括 21 条旧 AgentSession、6 条旧 Job、
  5 个 Verdict 及其 `state_snapshot_hash` / `evidence_manifest_sha256`。
- `worker_heartbeats` 原 22 条记录的子集 hash 一致；新增 2 条容器进程心跳单独记录，
  不将合法 Operational 增量解释为旧业务数据改写。
- 原 32 个 Artifact 文件、260 个 Workspace 文件逐一验证 size 与 SHA-256 无变化；
  原生 workspace / Session 归属随旧表保留。迁移后的未验证数据库约束数量为 0。
- API 实际读回 16 份旧 Evidence、10 份 PRD/config，共 51,409 bytes，摘要全部正确。

服务的 Artifact 和 Workspace 绝对路径仍为 `/var/lib/hypertest/artifacts` 与
`/var/lib/hypertest/workspaces`。Provider OAuth、原生会话保留在原
`/var/lib/hypertest/.codex`；只读 `codex login status` 返回 `Logged in using ChatGPT`，
本次切换未重新认证、未复制认证文件。数据库与应用备份不代替 Provider runtime
的独立灾难恢复方案。

95e92c5补丁前另做配对冷备
`/var/backups/hypertest/adr013-prehotfix-95e92c5848-20261018T195044Z`，实际恢复到独立库
`hypertest_verify_fix_95e92c5848`及目录`/var/lib/hypertest/adr013-hotfix-restore-95e92c5848`。
40张应用表全部行/列摘要与38个Artifact、789个Workspace、3个Bridge ledger文件
一致；24个原生Session文件在切换期间摘要不变。它包含本轮新失败Job及已通过的
49项正式测试；生产DB未被恢复覆盖。补丁实际就绪时间为UTC19:52:17.335908。

## 服务、定时备份与就绪

旧 `hypertest-api`、`hypertest-worker`、`hypertest-web`、`nginx` systemd 服务均为
inactive / disabled。新 `hypertest-harness-bridge`、`hypertest-container-stack` 为
active / enabled，`hypertest-backup.timer` 为 active / enabled。旧
`/opt/hypertest/current` 仍保留旧 release，不能将其误当作当前执行目录。

备份入口更新为版本化 `ops/container/scheduled_backup.py`，保留原每日 UTC03:30
及最多 20 分钟随机延迟。单一维护锁覆盖停止写入、检查任务、冷备和恢复，不嵌套
调用会再次获取同锁的 CLI。Bridge 通过 `Wants/After` 启动，stack 的 `ExecStartPre`
要求 Bridge active；Docker 的 `Requires/BindsTo` 与守卫仍保持。

独立 staging 已实际验证忙时跳过：真实 Operational 控制请求处于 QUEUED / RUNNING
时，Worker PID / StartedAt、全部 durable job 行 hash 保留，未生成备份。空闲路径
完成配对备份和服务恢复，无死锁。备份故障回归另覆盖普通 API 恢复失败只关闭
API/nginx、保留执行中的 Worker/PostgreSQL/Bridge；网络守卫或 Docker 身份不可信
时才全栈安全停止。新增运维及现有部署针对性检查共 **42 项通过**，Ruff、Shell
语法与 diff 检查通过。

正式 `hypertest-backup.service` 已实际执行并成功恢复，产生
`/var/backups/hypertest/20261018T190426.712263Z`。独立检查确认 COMPLETE、manifest
及 database.dump / artifacts.tar.gz / workspaces.tar.gz / bridge-state.tar.gz 四组件
SHA-256 全部一致。服务恢复健康基线为 `2026-10-18T19:05:22.365089+00:00`。

本机 `bash ops/check-remote.sh` 已在 container-v1 模式通过：五个容器 healthy，实际
挂载、非 root、只读根、权限、原 PG 卷和 loopback 映射一致；HTTP 与 Worker 返回的
Bridge/Docker 能力可用。该检查不创建业务 Run，但 capabilities 会写入独立
Operational 请求。首次切换观察 UTC19:07:48.240451–19:22:48.467091，共900.22664秒、
32次采样健康。补丁后另完成独立完整窗口 UTC19:52:38.903405–20:07:39.034863，
共 **900.131458秒、31次采样全部健康**；五容器最大重启次数0、OOM false，Bridge
PID/NRestarts稳定，最低 MemAvailable 2,701,712kB（约2.58GiB）。两条正式模型链路
覆盖在该最终观察窗口内。补丁就绪后 Worker/Bridge warning/error、MISSINGGREENLET
及 API HTTP5xx 均未出现（日志取样至UTC20:06:14）。

UTC20:07:57最终复核原32个Artifact、260个Workspace及23个切换前旧native Session
文件摘要全保留；UFW不变、Docker PID3294/NRestarts0。原PG卷仅新PG一个运行owner，
旧PG停止且restart=no，全部staging容器停止。原生Session文件只做摘要比较，不读取
或输出其正文及认证资料。

## 访问边界

公网仍为 `http://155.138.206.106:8080`，nginx 与 UFW 只允许来源
`45.76.149.233/32`；`127.0.0.1:8080` 保留 SSH 隧道。API8000、Web3000、PG5432
仅绑定回环，无新增 wildcard 或 IPv6 应用监听。UFW 原三条 SSH / VPN 规则未改变，
自动 SSH 检查仍使用 `hypertest-one` 别名、公钥和主机密钥校验。

正式 Docker26 网络的自有 DROP 位于 DOCKER-USER 首条。独立接口实测直达正式
API/Web/PG 均被拒绝，DROP 计数增加 6；从 loopback peer 伪造 XFF / Forwarded
白名单地址访问公网 nginx 仍返回 403。临时 namespace / veth 已清理。

主任务已记录 VPN 公网与 SSH 本地转发 HTML/API HTTP200、15 份静态资源 HTTP200，
共19项 HTTP 检查；新 nginx 日志确认真实 TCP peer 为 `45.76.149.233`。
补丁及两条真实链路完成后再次实测 VPN/SSH 的 HTML 与 API health，4项全部200，
见 `final-access-checks.json`；`final-remote-check.txt` 的完整就绪检查再次通过。
操作者在本轮对话中用不连接 VPN/Wi-Fi 的手机移动网络实测并确认
“无法访问（符合预期）”，记录在 `operator-mobile-check.json`。独立公网拒绝结论来自
该实际客户端观测；物理接口 en0 的另一次超时没有服务端日志对应，不作为拒绝证明。

没有重启共享 Docker daemon 或宿主。`restart=no`、systemd 受控入口、首条 DROP
和实际受控启停已核验；本记录不声称完成实机重启验收。

## 新正式真实测试周期

两条 Run 均通过真实 Web 创建、选择固定仓库 SHA、导入实际 PRD 文件并启动。
宿主 Codex 使用已有 OAuth；模型 Proposal 经过平台验证，正式事实来自 Docker Runner。
没有用模拟 Agent 输出替代最终验收，也没有创建外部 Issue。

| 场景 | Run / 被测源码 | 正式结果 |
|---|---|---|
| 正向、两次人工问答及显式恢复 | `01a1506d-a9e0-7dc4-91f3-b243c278fd92`；SUT `0a2af9c4f5034c118f1a19abd786290f0959a648`，`examples.api_sut.app:app` | 49 PASS / 0 FAIL / 0 ERROR / 0 SKIP，5 份可信证据，FINAL `RELEASE_READY`，报告已接受；41 项独立检查通过 |
| 产品缺陷诊断 | `01a15098-9ec5-7e56-b904-c484948981c8`；SUT `248b45dfcae2880087951f79baec5c4e7af26856`，`examples.api_sut.broken_app:app` | 14 PASS / 8 FAIL / 0 ERROR / 0 SKIP，5 份可信证据，1 个诊断 Finding，FINAL `RELEASE_BLOCKED`，报告已接受；43 项独立检查通过 |

两条 Run 均采用冻结的 `python-api-v2` 服务环境。平台 release 与被测源码 SHA
分别记录，先前 local/staging 的成功记录不替代本次正式结果。

### 实际故障、修复与恢复

正向原 Job `01a1506e-0144-78cb-8dd0-2f9fc0d582b6` 在 Web 完成 Mission 范围问答后，
四个 Mission/Attempt 均已接受，并产生唯一正式 Execution
`01a15070-185c-73f1-b266-67eded012229`（49 PASS）。此后模型读取 Evidence 时省略
`evidence_id`，工具按协议正确拒绝。事务回滚使长存的 ORM checkpoint 过期，下一轮
读取触发 `MISSINGGREENLET`，Job FAILED、Binding RECOVERY_REQUIRED。它不是认证或
Runner 故障；初始失败及诊断日志均保留。

`95e92c5` 在回滚后显式刷新 checkpoint，后续仍执行原租约、epoch 和绑定校验。
新增六种 PostgreSQL 回归覆盖缺失 Evidence ID、未知实体和过早执行请求，在有/无
active Mission 时都不会因工具拒绝终止会话。运行时测试文件 20 项通过。

部署补丁后通过 Web 显式恢复（请求 `01a15093-f9a0-7850-b9fd-66fc52c582ca`），
Binding epoch 1→2，原生 Session、workspace、logical worker 均不变。随后从原失败
Job 创建带 `retry_of` 的新 Job `01a15094-7128-7916-958a-d14505045719`；它提出 Run
范围问题，实际 Web 回答后由同一新 Job 接续，完成 Gate 与报告。原四个已接受
Mission/Attempt 没有重开，唯一 Docker Execution 没有重跑，原失败 Job 与五份
Evidence 的所有既有字段摘要不变。初始 49 项执行发生在 `2ceff17`，恢复、第二次
问答、Gate 和报告在 `95e92c5`，不能将其写成补丁后重跑了 49 项。

唯一原生 Codex Session 为 `01a1506e-0d45-78e3-a25a-587bccb758d1`；稳定身份 SHA-256
`b3fe4423e3e1464f43e1d3e3035fd316f62566447cb4c80eebf755d2f83e34c5` 在等待、失败、
恢复和终态间一致。四次调用总耗时 113/3600 秒，剩余 3487 秒；人工等待没有重置
冻结预算。终态 Binding/Session CLOSED，两次问题均 CONSUMED。

正向报告 `01a15096-5857-70db-bcae-51b9b0b2c3bf`，1571 bytes，SHA-256
`6201650d369dd1c23b6b3e608ecfe10ecf2003c2ed0dc0bc94c36fc19bb3e819`。
独立重算 Gate Evidence manifest 为
`5af4f8398fd60de324257bdb44452574adce4e0074c49f5dfa734e016b69fb98`，与平台一致。
`actual-recovery-acceptance.json` 的 41 项检查专门核对显式恢复；原正常等待检查器的
“epoch 必须为 1”“全过程同一个 Job”两项假设不适用，原始 false 结果仍保留。

### 故障版本的真实诊断

负向在补丁后完整执行：唯一 Job `01a15098-f561-7301-a4e3-dd83a5734f01`，唯一
Execution `01a1509a-4140-76d5-bcce-b0d123bf40e2` 正常结束为 FAIL、exit code 1、
`error_code=null`。8 条 JUnit failure 均为真实 AssertionError，例如请求 a=2、b=3
得到 -1 而预期 5，没有环境 error 或 skip。

5 类 Mission 全部完成，包含 `DIAGNOSE_FAILURE`。实现阶段第一个 Proposal 被验证
拒绝，模型在同一 Session 内修正后接受；6 个 Attempt 中 5 ACCEPTED、1 REJECTED，
拒绝历史保留，没有 Job 或 Execution 重试。CRITICAL PRODUCT_DEFECT Finding
`01a1509a-9a38-7f67-a208-a87eaf5deec1` 来自已接受的诊断 Proposal，指出固定源码
执行减法，通过 SUPPORTS 关系指向同 Run 的可信 Runner Evidence。

唯一原生 Session `01a15098-fe32-7d03-ac69-a57c16371bf3`，epoch 1，单次调用
耗时 121/3600 秒，终态 CLOSED。报告 `01a1509a-d16d-7f7c-9dd2-b684410233f1` 为
1953 bytes，SHA-256
`2bcf80d002d11f6fafec04c56c82a749bb4cc4eb16af03f98496d7bf92115723`。
独立重算 Gate manifest
`e64daa93800882a24d31b9e6a3ad1c452c1a7955cbd44a1ea6c9aace5b59d91a` 与平台一致。
Web 实际显示“任务已完成”同时“阻止发布”，并能阅读报告和关联发现。

### 自动检查

补丁提交 [95e92c5 CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39160250517)
全部成功：Ruff、Alembic、后端 **645 passed / 18 opt-in skipped / 3 既有警告**，
Web **61 passed**、`npm ci`、typecheck、production build。独立 npm audit 为
0 vulnerabilities。CI 默认跳过的 18 项受控 Docker 检查不冒充本轮集成通过；
上文两条正式链路分别提供真实模型、Docker 和证据验收。

## 证据位置与回退边界

本机交接目录：`/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/`。

- `adr013-production-740a74d/DEPLOYMENT.md`：单一部署操作者的切换记录。
- `adr013-production-740a74d/server-evidence/` / `final-evidence/`：已复制的保全、服务、网络、备份证据。
  服务器原件位于 `/opt/hypertest/adr013-production/ops/`，迁移基线在 `cutover/`，
  补丁准备、备份恢复、网络与最终观察位于 `hotfix-95e92c584897/`，其中
  `observation/result.json` 记录最终完整15分钟窗口。
- `adr013-production-acceptance/root-access-checks.json` / `final-access-checks.json` /
  `final-remote-check.txt`：主任务切换前后、真实链路后的实际 HTTP/访问/就绪检查。
- `adr013-production-acceptance/observations/`：本轮新 Run 的 API、只读 SQL 与原生身份
  证明；`actual-recovery-acceptance.json`（41 项）与 `actual-negative-acceptance.json`
  （43 项）给出完整结果及原始证明文件摘要。
- `adr013-production-acceptance/*-final-overview.png` / `*-final-report.png`：实际 Web
  结论与报告截图，PRD 原文件及两次问答、恢复截图也保留在该目录。

旧 release、旧容器、历史镜像及持久数据均保留。新的持续 Binding 已由本轮正向
Run 建立后，不能直接启动旧 binary 当作无条件回退；应使用兼容新 schema/profile
的 release 或向前修复，保留全部 Session/workspace/ledger。不得降级数据库、删卷
或用旧 dump 覆盖正式库。恢复正式数据属于独立操作，须先隔离验证配对备份。

真实 GitLab 外部创建/指派、其他 Provider、多宿主调度和宿主实际重启未在本次验收。
恢复后已关闭会话仍显示旧恢复提示的 Web 文案问题已记录，后续产品完善时处理；
不影响最终 Gate、报告或禁止重试终态绑定的控制。
