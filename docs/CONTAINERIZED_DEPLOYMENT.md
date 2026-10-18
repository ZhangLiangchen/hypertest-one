# ADR-013 容器化部署与恢复

本目录实现单 Linux 宿主的生产打包边界：nginx / Web / API / Task Worker /
PostgreSQL 使用固定镜像，Provider CLI、原生认证和 Host Harness Bridge 保留宿主。
开发用 `docker-compose.yml` 继续独立；生产使用 `compose.production.yml`。
本文是待发布版本的操作材料，**不是正式服务器已经迁移或完整 ADR 已验收的记录**。
实际应用、迁移、Bridge 版本及真实测试周期以该版本验收记录为准。

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

操作前使用 [服务器 SSH 约定](SERVER_OPERATIONS.md#ssh-access)。本次实现不执行正式
服务器切换、UFW 修改、OAuth 登录或数据删除。

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

nginx **仅**使用 `network_mode: host`，监听 `127.0.0.1:8080`（SSH 隧道）和
`155.138.206.106:8080`（公网 VPN）。公网 server 固定 `allow 45.76.149.233/32; deny all`，
同时保留既有精确 UFW INPUT 规则。nginx 无 `ports:`，因此公网入口没有 Docker DNAT
绕过原 INPUT 白名单的问题。API/Web/PostgreSQL 只映射 host loopback；没有 wildcard
或 IPv6 公网绑定。隔离验收使用 `HYPERTEST_PUBLIC_INGRESS=disabled`（生成配置只监听
loopback），并修改四个宿主端口以避开正式服务。正式环境保持 `enabled` 与原白名单。

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
该 unit `After/Requires/BindsTo=docker.service`，每次宿主开机都重新通过守卫启动，
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
重启验收。本轮只安装/操作独立 staging unit，不启用它的开机启动、不重启生产 Docker。

部署仍需实测以下项目，配置存在不等于已通过：

1. 从已连接 VPN 的实际出口访问 `http://155.138.206.106:8080`，HTML/API/静态资源通过，
   nginx 日志 peer 确认为 `45.76.149.233`。
2. 从不同真实公网出口（如未连接 VPN 的手机移动网络）访问失败；伪造 XFF 不得放行。
3. 公网 API8000/Web3000/PG5432 与 IPv6 不可访问；宿主 `ss -lntp`、Docker 发布配置
   和实际网络路径核对一致。不能只靠 UFW 展示推断 Docker 端口安全。
4. 原 `ssh hypertest-one` / 密码恢复方式与隧道保持有效，隧道 HTML/API 通过。

当前允许的白名单和 SSH 配置不由本目录脚本自动修改。任何网络策略修改须保留
回退记录，不重放旧的 activate 脚本或增添重复规则。

## 首次切换与常规升级

维护操作共用 `/run/lock/hypertest-maintenance.lock`。backup.py 自动取得该排他锁；
人工切换窗口使用 `flock` 持锁，并确保旧 backup timer/deploy 脚本使用同一把锁。
在确认既有 timer 的锁路径前，不并行执行备份/迁移。

所有 Compose 命令固定使用同一 release 的文件和 env，例如：

```bash
docker compose --env-file /absolute/compose.env -f compose.production.yml ps
```

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
7. 完成下一节真实就绪与数据保全检查，至少观察 15 分钟，再登记实际激活版本。

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
输出明确保留公网来源、旧数据和真实测试周期的未验收项，不能替代这些检查。

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

## 已执行的隔离验证边界（2026-10-19）

正式服务仍为 `0a2af9c4f5034c118f1a19abd786290f0959a648` / schema0012，
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

完整模型/恢复演练的身份、证据与限制另见本次ADR-013验收记录；单凭这里的
迁移与拓扑结果不能认定真实Runner/Evidence/Gate闭环已经通过。
