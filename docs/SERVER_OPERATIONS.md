# HyperTest One 服务器操作交付

## 当前环境与默认交付流程

**`hypertest-one` 是用户单人专用的内部测试服务器，用于 HyperTest One 开发及云端任务执行验证；
不是生产环境，没有多人共用或生产可用性依赖，开发更新允许中断和重启服务，没有零停机要求。**
这是2026-10-23由用户明确的环境定位。旧记录中的“生产”“正式上线”等人类语义不应继续
用于判断该服务器的等级；`compose.production.yml`、`hypertest-production`、已有路径、
镜像标签及日志字面是技术标识，保留原值，不据此把测试机当生产系统。
本节与 [AGENTS.md](../AGENTS.md) 的测试服务器规则共同取代旧文档对当前环境的可用性和
发布流程约束；现行产品领域、授权、幂等与证据真实性保持不变，被替代旧数据按 ADR-028 处理。

### Docker 部署与宿主 nginx 移除（2026-10-25）

用户明确后续应用服务部署统一采用 Docker。宿主 `nginx` / `nginx-common` 已卸载，
`nginx.service` 已停止、禁用并屏蔽，旧 failed 记账已清除；`/etc/nginx`、日志和状态目录
继续保留。实际入口仍由既有 Docker nginx 提供，不恢复历史宿主 nginx / Web 隧道流程。
本次未迁移既有独立 Cloud Worker / Bridge；具体包状态、资源收益和健康检查见
[移除记录](HOST_NGINX_REMOVAL_20261025.md)。旧宿主部署命令仅保留在历史快照中。

### 复用现有环境与最小隔离（2026-10-24 增补）

常规开发、构建和相关自动回归默认复用已有干净 Git checkout、兼容的依赖环境、构建缓存与
测试基础设施。尽量避免为每轮工作另建临时工作目录、隔离/影子环境、额外源码或构建副本、
重复 virtualenv / node_modules；本测试机允许停服后原地构建，不采用生产零停机流程。
复用环境不减少必要的变更范围回归、构建检查或强制 CI 检查。

只有具体依赖冲突、破坏性测试或安全边界确有需要时，才采用最小范围隔离。创建前说明
原因、资源和生命周期，优先复用已有测试环境；局部问题只隔离相应依赖、进程或测试库，
不复制多套全栈。完成后清理本轮新增、确认可再生且不再使用的临时目录、容器、依赖环境
和副本，保留不属于 ADR-028 替代清理范围的源产物、历史、凭据及未决 key / journal。其他工作目录和旧发行材料
不因名称含 `temp`、`test` 或 `release` 就自动成为本轮可删除资源。

复用现有环境不等于把测试 fixtures 写入业务数据库。可以复用明确用于自动回归的已有
test DB，reset 只作用于该测试库的合成数据；不得对业务库执行测试初始化、清空或覆盖，
也不得覆盖真实项目、任务或历史。需要防止破坏性测试触及业务数据时，隔离最小必要的
测试数据库是正当安全例外，无需另建整套平台。功能验收仍为 `USER_OWNED`；复用或
最小隔离都不授权 Agent 自动创建验收业务数据、签发凭据或调用真实模型 / SUT。

### 默认 Git 交付与直接部署

默认流程适用于本项目的代码、依赖或部署配置变更：

1. 本地修改并检查本次差异。按调试需要做轻量本地检查，不默认在本机跑全套测试、
   完整前端回归或 production build，也不设固定的本地 preflight 矩阵。
2. 将本次内容提交并 push 到明确的 Git 分支，记录完整 commit SHA。保护其他人的未提交
   工作；普通交付不打包上传 dirty 工作树，不把源码未提交快照当默认发布来源。
3. 默认复用服务器已有干净的 Git checkout，fetch 指定分支或 commit，解析并记录完整
   SHA 后 checkout 该提交。首次准备或现有目录有未提交内容时才另建 checkout，不 reset 覆盖它。
4. 停止受影响服务，在服务器原地构建新版本，执行需要的迁移，再启动相应服务。按 ADR-028 可定向清理被替代且不兼容的旧数据。
   用户要求部署即已授权中断，无需再次确认；必要时允许停应用栈，不要求先建隔离环境或
   保持旧版本持续在线。数据保护按本次迁移的具体风险决定。
5. 在远端按改动范围执行一次相关检查和基本就绪检查，记录实际 SHA / image / migration
   与检查结果；失败或未知结果如实保留，不重写为成功。确需全量回归时也在远端执行，
   是否扩大检查遵循下方停止条件。

**纯文档变更只做静态校验并 commit/push**，不触发服务器构建、迁移、重启或功能回归。
日常已授权开发不再额外要求审批、正式维护窗口、蓝绿 / 影子部署、每轮冷备及隔离恢复演练、
逐表逐文件 hash 保全、独立发布复核、历史生产 Gate 或固定15分钟观察；PR 合并及正式发行
资格也不是本测试服务器部署的默认前置条件。用户明确要求的发行流程和强制 CI 检查仍适用。
历史维护锁、admission、保全及回退流程按具体操作需要使用，不整套套用于普通更新。

### 最小必要验证与停止条件

- 文档修改只检查差异；局部代码修改只做相关检查。部署后检查服务启动、健康接口及本次
  变更的一条技术关键路径，不据此自动开展用户业务验收。
- 相关检查通过且没有具体未解决问题后立即结束。只有用户明确要求、强制检查要求或具体
  故障需要时，才扩大到全量回归、多宿主矩阵、重复采样或额外审查；不为普通开发任务
  新增验收、证明或保全体系。
- **功能验收由用户执行；除非用户明确要求，不擅自开展验收。** 必要构建、组件回归、迁移和
  基础健康 / 部署路由检查可形成交付记录，但不称为用户验收；不因部署完成自动创建业务
  Task、调用模型 / SUT，或追加浏览器 / 凭据 fixture 验收。

### 数据、凭据与访问保护

- 依据 [ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md)，可以删除被新实现替代且不兼容的旧实现和对应旧数据，包括旧任务及关联记录，无需再次批准。明确清理范围；无关的现行数据、用户源文件、凭据与宿主配置继续保留。清空整库或删除数据卷（包括 `docker compose down -v`）不在此授权范围。
- 除 ADR-028 已授权清除的旧数据外，迁移对其他数据确有风险时采取相称保护；不自动要求冷备或完整恢复演练。不能盲目重放结果未知的外部操作，不能把删除旧记录描述为迁移成功或历史结果改变。
- 保留现有 SSH 访问、公钥和人工密码恢复、主机密钥校验、TLS、VPN 白名单及其他网络
  访问限制；不将私钥、token 或密码写入源码、日志或交付物，不改动无关服务。

### Local 归档部署配置

新 Local 入口使用独立的 `HYPERTEST_ARCHIVE_WEB=enabled` 与
`ops/container/compose.archive.yml`。该开关只启用归档和 CLI 授权 Web BFF，
复用既有受保护 HTTPS Unix socket、公开 CA 与 Web 私有 Operator 文件；
不要求启用 Cloud Worker、模型执行或 Memory。相应受保护 nginx 路由由新版
`stack.py` 生成，不新增 TCP 入口，不改变 VPN 白名单或 TLS 身份。

首次部署此能力曾更新固定 ops、API、Web 并应用 `0030_local_archive` 和 `0031_cli_authorization`。后续部署应检查目标提交所需的完整迁移链。
`HYPERTEST_LOCAL_SESSION_WRITES_ENABLED` 默认为关闭，新部署不再接受旧 Local
新写入，旧查询与原 key 恢复目前仍存在，但可按 ADR-028 随旧实现定向移除。不要以回滚 Web 为由重新启用自动同步。
该轮源码、镜像、schema、公开 CLI 发行与健康检查见[归档交付记录](LOCAL_ARCHIVE_DELIVERY_20261027.md)。

现有脚本不会自动完成 Git 更新。下面是复用已有干净 Git checkout 的示例，不表示已经
在服务器执行或该示例路径已经存在；`release_checkout` 和 `target_ref` 需填为本次实际目标：

```bash
# 在服务器执行；不覆盖已有未提交内容。
set -e
release_checkout='/填写已有Git_checkout的绝对路径'
target_ref='本次已push的分支或完整commit'
cd "$release_checkout"
if [ -n "$(git status --porcelain)" ]; then
    printf '%s\n' '保留当前未提交内容，改用新checkout。' >&2
    exit 1
fi
git fetch --no-tags origin "$target_ref"
target_commit="$(git rev-parse --verify 'FETCH_HEAD^{commit}')"
git checkout --detach "$target_commit"
git rev-parse HEAD
git status --porcelain
```

仅在首次准备或当前目录不能复用时，才用 `git clone --no-checkout` 从仓库远端建立新的
checkout，再执行上面的 fetch/checkout；旧的非Git release和dirty目录保留，不每次重新clone。

构建入口是所选 Git checkout 中的 `Dockerfile`、`web/Dockerfile` 和
`ops/container/build-images.sh`。后者是全套构建工具，会构建 API/Worker/Web 并解析
PG/nginx 镜像；仅改部分组件时可按同一 Dockerfile 目标构建所需组件，不能把输出
`images.env` 全量覆盖现有配置而顺带升级无关组件。记录构建 SHA 与实际 image ID，
仅更新本次目标 image 键；新增 migration 通过 maintenance profile 的 `migrate` 服务
执行，API/Worker 启动不会自动迁移。Compose 操作沿用固定 ops 的 `compose_command`
及其实际 overlays、env 和网络守卫；不要照抄缺少 TLS overlay 的裸 Compose 命令。

既有运行入口为 `/opt/hypertest/ops-current` 的容器工具及
`hypertest-container-stack` / `hypertest-harness-bridge` systemd 服务。
`systemctl restart hypertest-container-stack` 是已有受控整栈重启入口，可能重启PG，
并不是 Git 拉取、镜像构建或迁移命令；按本次变更选择组件更新或整栈重启，
不为日常更新固定要求“PG启动时间不变”，也不绕过网络守卫。基本状态与就绪检查仍可用
`stack.py ... status` 或 `readiness.py --env /etc/hypertest/container/compose.env`。
已在测试服务器上运行时直接本机操作，不要求绕经 Mac 专用 SSH 别名或另配私钥；
`bash ops/check-remote.sh` 适用于已配置别名的 Mac，不必与服务器本机检查重复执行。
具体工具能力和数据边界见[容器部署材料](CONTAINERIZED_DEPLOYMENT.md)。

以下访问保护继续有效。历史发布流程与当前规则冲突时，以本文和项目 `AGENTS.md` 为准；不修改旧日志、证据路径或当时已经执行的事实。

## 当前访问与巡检规则（2026-10-19 更新）

Web 的唯一用户入口是既有跳板机出口对应的来源白名单入口。真实入口地址及唯一
IPv4 `/32` 来源保存在服务器受保护的 `compose.env`，分别由
`HYPERTEST_PUBLIC_IP` / `HYPERTEST_INGRESS_PORT` / `HYPERTEST_VPN_CIDR` 指定；
产品说明、白皮书和新的验收摘要不列出跳板机地址。配置升级必须沿用这些现值，
不能照抄示例中的文档地址。原始历史证据保留其当时的真实内容。

测试服务器 nginx 的回环监听仅接受 `GET` / `HEAD /api/v1/health`，其余路径拒绝；
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

[健康检查脚本](../ops/check-remote.sh)按服务器部署模式选择检查：容器模式调用现有 readiness 工具；旧模式检查原服务与数据库等。失败或 SSH 认证失败返回非零退出码，不进入密码交互。该结果只说明对应检查的运行状况，不代表真实 Agent 测试周期已通过或获得 `RELEASE_READY`。

后续自动检查与新建运维脚本统一沿用上述别名和密钥参数，不再使用临时目录中的 `SSH_ASKPASS`。此前失败是默认公钥未获授权，而 `BatchMode=yes` 又禁用了密码交互；密钥安装后该问题已解决。不要在全局 SSH 配置中禁用密码登录。

需要人工密码恢复时，在本机终端执行，由操作者输入现有密码：

```bash
ssh -o BatchMode=no -o PreferredAuthentications=password -o PubkeyAuthentication=no hypertest-one
```

本次配置未修改远端 sshd 的密码认证设置、应用服务或网络白名单。


## 历史记录

以往各轮的部署身份、命令和验收记录保存在[服务器操作历史快照](SERVER_OPERATIONS_HISTORY.md)及各轮交付文档。不能用历史记录推断当前运行版本；操作前检查实际状态。
