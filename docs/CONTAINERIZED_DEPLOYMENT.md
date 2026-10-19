# ADR-013 容器化部署与恢复

当前访问规则（2026-10-19）：用户 Web 仅走既有跳板机来源白名单；SSH 保留运维
登录，停用转发与 Web 隧道。真实地址留在服务器受保护配置中，示例使用文档地址。
首次启用或 ACL 变更做一次外部允许/拒绝验收；日常部署核对 ACL 有效与内部就绪，
不反复进行手机/VPN 连通性检查。本文末尾首次切换记录保留当时边界，不能用其旧
隧道步骤恢复另一用户入口。配置的实际激活结果须独立登记。

本目录实现单 Linux 宿主的生产打包边界：nginx / Web / API / Task Worker /
PostgreSQL 使用固定镜像，Provider CLI、原生认证和 Host Harness Bridge 保留宿主。
开发用 `docker-compose.yml` 继续独立；生产使用 `compose.production.yml`。
本文是容器栈的操作材料。2026-10-19 的正式切换、实际应用/迁移/Bridge 版本、
保全检查和真实测试周期另见[正式部署验收](ADR013_PRODUCTION_DEPLOYMENT.md)，
不能仅凭本文中的配置或命令推断某项验收已经完成。

领域/协议仍由四份奠基文档和 [ADR-013](architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)
定义。Job 完成、容器 healthy、Bridge 连通都不能替代正式 Runner / Evidence / Gate。

## 权限与持久目录

| 服务 | 数据/接口 | 不授予的宿主能力 |
|---|---|---|
| nginx | 只读生成配置，宿主网络，非 root 监听两个明确 IPv4 地址 | DB、Docker、Provider、Artifact |
| Web | 构建产物，容器内 API HTTP | DB 凭据、宿主文件、Docker、Provider |
| API | PostgreSQL、Artifact、受控源码工作区；Worker 实时能力请求走 PostgreSQL | Docker socket、Bridge signing key / socket、Provider CLI / auth |
| Worker | PostgreSQL、Artifact、受控源码/会话工作区、Docker、Bridge UDS 和窄授权 key | Provider CLI / auth |
| 宿主 Bridge | 原生认证/会话、独立操作 ledger、仅受控 Agent 副本、UDS | Canonical DB、Docker、Artifact Store、GitLab 凭据 |
| PostgreSQL | 既有 external volume | 自动创建/删除原数据卷 |

API 暂保留 Git 与受控源码目录读写，用于兼容已有 pinned checkout 接口；它没有
Docker CLI 或 Provider CLI。正式执行/能力查询由可信 Worker 处理。Worker 具有
Docker 管理权限，因此它属于受信平台组件，不能把其 socket 继续挂给测试容器。

所有生产 bind mount 使用 `create_host_path: false`，防止路径拼错时创建空目录造成
“原数据消失”的假象。宿主与 Worker 的 workspace **绝对路径相同**，否则宿主 Docker
或 Bridge 会解析到错误目录。Artifact 与 workspace 必须分别持久保存且不能嵌套。
API / Worker 以现有服务 UID/GID 运行；先 `id hypertest` 和检查目录权限，不自动
递归 chown 旧库、Artifact、暂停副本或认证文件。

Bridge 的专门 systemd unit 不加载原平台 `hypertest.env`；只接受
`bridge.env.example` 中的配置。它保留原服务用户 HOME/CODEX_HOME，因此不复制 OAuth。
`ProtectSystem`、`InaccessiblePaths` 和 `IPAddressDeny` 约束平台目录、Docker 与
本机/私有网段数据库访问。安装后必须检查 systemd 实际应用这些限制；需要内部代理
时先审查窄例外，不能整体取消 DB 隔离。

本实现的受控 Codex 工具 profile 关闭 native shell / unified exec / multi-agent /
web search，源码与领域事实经平台限定工具提供。Bridge 与 Provider 同 UID 时，单凭
环境变量过滤或 read-only sandbox 不足以防读取 Bridge key；因此不能擅自重新开放
任意宿主 shell。未来启用前需完成独立操作系统身份/文件系统权限隔离与负向验收。

## 固定镜像和配置准备

操作前使用 [服务器 SSH 约定](SERVER_OPERATIONS.md#ssh-access)。脚本不会自动修改
UFW、执行 OAuth 登录或删除原数据；正式切换必须遵循后文的维护与保全步骤。

在经过测试的 release checkout 执行：

```bash
bash ops/container/build-images.sh /absolute/new/images.env
```

脚本显式拉取构建用 Python3.12 / Node22 / Docker CLI / PostgreSQL17 / nginx 基础镜像，
先解析 registry digest，再构建 API / Worker / Web；最终输出实际本机 image ID。
平台依赖在构建时安装，运行期间不 build / pull / npm install / pip install。
输出文件不覆盖既有文件，不包含凭据。CPU 架构必须与目标宿主一致；Mac arm64 构建
不能直接当成 Debian amd64 发布，目标机构建或经验证的同架构 CI 产物分别登记。

`compose.production.yml` 没有 `build`，全部 `pull_policy: never`。部署验证器拒绝裸 tag，
仅允许 `sha256:<64hex>` 或 `repository@sha256:<64hex>`，并实际检查本地镜像存在。
基础镜像 digest 与最终应用 image ID 不是同一种身份。维护旧 release 镜像和历史
Runner image ID；不要 `docker system prune`。

从 `ops/container/compose.env.example`、`platform.env.example`、`bridge.env.example`
复制到新 release 的受保护配置目录。compose.env 只包含路径、image ID、账号数值和
端口，不能放密码；platform.env 保留原用户名/数据库/密码，只把 DB 主机改为服务名
`postgres`，密码仍 URL 编码。PostgreSQL 沿用原 `postgres.env` 和
`HYPERTEST_POSTGRES_VOLUME=hypertest_pgdata`，不重新初始化。

- 平台共用 `HYPERTEST_EXECUTION_MODE=queued` 和 `HYPERTEST_HARNESS_MODE=bridge`。
- Worker 的 Bridge key 只从文件挂载，API 不挂载；两把独立随机 key 至少 32 bytes。
- 原生 OAuth 和 session 仍留原宿主目录，不放镜像、env、备份日志或 Agent Context。
- `HYPERTEST_BRIDGE_HOST_ID` 是稳定节点身份，不能用当前容器 ID 替代。
- Bridge 的 workspace root 是平台 workspace 下的 `.hypertest-agent-sessions`。
- 配置中的 UID/GID、Docker socket group、专用共享 Bridge group 来自实际主机。
- Bridge state 目录 0700；socket 父目录 0770，socket 0660。挂载父目录使重启替换的
  socket 对 Worker 可见。unit 使用 `RuntimeDirectoryPreserve=yes`，停止 Bridge 不删除
  共享父目录；首次部署或重启后显式准备该目录，或先启动 Bridge 再运行数据库阶段。
  不要只挂载某次创建的 socket inode。

在新路径生成 nginx 配置（拒绝覆盖已有文件），之后作完整预检：

```bash
python3 ops/container/stack.py --env /absolute/compose.env render-nginx
python3 ops/container/stack.py --env /absolute/compose.env validate
python3 ops/container/stack.py --env /absolute/compose.env config
```

`--offline` 只做 schema 检查，不能作为运行环境、镜像、卷、权限或就绪证明。
不要把含 secret 的 `docker compose config` 展开输出贴到日志；上面 `config` 使用
`--quiet`。实际生产 build / preflight 的完整 Git SHA、image ID 与配置 hash 应单独记录。

受控 GitLab 集成是可选项。启用时在宿主受保护目录
`/etc/hypertest/container/gitlab` 放 `policy.json` 与对应 token 文件，目录只允许
root 与 Worker 身份读取，token 不可 world-readable。在 compose.env 增加
`HYPERTEST_GITLAB_POLICY_DIR=/etc/hypertest/container/gitlab`，由本目录启动/检查/备份工具自动加入该 overlay；手工 Compose 操作也必须增加
`-f ops/container/compose.gitlab.yml`。先以 `config --quiet` 验证合并结果。
该 overlay 仅给 Worker 只读挂载目录，policy 中 `token_file` 使用容器绝对路径
`/run/hypertest-gitlab/<project>.token`。API/Web 没有此挂载，Bridge unit 明确禁止访问
宿主目录；若改用其他宿主路径，必须同步增加对应的 `InaccessiblePaths`。
平台仍按 Project policy 和结构化操作权限控制实际 GitLab 调用，安装 overlay
本身不授权创建真实 Issue。备份与恢复脚本不复制这些平台凭据。

## 网络边界

nginx **仅**使用 `network_mode: host`，公网监听地址/端口取自受保护的
`HYPERTEST_PUBLIC_IP` / `HYPERTEST_INGRESS_PORT`；公网 server 只允许
`HYPERTEST_VPN_CIDR` 配置的单个 IPv4 `/32`，其余 `deny all`。该值来自现有已授权
配置，不由 Web/Agent 提供，不自动增加来源或扩大网段。同时保留既有精确 UFW
INPUT 规则。nginx 无 `ports:`，因此公网入口没有 Docker DNAT
绕过原 INPUT 白名单的问题。API/Web/PostgreSQL 只映射 host loopback；没有 wildcard
或 IPv6 公网绑定。生产回环 nginx 只提供精确 `GET` / `HEAD /api/v1/health`；
其他方法或路径一律拒绝，不能通过它访问 Web、capabilities 或业务 API。隔离验收
使用 `HYPERTEST_PUBLIC_INGRESS=disabled`（生成配置只监听 loopback，提供完整隔离
Web/API），并修改四个宿主端口以避开正式服务。正式环境保持 `enabled` 与原白名单，
不能用 staging 配置替换正式入口。生成新 nginx 配置使用全新目标路径，先核对原
白名单现值，再测试并在维护窗口切换；不要直接覆盖已有 bind mount 文件。

nginx 使用真实 TCP peer 作为 ACL 和日志身份，不信任 Real-IP、PROXY protocol、
来客 X-Forwarded-For / Forwarded。转发时覆盖身份头，公网 Host / unsafe Origin 再作
约束。Docker 内网和 loopback 端口不是用户访问入口。

实际宿主仍为 Docker26.1.5；[Docker 官方说明](https://docs.docker.com/engine/network/port-publishing/)
指出 28 之前的 localhost published ports 可能被同二层网络主机访问，因此仅检查
`127.0.0.1` 绑定不足。`network_guard.py` 在已创建的、本 Compose 项目所属的 IPv4
bridge 上安装一条带唯一标记的 DOCKER-USER 规则：拒绝其他接口转发进入该桥的
非 ESTABLISHED/RELATED 连接。宿主 OUTPUT、同桥容器通信及已建立的返回流量保留。
脚本拒绝不属于本项目的网络和未另行验证的 IPv6 bridge，不清空任何链、不修改
原 UFW/SSH 或其他 bridge；`remove` 只删除精确匹配的自有规则。检查同时要求该
规则为 DOCKER-USER 的第一条规则，防止前置 RETURN/ACCEPT 提前放行；install 仅
将精确匹配的自有规则移到首位，保留所有其他规则的内容和相对次序。

所有服务固定 `restart: "no"`，禁止 Docker 绕过守卫自行恢复端口。`start.py` 检查
实际 daemon `LiveRestoreEnabled=false`、完整 Compose 和既有容器的 restart policy；
不满足就拒绝启动，不自动修改 daemon 配置。每次启动先停止本栈，再以停止态创建
容器/网络，安装并验证自有规则，最后 `compose start` 并轮询实际容器健康状态（不依赖 start 的未支持参数）；daemon 在过程中变化
或守卫失败会停止本栈。它不运行迁移，也不停止其他项目。

安装 `hypertest-container-stack.service` 前替换其中 release/env/lock/Bridge unit 路径。
该 unit `After/Requires/BindsTo=docker.service`，并 `Wants/After` Host Bridge；
`ExecStartPre` 要求 Bridge 已 active 后才允许启动平台。Bridge 不再位于 `Requires`，
防止冷备显式停止 Bridge 时连带触发 stack 的 `ExecStop`，重新争用同一维护锁。
Worker 的 Bridge 准入和真实 capabilities 仍须通过，Bridge 不可用不能报告完整就绪。
每次宿主开机都重新通过守卫启动，
而非依赖 iptables 规则持久化。正式启用前先手动执行同一入口验证：

```bash
python3 ops/container/start.py --env /absolute/compose.env \
  --lock /run/lock/hypertest-maintenance.lock start --postgres-only
# 显式的一次性迁移完成后：
systemctl start hypertest-container-stack
# 验收通过后，才启用开机启动：
systemctl enable hypertest-container-stack
```

如果已有本栈容器来自旧的 `unless-stopped` 配置，先停止本栈并明确执行
`docker update --restart=no <逐个核验的本栈容器ID>`；入口会拒绝不安全既有容器。
Engine 重启导致本栈停止后，操作者用 `systemctl restart hypertest-container-stack`
恢复（不是直接 `compose up`）；应用意外退出也以此受控入口恢复。本方案选择安全停止，
不承诺应用自动重启。停止后才可用 `network_guard.py ... remove` 删除精确自有规则。
未在共享生产 Engine 上执行真实 daemon/宿主重启试验，不能将静态约束声称为实机
重启验收。正式 stack 和 Bridge 已启用开机启动，独立 staging 保持停止；
生产 Docker / 宿主实机重启仍未执行。

首次安装或访问策略变更时实测白名单入口 HTML/API/静态资源可用、非白名单拒绝
（伪造 XFF 也拒绝）、内部端口无公网旁路；核对正常 SSH 管理登录及新转发被拒绝。
既有允许/拒绝证据保留，不将历史结果改写成新策略已经验收。

常规应用部署核对实际配置与既有 `/32` ACL、UFW 和 Docker 守卫继续有效，再做
内部 readiness 即可；不用每轮重复手机/VPN、公网多出口、SSH 隧道或密码登录测试。
`readiness.py` 比较实际挂载的 nginx 配置与受保护配置的渲染结果，直接请求内部
API/Web、nginx health；capabilities 走内部 API，不依赖回环业务入口。该比较不
冒充首次实际公网允许/拒绝验收。网络策略修改保留回退记录，不重放旧 activate
脚本或添加重复规则。

### SSH 仅作运维

使用仓库中的 `ops/ssh/00-hypertest-no-forwarding.conf` 作为 sshd drop-in：

```text
DisableForwarding yes
AllowTcpForwarding no
AllowStreamLocalForwarding no
PermitTunnel no
```

安装前保持现有管理 SSH 连接打开，确认 `/etc/ssh/sshd_config` 在全局段包含
`Include /etc/ssh/sshd_config.d/*.conf`，并运行 `/usr/sbin/sshd -t`。在新的受保护
备份目录保存原主配置、同名 drop-in（若存在）及 `/usr/sbin/sshd -T` 输出；不复制
私钥或认证内容。再安装该文件到 `/etc/ssh/sshd_config.d/00-hypertest-no-forwarding.conf`
（root:root、0644），运行：

```bash
/usr/sbin/sshd -t
/usr/sbin/sshd -T
# 再用现有 SSH_CONNECTION 中的实际连接上下文检查 Match 生效结果：
/usr/sbin/sshd -T -C 'user=root,host=<peer>,addr=<peer>,laddr=<server>,lport=22'
```

全局及 root 实际上下文必须均为 `disableforwarding yes`、`allowtcpforwarding no`、
`allowstreamlocalforwarding no`、`permittunnel no`。认证相关的
`passwordauthentication`、`pubkeyauthentication`、`permitrootlogin`、
`authenticationmethods` 和 `hostkey` 必须与安装前相同，并保留已有公钥/密码登录。
Include 顺序或 Match 规则导致效果不同则拒绝应用，不另行改认证规则。校验失败
立即恢复原 drop-in（原先不存在则只删除新文件），重新 `sshd -t`，不执行 reload。

全部通过后才 `systemctl reload ssh.service`，从本机另开一条严格公钥的新连接验证
管理登录成功，再关闭旧检查连接。reload 不会撤销既有 SSH 连接的旧转发能力；
只结束逐一核对为旧 Web 隧道的本机进程。若需关闭远端旧会话，核对其 PID、完整
命令、peer 与用途，不批量结束 sshd 子进程、不沿用历史 PID、不影响其他管理连接。
用一条新的临时连接验证 TCP / streamlocal 转发被拒绝后关闭该验证连接。此项仅在
策略初次安装或改变时执行，常规部署不重复改 sshd，也不要求操作者重复密码登录。
禁转发不限制受信 root 运维 shell 的管理权限。

## 首次切换与常规升级

维护操作共用 `/run/lock/hypertest-maintenance.lock`。backup.py 自动取得该排他锁；
人工切换窗口使用 `flock` 持锁，并确保旧 backup timer/deploy 脚本使用同一把锁。
在确认既有 timer 的锁路径前，不并行执行备份/迁移。

所有 Compose 命令固定使用同一 release 的文件和 env，例如：

```bash
docker compose --env-file /absolute/compose.env -f compose.production.yml ps
```

需要独立发布运维修复时，保持业务 `container-current`、Bridge 与运行镜像身份不变，
把 `ops/container` 和所需 Compose 文件打包到
`/opt/hypertest/ops-releases/<manifest-digest>`，保留每文件 SHA-256 与来源 provenance。
运维包不含生产 env、OAuth 或密钥；未提交快照须明确记录，不能宣称来自 main。
`ops-current` 原子指向固定包；stack 的 ExecStart/ExecStop、backup 的 ExecStart
通过窄 drop-in 使用该入口，其余 unit 依赖、工作目录、维护锁和 timer 不变。
`check-remote.sh` 优先用 `ops-current`，仅在此入口从未配置时兼容业务 release；
断链或不完整入口必须失败。构建镜像仍从完整业务 release 执行，不从此运行运维包构建。

新 nginx 与新 readiness/backup 在同一维护窗口切换。维护程序持有既有排他锁时，
按 scheduled backup 的方式调用受控 `start.start()`，不能在该锁内再执行会获取
同一锁的 `systemctl restart` / `start.py` CLI。先停止 API 接收新工作、复核没有
活动请求；忙时恢复 API 并退出，不中断 Worker。失败恢复原 env、ops symlink 和
unit drop-in，再以原运维代码受控启动并核对就绪。原业务源码、镜像、数据库和
历史文件均不回写，应用与运维身份分开登记。

切换窗口必须有同一时间的配对备份、隔离恢复和新 image 的检查结果。现有服务器
systemd API/Worker/Web/nginx 与生产端口不能并行争抢；原 PostgreSQL 容器也不能和
Compose 同时挂载同一个 PGDATA。只停止明确核验的旧服务/容器，保留它们以供回退。

顺序：

1. 固定 Git SHA / 镜像 / Bridge package 版本与配置。核查源工作区 clean、测试/迁移
   结果、磁盘、Docker、UID、原卷和 Artifact 清单；记录原 systemd 服务及现有监听。
2. 停止旧 API 接收写操作，排空任务。**旧 profile 的 WAITING_INPUT 不能转交新持续
   会话 Worker**；应先在旧版本完成回答/取消，或继续保留旧环境服务到该任务完成。
   任何暂停任务未处理时不迁移该环境，不删副本，不伪造主 Session 绑定。
3. 确认无 QUEUED/RUNNING/CANCEL_REQUESTED/旧 profile WAITING_INPUT，停止旧 Worker。
   配对备份并隔离恢复。确认保留原 Provider runtime 和托管副本。
4. 完成上一节版本/网络防护核验，先按配置 UID/GID 准备所有新 bind 目录（包括 socket 父目录）；
   停止旧 PostgreSQL 容器后再让 Compose PostgreSQL 独占既有 external volume：
   `start.py --env ... --lock ... start --postgres-only`。DB 可用后单独执行 `... --profile maintenance run --rm migrate`。
   迁移任务一次性成功并核对 Alembic head，API/Worker 启动本身不自动迁移。
5. 按已核验 UID/GID 创建共享 socket group、新 state 目录和 agent-sessions 目录（只
   设置新目录权限，保留旧目录内容/owner）。安装与应用兼容的独立 Bridge venv 到新版本目录，切换经过核验的 bridge-current，
   加载专门 unit/env，执行 `systemctl start hypertest-harness-bridge`。
   仅安装兼容包不执行 OAuth 登录。确认 UDS/身份/协议能力和 key 权限。
6. 停止旧 nginx 并核验端口释放后，`systemctl start hypertest-container-stack`。
   受控启动不含 migration；不要绕过守卫直接 `up`，也不要用 `up --build`。
7. 完成下一节真实就绪与数据保全检查，按变更风险观察服务，再登记实际激活版本。

新持续 profile 的 WAITING_INPUT 在平台升级时仍需要保留原 Bridge state/native
session/workspace，以及兼容代码/协议，停止 Provider 后才能做配对备份；不能把
暂停解释为可删除或可新建 Session。恢复前验证原绑定和 fenced generation。

## 就绪与数据核验

`stack.py status` 返回 Compose 状态。API healthcheck 同时请求 /health 与执行真实
`SELECT 1`；Worker healthcheck 检查**本容器 hostname**对应的数据库心跳，不能拿
其他 Worker 的心跳掩盖失联实例。Web/入口分别检查 HTTP。Bridge 故障和 Runner
镜像缺失必须通过平台实际 capabilities/environment 请求呈现，不能靠静态配置报告可用。

使用 `python3 ops/container/readiness.py --env /absolute/compose.env` 核验实际容器
健康、PG 卷、API 的 CLI / socket 边界、loopback HTTP 与 Worker 返回的真实 Bridge /
Docker 能力。隔离环境增加 `--bridge-service hypertest-adr013-staging-bridge`。
此命令不提交测试 Run；capabilities 请求会写入独立 Operational 控制队列。
输出明确区分首次公网边界、旧数据和真实测试周期的独立证据；日常升级无需重复
外部连通性验收，内部 readiness 也不替代真实测试结果。

核验安装镜像内 API/Web 不含 Codex、API 不含 Docker；`docker inspect` 核对挂载、
只读根、非 root、cap_drop、无 host auth。Worker 有 Docker/Bridge 且无原生认证。
Bridge systemd 环境与权限不包含平台数据库、GitLab 或 Docker 能力。记录真实
Provider session 身份、跨 Mission 复用、等待/回答/重启及旧 owner 拒绝结果。

升级前后逐项核对原业务行/关系/历史、所有 Artifact SHA 与 size、托管源码与暂停
副本存在、已发布 Verdict state/evidence hash、PG 卷身份、原 OAuth 只读 login status。
就绪检查不应新建 Canonical 测试记录；另建明确的验收 Run 做真实 Provider → Docker
→ Evidence → Gate 成功/失败/问答链路，其记录不能代替旧数据保全。

## 配对备份与隔离恢复

`ops/container/backup.py` 只在 API/Worker/migrate 和 Bridge 都已停止、无正在执行/排队
任务时生成新备份目录。它保留 WAITING_INPUT 的 DB、工作副本和 Bridge ledger；
备份内容为 database.dump、artifacts.tar.gz、workspaces.tar.gz、bridge-state.tar.gz，
以及 hash manifest / COMPLETE 标记。脚本不停止/重启服务、不删除失败备份、不删除
历史备份、不读取或复制 OAuth。暂停期间的原生 Provider session 仍保留宿主原位置；
整机灾难恢复另需操作者管理的加密 Provider runtime 备份，不能从此数据备份凭空恢复会话。
隔离 staging 使用自己的 `--bridge-service hypertest-adr013-staging-bridge` 与
`--lock-file`；不通过正式 Bridge 的停止状态推断 staging Bridge 已停止。

正式切换时必须同步替换旧 `hypertest-backup.service` 的 `ExecStart`，保留既有 timer
时间与随机延迟；旧脚本硬编码宿主 API/Worker 和 `hypertest-postgres`，不能用于新栈。
新入口为：

```bash
/usr/bin/python3 /opt/hypertest/container-current/ops/container/scheduled_backup.py \
  --env /etc/hypertest/container/compose.env
```

该 wrapper 要求完整栈与 Bridge 已健康，只在进程内持有一把维护锁，不嵌套执行
`start.py` / `backup.py` CLI 或 stack unit 的 ExecStart/ExecStop。先关闭 API 写入口；
存在排队、执行、取消中的 Job 或未完成 runtime control 请求时，仅恢复 API 并跳过，
不停止 Worker。空闲时停止本栈容器和 Bridge，用同一守卫恢复 PostgreSQL-only，调用
配对备份内部方法，再恢复 Bridge 与完整栈。新 profile 的 WAITING_INPUT 原绑定、
workspace 与 ledger 纳入备份，原生 Provider runtime 仍在原宿主目录保留。
备份失败保留未完成目录并尝试恢复原健康服务；恢复后必须通过实际 readiness，
失败返回非零并停止本栈监听，不能把生成了备份目录作为成功。锁被占用时安全跳过。

启用 timer 前必须实测空闲期 `systemctl start hypertest-backup.service`：新配对目录
具有有效 COMPLETE / manifest，Bridge active、五个容器 healthy，原数据不变；另在
独立验收栈验证忙任务只暂停 API、原 Job / Worker / native Session 不被中断且不产生
新备份。不可在正式真实验收 Job 运行中为了测试备份而中断其会话。

```bash
python3 ops/container/backup.py --env /absolute/compose.env backup \
  --output /var/backups/hypertest/NEW_TIMESTAMP \
  --bridge-state /var/lib/hypertest-harness
python3 ops/container/backup.py --env /absolute/compose.env restore-verify \
  --source /var/backups/hypertest/NEW_TIMESTAMP \
  --output /var/lib/hypertest/restore-check/NEW_TIMESTAMP \
  --database hypertest_verify_NEW_LOWERCASE_SUFFIX
```

恢复命令只允许新建 `hypertest_verify_...` 数据库和全新文件目录，校验同一份 manifest
全部 hash，拒绝覆盖原库/目录。**SQL restore 与 archive hash 通过仍不是应用完整性
验收**；需在此隔离库执行新 Alembic、关系/行数/历史hash、Artifact引用读取及代表性
旧结论核验。原PG卷/业务数据从未被恢复覆盖。

## 回滚触发与边界

API/Worker不可用、Bridge协议/原会话恢复不兼容、权限泄漏、旧数据/hash不一致、VPN
拒绝/错误放行或 SSH 失效均停止继续上线。先停止新 API/Worker，确认无外部 Provider /
Runner 残留调用，保留失败/未知结果和审计，再判断可回滚范围。

- 尚无新绑定/协议写入且 schema 向后兼容：保持新 schema，重新选择验证过的旧
  application / Bridge image 或旧 systemd release，恢复原入口；PG同时只能一个 owner。
- 已产生新持续 Binding、RunInputRequest、Call 或其他新语义：**不能**把旧二进制当
  无条件回退版本。使用能读取新 schema/profile 的兼容 release或向前修复，保留会话
  工作区与全部历史。恢复不自动重放未知外部工作。
- 不运行 `alembic downgrade`、`docker compose down -v`、`docker volume rm` 或用旧
  dump 覆盖正式库。正式数据恢复是另一个明确授权的操作，先隔离验证同一配对备份。

nginx回退只是恢复已核验的原host站点/服务；不改 SSH、不清 UFW、不调整 OAuth。
生产迁移前后的实际结果应追加到服务器交付记录，不能把本 runbook 的目标写成已实现
验收事实。

## 首次隔离验证的历史边界（2026-10-19，正式切换前）

该次隔离验证时，正式服务仍为 `0a2af9c4f5034c118f1a19abd786290f0959a648` / schema0012，
正式数据卷、服务 PID、Artifact 清单和 UFW 规则与隔离验证前一致。隔离栈使用
新 `hypertest_adr013_staging_final_pgdata` 卷和独立 Artifact/workspace/Bridge state，
仅监听回环15432/18000/13000/18080；没有切换正式公网入口。

最终0014已在全新隔离空库中执行0001→0014。另以不停止正式服务的只读 pg_dump
恢复到 `hypertest_verify_historical_0012`，再执行0012→0013→0014：全部33张既有表
的所有原字段与行 hash 不变，5个旧Verdict完整保留，新增Run binding数量为0。
该隔离历史库未启动Worker，不会重新执行旧任务。早期开发staging卷也保留，
没有将“已处于0014”误当成修改后migration的执行证明。

实际隔离 network namespace 从另一接口访问容器API/Web/PG均失败，自有DROP
计数增加6；宿主staging与正式入口仍HTTP200。systemd受控启动及实际首条DROP、
restart=no、live-restore=false通过。没有重启共享生产Docker/宿主；这不等同于
真实开机验收，也不能替代正式切换时的VPN允许和另一公网出口拒绝实测。

最终构建输入与实现 commit `dae0ef8cf3cd7ad2fe5498b62c017c557127847b` 的内容和
文件 mode 完全一致：platform 97个文件、Web 46个文件、ops 14个文件。真实 Linux
容器 Worker → 宿主 Bridge → Codex → Docker API 环境已完成一个独立 Run：
4个 Mission 复用同一原生会话，26项 JUnit 测试通过、无失败/跳过，5份证据均为
`RUNNER/VERIFIED`，最终 `RELEASE_READY` 且会话绑定 `CLOSED`。页面及18份静态资源
HTTP200，报告和JUnit引用已实际读取；这项 Linux 检查没有代替本地真实浏览器交互验收。

完成冷备后恢复到全新隔离库/目录：41张表的全部行一致，Artifact 9个文件、
workspace 529个文件、Bridge ledger 2个文件 hash一致。最终 API 镜像以非root、
禁网络和只读恢复 Artifact mount调用真实应用reader，验证11个引用（25,361 bytes），
另校验2个 PRD/config输入摘要，数据库约束全部有效。恢复库没有启动Worker/Provider；
因此这些证据覆盖应用数据读取完整性，不宣称完成原生Provider整机灾难恢复。

限定Web回滚演练将当前镜像 `sha256:c698b031557bf297e389e970676cc9f33f256872431947eef23ff4c7a4af29fe`
切换到兼容旧Web镜像 `sha256:e67115577e8ee0de87a368105b4093af040f26a429c7036c0cd8c72309c2f0c0`，
再恢复当前镜像。两个版本均通过实际就绪和同一已完成Run的绑定/报告读取，完整
harness响应一致；API/Worker/Bridge/schema保持原版本。**完整核心版本回滚未验收**，
不能据此绕过前述新绑定/协议兼容性限制。

另在停止整个隔离栈后删除其唯一自有guard，验证检查拒绝，再通过systemd受控入口
重新安装首条DROP后启动；就绪通过。没有重启共享Docker/宿主，不把该演练写成
真实主机重启验证。身份、镜像、证据和剩余限制见
[ADR-013验收记录](ADR013_ACCEPTANCE.md)。

验收结束后已停止独立staging的五个容器与宿主Bridge，两项staging systemd unit均为
inactive/disabled，容器restart policy均为no，四个隔离回环端口全部关闭。只移除了
该staging网络的自有DROP，DOCKER-USER恢复原有RETURN；保留两套staging PG卷、
配对备份、恢复目录、Artifact、工作副本、Bridge ledger和镜像供复核。正式release、
schema、业务计数、Artifact清单、原PG卷挂载、各服务PID及UFW与验收前快照完全一致，
当时正式Web与API仍HTTP200，尚未执行本ADR的生产切换。之后的正式切换与
真实验收已完成，见[正式部署记录](ADR013_PRODUCTION_DEPLOYMENT.md)。
