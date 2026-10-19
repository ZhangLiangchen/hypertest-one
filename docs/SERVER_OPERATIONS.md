# HyperTest One 服务器操作交付

## 当前访问与巡检规则（2026-10-19 更新）

Web 的唯一用户入口是既有跳板机出口对应的来源白名单入口。真实入口地址及唯一
IPv4 `/32` 来源保存在服务器受保护的 `compose.env`，分别由
`HYPERTEST_PUBLIC_IP` / `HYPERTEST_INGRESS_PORT` / `HYPERTEST_VPN_CIDR` 指定；
产品说明、白皮书和新的验收摘要不列出跳板机地址。配置升级必须沿用这些现值，
不能照抄示例中的文档地址。原始历史证据保留其当时的真实内容。

生产 nginx 的回环监听仅接受 `GET` / `HEAD /api/v1/health`，其余路径拒绝；
它供容器与运维检查，不再提供备用 Web/API 入口。API、Web、数据库的内部回环
映射仍保留，用于可信组件和运维。SSH 仅作管理与人工恢复，公钥、现有密码登录、
SFTP 和主机密钥校验保留；标准 TCP / Unix socket / TUN 转发停用，不再建立 Web
隧道。`ops/ssh/00-hypertest-no-forwarding.conf` 及安全安装步骤见
[容器部署网络边界](CONTAINERIZED_DEPLOYMENT.md#网络边界)。受信 root shell 本身
仍具有管理能力，禁转发不构成对 root 的权限隔离。

首次启用或变更访问策略时，做一次实际白名单允许与拒绝验证，并保留结果。
常规应用部署只核对受保护配置、实际 nginx ACL / UFW / Docker 守卫继续有效，
加上内部服务就绪检查；不重复要求手机断 VPN、VPN 重连或整套外部连通性验收。
访问异常时再针对故障检查。`bash ops/check-remote.sh` 保持按原 SSH 别名和严格
公钥方式执行平台检查，不创建业务测试任务，也不检查备用隧道。

## ADR-015 当前生产发布（2026-10-19）

生产切换已于 **2026-10-19 13:01:10 UTC** 完成：业务源码
`63bd6cc6710d2937d189acc90acaa15502d73a24`，数据库
`0018_harness_selection`，固定运维 manifest
`61b4e2800472db67d0e52cbc1507663fc8ac9d707b43e308e6fb88e32ff8214d`。
API / Worker / Web 已切换，原 `95e92c5` 宿主 Bridge、PostgreSQL 容器 / 数据卷 / 镜像、
原生认证与会话、历史数据和访问规则保留。原 38 业务表 row hash、文件、认证 metadata、
SSH / UFW / Docker 守卫、PG identity 和备份 timer 已在公共 admission 前核验。
版本表另行确认由0014向前升至0018，不能称39表 hash 全部未变。

现有受保护监听的配置升级为 HTTPS / WSS，来源地址、端口与唯一 VPN 白名单保持。
回环 nginx 继续仅通过 **HTTP** 提供 health；API / Web / PostgreSQL 仍只绑定回环。
`HYPERTEST_INGRESS_TLS=enabled` 使 `stack.compose_command` 自动加载同一 TLS overlay，
start、backup、readiness 不得漏载；仅 nginx 只读挂载 leaf cert/key。
`FORWARDED_ALLOW_IPS` 限于回环和实测单个 proxy peer，Operator key 留在保护的
platform.env，CA 私钥留本机。实际值仅在私有配置，不复制到公开文档。
**严格外部 TLS、线上本地 Connector 核心周期与私有源码 source-only 接受补验已通过**，不能用内部 readiness
代替外部证书校验或正式 Runner / Evidence / Gate 验收，也不能关闭证书校验绕过失败。

常规状态检查使用当前固定运维包：

```bash
ssh hypertest-one
cd /opt/hypertest/ops-current
python3 ops/container/stack.py --env /etc/hypertest/container/compose.env status
```

业务恢复前检查同一维护锁、WAITING_INPUT、open Binding 与未知调用 / 外部操作。
有活动或未知结果时，先关闭 API / nginx admission，保留 Worker、Bridge、原会话和
Runner 收尾；不得直接整栈重启、重投消息或换会话消除未知状态。应用回退不自动降级
schema，也不恢复覆盖生产库。此次两次安全回退、最终切换、已通过的线上核心周期与扩展验收边界见
[ADR-015 生产部署记录](ADR015_PRODUCTION_DEPLOYMENT.md)。

业务与运维版本分别登记：`container-current` 指向业务源码发布，平台镜像和
`bridge-current` 各自记录构建身份；`ops-current` 可指向
`/opt/hypertest/ops-releases/<manifest-digest>` 中固定的运维源码包。它包含运行所需
`ops/container`、Compose 文件、SHA-256 manifest 与 provenance，不含生产 env 或
认证。stack / backup 的窄 systemd drop-in 使用该入口，保留原依赖、维护锁和 timer；
健康检查优先使用它，无此入口时兼容旧 `container-current`。已配置却断链或缺文件
必须失败，不能偷偷回退旧巡检。运维快照的 digest 不冒称已合并的 main commit。
业务升级前必须核对固定运维 Compose 与新镜像/协议兼容；改变运维代码或 Compose
时生成并验收新的运维包，不能让旧 `ops-current` 静默遗漏发布所需配置。

## 访问与巡检修复登记（历史，ADR-015 切换前）

该轮已实际安装 sshd drop-in，并将 health-only nginx 与新版巡检/备份成对切换。
业务源码入口仍为 `828225d1c1d698f820aebb265ad962e3ab6c2151`，Bridge 仍为
`95e92c584897ff18bc1a0006823891ca45a619be`，五个运行 image ID 均保留；本轮仅发布
运维修复，未部署 Finding / Gate 新业务功能。当前运维源码 manifest digest 是
`90037658b11338ea183e9daa197d1bde5671cf8617bc6322f9ead96f009c2c96`，属于明确登记
的 working-tree 快照，不宣称已合并到 main。新 SSH 公钥登录、TCP / Unix socket
转发拒绝、内部 readiness、实际白名单浏览器 Web/health 及内部非白名单拒绝均已
通过；39 张纳入保全范围的原表与 2451 个既有 Artifact / Workspace / Bridge 文件 hash
保持，原 OAuth、UFW、Docker 守卫及登录配置保留。详细证据见本机交接目录
`closed-gate-20261019/evidence/server-access/` 与该轮运维报告。
备份 timer 继续每日 UTC03:30 加最多20分钟随机延迟；daemon-reload 后随机触发点
从03:43:38变为03:44:10，原 timer 文件、日历策略与持久配置未修改。

以下旧部署和 SSH 隧道段落是历史记录，
不授权恢复旧 Web 隧道或重放早期白名单激活脚本。

## ADR-013 首次生产切换记录（历史，2026-10-19）

PR #9 已合并为 `740a74d3bf66edfe916a2f3e80e459edf63e61dc`；正式发布另含备份与巡检适配
`2ceff17fe7d4e090e651e12c3a57e4d1d802ffe2`，并更新至真实验收发现的会话修复
`95e92c584897ff18bc1a0006823891ca45a619be`。当前运行入口是
`/opt/hypertest/container-current`，不是保留的旧 `/opt/hypertest/current`。
五个 `hypertest-production` Compose 服务承载 nginx、Web、API、Worker 和 PostgreSQL；
宿主 `hypertest-harness-bridge` 保留原 Codex OAuth、原生会话与运行时。
数据库已从 0012 升至 `0014_harness_operations`，继续使用原 `hypertest_pgdata`。
完整切换、旧数据逐项核验、配对备份恢复、真实运行与限制见
[正式部署验收](ADR013_PRODUCTION_DEPLOYMENT.md)。下文旧版本操作保留为历史记录。

连接 VPN 后仍访问 `http://155.138.206.106:8080`，公网仅允许来源
`45.76.149.233/32`；API8000、Web3000、PG5432 只绑定回环。SSH 备用入口：

```bash
ssh -N -L 127.0.0.1:8080:127.0.0.1:8080 hypertest-one
# 浏览器打开 http://127.0.0.1:8080
```

在本机仓库执行 `bash ops/check-remote.sh` 会根据受保护的
`/etc/hypertest/deployment-mode` 检查实际容器、数据库、Worker、Bridge 和 HTTP，
不创建业务测试运行。查看正式服务与日志：

```bash
ssh hypertest-one
systemctl status hypertest-container-stack hypertest-harness-bridge hypertest-backup.timer
journalctl -u hypertest-harness-bridge --since '30 minutes ago'
cd /opt/hypertest/container-current
python3 ops/container/stack.py --env /etc/hypertest/container/compose.env status
```

恢复平台必须经 `systemctl restart hypertest-container-stack` 重建并检查网络守卫，
不直接执行 `docker compose up`。操作前确认活跃任务与维护锁，按
[容器部署与恢复](CONTAINERIZED_DEPLOYMENT.md) 处理；暂停中的持续会话必须保留其数据库、
Bridge ledger、原生会话和工作副本。旧 `hypertest-api/worker/web/nginx` 已停止并禁用，
不要同时启动它们或让旧 PostgreSQL 容器挂载同一数据卷。

`hypertest-backup.service` 已切换到新版本 `scheduled_backup.py`，使用原维护锁；
每日 UTC03:30、最多20分钟随机延迟的 timer 保留。忙时恢复 API 并跳过冷备，
不打断 Worker；空闲时配对保存 DB、Artifact、Workspace 和 Bridge ledger，
随后通过守卫恢复服务。备份不包含 OAuth 或平台凭据；原认证目录留在宿主。

核验日期：2026-10-17，Asia/Singapore。本文中的“交接目录”指本机 `/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff`，可移交证据副本见 [第一阶段验收](FIRST_PHASE_ACCEPTANCE.md)。目标：155.138.206.106，root SSH/22。实际主机是 Debian13.7 x86_64、2CPU/3915MiB，已有7.7GiB swap保留。此部署面向一个可信操作者。d20 已部署时使用 SSH 隧道访问；用户现已选择 VPN 来源 IP 白名单入口加 SSH 备选。阶段1 `73dff989b87fa7349d9b36bd8416ece948a82212`已部署并激活白名单；当前范围修复的后续实际版本、网络状态与运行结果以[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)为准。来源白名单不等于应用登录/RBAC。

<a id="ssh-access"></a>

## SSH 登录与自动检查（2026-10-18 更新）

本机后续远端检查统一使用 `hypertest-one` SSH 别名与专用 Ed25519 密钥。目标为 `root@155.138.206.106:22`。2026-10-18 已分别实测别名密钥登录、IP 密钥登录和强制密码登录成功；原有密码登录继续保留。本文其余版本与验收记录保留各自的历史时间。

本机 `~/.ssh/config` 中的配置如下；原 OrbStack Include 保留在文件顶部：

```sshconfig
Host hypertest-one 155.138.206.106
    HostName 155.138.206.106
    User root
    Port 22
    IdentityFile ~/.ssh/hypertest_one_ed25519
    IdentitiesOnly yes
    PreferredAuthentications publickey,password
    StrictHostKeyChecking yes
```

私钥 `~/.ssh/hypertest_one_ed25519` 仅保存在这台 Mac，权限为 `600`；远端 `/root/.ssh/authorized_keys` 仅追加对应公钥。其他电脑、CI 和云执行器需要独立配置及授权，不能直接假定此别名可用。不要把私钥或密码写入仓库、交付归档或日志。

- 专用登录公钥指纹：`SHA256:qA1hUtHN3M+8o6LLBhjUQWG6XVeJh2P/ONwvlgiDJKE`。
- 服务器 Ed25519 主机密钥指纹：`SHA256:PoYUrSTDnN10A010My98ydOX3HQq/FynK/VxU9T5AqI`。这是服务器身份，与登录公钥不同；后续连接继续校验已有 `known_hosts`。
- 本机配置备份：`~/.ssh/config.before-hypertest-one-20261018T125515637563Z`。
- 远端授权文件备份：`/root/.ssh/authorized_keys.before-hypertest-one-20261018T125452257501Z`。恢复前保留之后新增的授权，不能盲目覆盖。

日常交互登录：

```bash
ssh hypertest-one
```

自动连接预检及统一的只读健康检查，在本机仓库根目录运行：

```bash
ssh -o BatchMode=yes -o PreferredAuthentications=publickey -o ConnectTimeout=15 hypertest-one 'hostname'
bash ops/check-remote.sh
```

[健康检查脚本](../ops/check-remote.sh)检查 API、worker、生产 Web、nginx 的服务状态，PostgreSQL 容器健康与实际 SQL 查询，以及 API 健康响应、worker 心跳和 Web HTTP 状态。任一项失败返回非零退出码；SSH 认证失败同样返回失败，不进入密码交互。该结果只说明平台运行状况，不代表真实 Agent 测试周期已通过或获得 `RELEASE_READY`。

2026-10-18 21:29（Asia/Singapore）已通过该脚本实测：四项 systemd 服务 active、数据库 healthy 且 `SELECT 1` 成功、API 直连和代理健康、worker 可用且 active_workers=1、Web 直连和代理均 HTTP 200。该次实际 release 为 `0a2af9c4f5034c118f1a19abd786290f0959a648`；以后仍以每次远端检查结果为准。

后续自动检查与新建运维脚本统一沿用上述别名和密钥参数，不再使用临时目录中的 `SSH_ASKPASS`。此前失败是默认公钥未获授权，而 `BatchMode=yes` 又禁用了密码交互；密钥安装后该问题已解决。不要在全局 SSH 配置中禁用密码登录。

需要人工密码恢复时，在本机终端执行，由操作者输入现有密码：

```bash
ssh -o BatchMode=no -o PreferredAuthentications=password -o PubkeyAuthentication=no hypertest-one
```

本次配置未修改远端 sshd 的密码认证设置、应用服务或网络白名单。

## 本轮访问方案与最新运行登记

最新用户选择：公网 HTTP `155.138.206.106:8080` 仅允许来源 `45.76.149.233/32`，SSH22及原 `127.0.0.1:8080` 隧道保留。用户已连接 VPN，服务器记录的 SSH 实际 peer 为 `45.76.149.233`；这不替代浏览器 HTTP 实际出口确认。

阶段1已在独立 nginx server 上精确监听 `155.138.206.106:8080`，不是 wildcard/IPv6；UFW 仅增加 `enp1s0`、来源 `/32`、目标 `155.138.206.106`、TCP8080 的精确规则，nginx 同时 `allow 45.76.149.233/32; deny all;`。不信任 Real-IP / PROXY protocol 或来客 XFF；转发身份由 TCP peer 重写，Host 与不安全方法 Origin 检查作补充。API8000、Web后端3000、PG5432及Docker PG映射继续 `127.0.0.1`。此来源许可覆盖共享该 VPN 出口的客户端，不识别个人身份，也不提供应用 RBAC。

已纳入仓库的运维材料：[nginx配置](../ops/nginx/hypertest-vpn-allowlist.conf)、[受控激活脚本](../ops/activate-vpn-allowlist.sh)、[受控回退脚本](../ops/rollback-vpn-allowlist.sh)。它们已用于阶段1受控启用，实际协议检查见[73d部署报告](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/server-pr4-deployment-2026-10-17.md)。后续重新启用仍需最终Web版本/CI、精确应用SHA、配置SHA、来源确认及root指令。范围补丁的应用版本切换不应重复添加ACL规则；实际变更以最新交付登记为准。维护锁内核对前置状态、空闲任务和原回环配置；不改应用数据、OAuth或原 SSH 规则。这里只说明操作边界，不要求现在执行。

阶段1本地 **9文件/15UI检查**、**20前端回归**与生产HTTP Project/Run/Job、605字节编辑稿/hash均已实际验证；公网允许HTML/API/13静态资源、Host/Origin、非允许peer及伪造转发头、原SSH隧道均有实际记录。手机非VPN失败与同窗UFW BLOCK是关联证据，不声称精确手机源IP归属。

首轮真实Run `01a14a80-f686-7ae1-86a9-5624fd2ce8a5`接受10Req/6Risk/8Case后，因两Runner guard Case不属于被测pypa代码而由模型如实返回PARTIAL；6条实现Proposal被拒绝并保留，0Canonical Implementation/Execution/Evidence/Verdict，Run BLOCKED。不能把HTTP/导入成功当作模型整链通过。

阶段2已修改runtime/codex的provider-independent范围说明，规范以[领域§12](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md#12-requirement)/[TMP§9](protocol/TEST_MISSION_PROTOCOL.md#9-mission-context)为准；不是阶段1“后端等d20/302”的复用。新冻结源码manifest `4e6447f0b851c197b8634ad16e01c9e6506a2c5d540fd6a97027213f9cb50c90`已通过 **303后端/3 warnings/48.70s**、fresh Web20/typecheck/build/audit0、Ruff和独立测试库0008，无新增迁移。精确新应用SHA/CI/切换与相同605字节PRD的fresh-Project真实复验以[最新交付登记](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/prd-import-vpn-acceptance-2026-10-17.md)为准；原失败Project/Run/Canonical历史不删除、不退役、不接受PARTIAL，不预写新模型通过。`RETRYING`显示为等待重试 / Awaiting retry，不代表仍有Worker运行。

网络回退仅删除精确新增 UFW 规则、禁用受控 nginx 站点并测试/reload，保留原回环站点与SSH；支持精确 Hash 的中途恢复状态，异物拒绝。最终必须核对公网监听/规则已消失、SSH/隧道和后端回环保留；失败就记录回退未完成。网络回退不恢复数据库或重启应用，nginx graceful reload 可让已存在请求排空。

## 阶段1 73d部署与d20历史基线


- 阶段1已部署：`73dff989b87fa7349d9b36bd8416ece948a82212`，目录`/opt/hypertest/releases/73dff989b87fa7349d9b36bd8416ece948a82212`；后续scope修复SHA/切换以最新交付登记为准。
- 更早d20选择（历史）：`/opt/hypertest/current` → `/opt/hypertest/releases/d20a2bc78c2f57b3bc2835cdf253d021f6b8265a`。
- d20 部署保留的回退版本：`/opt/hypertest/releases/2b3602507e42a25ee7aa21f15a57db454bd73736`；更早版本和真实链记录继续保留。
- 服务账号及实际home：`hypertest`，`/var/lib/hypertest`。
- 共享配置：`/etc/hypertest/hypertest.env`（root:hypertest0640）；PG初始化凭据：`/etc/hypertest/postgres.env`（root0600）。
- Canonical Artifacts：`/var/lib/hypertest/artifacts`；测试仓库：`/var/lib/hypertest/workspaces`；Codex正常可写runtime：`/var/lib/hypertest/.codex`。
- Python3.12.15；Node22.23.3；官方Codex0.163.0；Docker26.1.5；PostgreSQL17.11容器`hypertest-postgres`、volume`hypertest_pgdata`。
- 数据库head：`0008_job_ownership`。首次完整0001→0008升级与d20切换已核验；d20无新增迁移，没有降级/清库。范围补丁亦无新增迁移；其独立测试库检查与实际正式库状态分开登记。
- 可信Runner：`hypertest-runner:py312`，image ID `sha256:a8f6f769b6b6a34ed6e6968b6c9816c17d860fbb38445c2473d3544addd20b56`。已由服务用户实际运行禁网/只读/nonroot/cap-drop/512MiB/1CPU容器验证。

d20 合并源码 tree 与 2b 完整相同，既有 302 项结果与独立 Web 检查按记录复用，main CI通过；d20 新安装、定向11项和数据保全已验收。记录见[main部署](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/main-pr3-sync-deployment-2026-10-17.md)、[API保全](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/main-pr3-sync-preservation-2026-10-17.md)。这些是本轮前历史基线，不能证明新 UUID/导入修复或公网已验收。

应用服务均已enable；API与Worker共用正式数据库、Artifact Store和Workspace Root：

```bash
systemctl status hypertest-api hypertest-worker hypertest-web nginx
systemctl is-active hypertest-api hypertest-worker hypertest-web nginx
journalctl -u hypertest-worker --since today
curl -fsS http://127.0.0.1:8080/api/v1/health
curl -fsS http://127.0.0.1:8080/api/v1/capabilities
```

unit文件在`/etc/systemd/system/hypertest-{api,worker,web}.service`。使用一进程API、一个独立Worker、Next生产服务器，无reload/dev服务器。nginx站点为`/etc/nginx/sites-available/hypertest.conf`。

## 访问与现有隧道

d20时代仅SSH22公网监听属于历史。阶段1 73d已启用精确公网155.138.206.106:8080及唯一来源45.76.149.233/32规则；nginx原127.0.0.1:8080与SSH保留，API8000/Web后端3000/PG5432仍回环。后续scope版本切换的实际监听/防火墙/保全结果以最新交付登记为准。

当前可继续使用本机隧道：http://127.0.0.1:8080 。d20同步记录的隧道PID为`25603`；它是当时的进程身份，不保证日后不变。操作前检查当前转发进程和健康，只关闭自己确认的隧道，不沿用旧PID。原始92044/9255等隧道记录保留为历史。

以后在本机终端重新建立（终端保持打开）：

```bash
ssh -N -o BatchMode=yes -o PreferredAuthentications=publickey -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8080:127.0.0.1:8080 hypertest-one
```

原有known_hosts与远端Ed25519公钥指纹已一致核验：`SHA256:PoYUrSTDnN10A010My98ydOX3HQq/FynK/VxU9T5AqI`。

## 由操作者亲自完成OAuth

用户已亲自完成OAuth；2026-10-17最新只读检查返回 **Logged in using ChatGPT**（exit0）。安装/验收Agent没有执行login，没有读取或复制任何auth内容。以下保留日后需要重新认证时的精确操作；当前无需重复登录。

先从本机进入你已经验证过的服务器终端：

```bash
ssh hypertest-one
```

再在服务器root终端执行，让CLI在正确服务账号下完成device OAuth；按CLI提示在自己的浏览器完成授权：

```bash
runuser -u hypertest -- env PATH=/opt/hypertest/node/bin:/opt/hypertest/codex/bin:/usr/bin:/bin \
  codex login --device-auth
```

只读检查：

```bash
runuser -u hypertest -- env PATH=/opt/hypertest/node/bin:/opt/hypertest/codex/bin:/usr/bin:/bin \
  codex login status
```

日后重新认证完成后，可从Web继续提交真实模型任务。API/Worker使用同一hypertest账号runtime，不需要复制凭据或改root账号。服务已启用`HYPERTEST_CODEX_IGNORE_USER_CONFIG=true`；适配器显式使用read-only沙箱和结构化结果契约。

未认证HTTPS探测已证实TLS可达；api.openai.com/v1/models返回401，chatgpt/auth主页返回403。这不等于真实模型调用验收，也不能据此判定凭据失效。随后用户完成OAuth，真实Codex/Docker通过与失败诊断双链均成功，已经建立服务端模型可用证据。

## 备份与已验证恢复

脚本：`/opt/hypertest/deploy/backup.sh`。定时器：`hypertest-backup.timer`；每天03:30UTC加0–20分钟随机延迟，即新加坡11:30–11:50。已enable且persistent。历史备份不自动删除。

```bash
systemctl list-timers --all hypertest-backup.timer
systemctl start hypertest-backup.service
systemctl show hypertest-backup.service -p Result -p ExecMainStatus
```

脚本在空闲窗口短暂停止API接收新工作，检查queued/running任务；有工作则跳过，空闲时暂停Worker，配对备份数据库和Artifacts并恢复先前服务。保护锁防止与部署并行。密码/OAuth/源checkout不进入这两份数据档案。

首次真实模型验收时的已完成备份：`/var/backups/hypertest/20261017T110027Z`，包含生产Web真实创建的Project与Run及PRD Artifact；`database.dump`、`artifacts.tar.gz`的SHA256均通过。核对命令：

```bash
cd /var/backups/hypertest/20261017T110027Z
sha256sum -c SHA256SUMS
```

该次真实数据备份已执行实际隔离恢复：DB`hypertest_restorecheck_20261017110028`，恢复head0008_job_ownership；Artifacts解包到`/var/lib/hypertest/restore-check/20261017T110027Z/artifacts`。恢复SQL核实2Project/2Run/2Execution/8Evidence/3FINAL/1Finding/3Job，activeJob=0。Python从这个解包目录实际读取字节，验证15个引用、12个唯一Artifact，涵盖Evidence SHA/size、所有Implementation source_sha256、PRD/config input hash。正式库及正式Artifact目录未被恢复覆盖。证据为`server-final-restore-2026-10-17.json`；数据库/Artifacts必须使用同一时间戳配对。

d20切换时最新配对备份为`/var/backups/hypertest/20261017T143150Z`，dump和Artifacts checksum已核验，证据见main部署记录。本轮新版本/网络变更的备份和保全结果以最新交付登记为准；不能把旧恢复演练写成新备份已再次演练。

## 升级、保留与回滚边界

原始HANDOFF及原始归档保持不变。首次交付适配Debian13的可重跑材料在服务器`/root/hypertest-deploy-final-89d15ae`及本机`hypertest-one-89d15ae-debian13-deploy.tar.gz`。该归档SHA256：`04a53491b72ea3ba4da36485f0090c13b99e5fc5f4e09f024a70a9d956b6b3c8`。先核验目录内SHA256SUMS；其源码bundle固定89d。prepare与ACTIVATE分阶段，不能把准备完成当成已激活。

升级应先核实完整SHA、独立库测试、当前配对备份及没有活跃任务，再选择新release并重启服务。保留旧release、配置、数据库volume、Artifacts和OAuth；不在current覆盖源码，不执行强制reset/clean，不降级或删除canonical历史。

历史89d只改Python/TMP/tests。Web所有tracked源码/配置/lock与5b完全相同，经git差异与文件树hash核对复用了已通过npm ci/typecheck/build的生产产物；.next产物树SHA256：`25c0e566293a27b651b1fdce2ffcf8b0a7b335acb26dcc94e25a7d18c161a174`。新Python环境独立构建。

应用回滚仅选择已保留且验证可启动的旧release、恢复之前活跃服务；不自动回滚schema。存在活跃任务时先审查并受控停止，不能静默重放执行。正式库需要恢复时，先在隔离库核验备份与同时间Artifacts，再由操作者决定正式恢复。

## 历史首次实际验收与当时状态（5b / 89d）

- 5b在服务器：ruff、独立空库0001→0008、**208 passed**、npm ci/typecheck/build均通过。
- 89d在服务器：ruff、另一独立空库0001→0008、**212 passed，3 warnings，142.49s**。Web输入无变化，复用上述验证产物；无新增正式迁移。
- 两版本实际检查health、数据库projects、Worker heartbeat、生产HTML。89d API/Worker/Web实际cwd均属于89d release，tracked源码clean；Worker available=true且active_workers=1。
- 生产Web创建的Project`01a14972-275a-7c29-a10d-9bb709e150d5`及Run`01a14972-ca09-7f60-9b75-a63ae8bdc74e`在升级后身份完整保留。前后快照在本交接目录`server-upgrade-preservation-{before,after}.json`。
- 已准备真实应用source，无预置测试或Agent结果；manifest为`server-live-fixture-2026-10-17.json`。正确commit3654e6b656b6ae70301de797a533382b210fd0e5，错误commit8baa49cbb67956e99bd8c6a9a732ff81db9105e2。
- **服务端真实Codex CLI→canonical→OFFICIAL Docker→Evidence→Verdict两条链均通过验收。** 正确source：7Req/7Risk/11Case/1Implementation/1Execution/4Evidence，Run COMPLETED，最终RELEASE_READY；旧BLOCKED FINAL保留，sequence2追加新结论。错误source：8Req/8Risk/12Case/2Implementation/1Execution/4Evidence/1Finding，DIAGNOSE_FAILURE实际完成，最终RELEASE_BLOCKED；Finding保留NEW供用户triage。
- 9个真实Codex Mission均Attempt1 ACCEPTED。SnapshotHarness是临时source wrapper，内部使用真实Codex CLI；没有预设Agent结果。两次OFFICIAL执行均由可信Docker Runner产生事实。
- SQL核心关系链JOIN为pass92/fail56，包含Finding的失败完整链JOIN15；pass62Audit/62Outbox、fail69/69，逐实体事件分组差异0。Outbox归属使用payload Run或Audit entity/action关系，避免漏掉没有payload.test_run_id的执行/证据事件。Attempt/Execution的durable_job同Run归属异常0，accepted Proposal缺entity=0。
- 两原始source checkout保持固定commit且git status为空，只含PRD.md/checkout.py；真实执行后的受控Docker容器和volume残留均0。

首次验收的最终备份正常重启空闲API/Worker后，当时PID为API21637、Worker21639、Web14401；三服务NRestarts=0，实际cwd均属于89d。真实模型Jobs由此前Worker14947执行，历史记录保留。该次readiness为health ok、HTML200、Worker available=true/active_workers1、activeJobs0；Codex login status为Logged in using ChatGPT。主机最后可用约3GiB、盘余56GiB，近期服务ERROR/Traceback和内核OOM计数均0。结构化最终状态：`server-final-state-2026-10-17.json`。

详细阶段日志、hash和恢复证据见同目录`server-acceptance-2026-10-17.md`、`server-tests-89d15ae.log`、`server-readiness-89d15ae.log`、`server-final-backup-2026-10-17.log`。
