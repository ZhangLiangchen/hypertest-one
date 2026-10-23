# ADR-023：Cloud 的固定 SSH 环境诊断

**状态：Accepted design / IMPLEMENTING / DEFAULT OFF；source29隔离合成transport及source30 Worker的r8 canonical SSH专项通过；source31对r8同v19固定快照strict重评PASS、旧source30 NON_PASS保留，故障矩阵与真实staging待验收；尚未更新测试服务器常驻Cloud服务（2026-10-23，Asia/Singapore）。**

## 决定与范围

在 ADR-019 的独立 CloudTask / CloudAttempt 中增加显式 opt-in 的 `SSH_FIXED_DIAGNOSTICS_V1`。第一片仅访问一个冻结的 literal IP、端口、非 root 用户和精确 Ed25519 host key，串行调用固定目录中的无参数只读诊断动作；每动作不超过30秒、stdout / stderr各64 KiB、每 Attempt 最多8个操作。测试发现、用例、断言及执行仍由项目工作区框架负责；该能力不建立通用远端 shell、Runner、CI或环境部署系统。

任务级隔离继续必需。当前专用非 root systemd / namespace 基线内，根和子 Agent 只得到 `/run/hypertest-ssh.sock` 与窄客户端：`python -m hypertest.cloud.ssh_client invoke --key KEY --action KEY` 或 `query --operation UUID`。客户端不能传目标、命令、参数、环境变量或凭据。namespace 没有一般网络、SSH私钥、signing key、DB / 平台凭据、SSH_AUTH_SOCK或个人 HOME；不启用 PTY、转发、隧道、跳板、scp / sftp。Claude继续占位。

## 冻结配置与授权

- Environment 冻结 exact target、host key、helper版本 / 摘要、动作目录摘要和每个固定脚本摘要及限额；旧 SSH 元数据或自由文本 `side_effect_limits` 不构成执行 allowlist。`NONE` 与原 HTTPS Git / 工作区框架路径保持原义。
- 授权明确列出 SSH 固定诊断动作及 canonical `ssh://user@IP:port`；Project credential 的 allowed_targets 必须精确匹配，不从旧 host-only 授权推导新权限。IPv6 使用规范括号 URI。域名解析、root用户、任意参数和超范围目标拒绝。
- 独立 `cloud_ssh_enabled=false` 默认关闭。开启仍须受信、canonical、只读、固定摘要的 OpenSSH 客户端与远端 helper / 动作目录、独立 SSH-authority Ed25519签名身份与首片Ed25519 SSH客户端认证key、有效环境SSH credential和已强制的有限资源。缺失任一项在 prompt / SSH前闭锁；禁止 PATH、宿主网络或个人登录回退。首次启动准入不联系DB / 模型 / SSH目标。
- SSH开启时，claim前还须在固定image内解析当前有效UID的NSS记录，并核其UID / 主GID与进程身份一致；缺失返回闭集`SSH_LOCAL_IDENTITY_UNAVAILABLE`，不输出账户数据。此检查不替代原outer非root准入，SSH关闭路径不查询NSS；镜像可固定合成服务账户，禁止改root或挂宿主`/etc`回退。
- SSH key、SSH ticket签名 key、包装 key、平台 Operator / Worker身份和模型身份互相独立。签名 key只在host，远端固定验证公钥；不得为最小部署复用包装 key或Operator key。

## 可恢复的远端操作

Cloud canonical SSH ledger独立于平台 typed mutation回执，保存 Attempt / generation、稳定client key、不可变request digest、目标与动作摘要、原operation UUID及追加观察。host先在DB事务持久SENT再允许一次SSH发送；重复SENT / UNKNOWN仅按原ID QUERY，NOT_FOUND不授权再次START、换key或重放prompt。

host在当前DB授权检查后签发短期票据，精确绑定目标、Attempt、operation、请求摘要、generation、lease截止和任务hard deadline。远端固定forced-command helper验签、验证时钟 / 有效期，先以O_EXCL持久登记原ID和摘要，再创建Restart=no、有限cgroup与TTL的单次动作。登记到启动间崩溃保持UNKNOWN；QUERY不创建、续租或启动操作。generation数字本身不是授权。

合法签发的票据在短有效期内存在**有界撤销延迟**，不是即时撤销承诺。失租 / 取消后拒绝START / RENEW；清理只能对原ID发独立受限STOP / QUERY，不增加动作或延长deadline。远端短TTL与hard deadline负责失联停止，但TTL到期或本地ssh退出均不能代替远端实际观察。每次新连接仍复核SSH credential有效性和精确目标；撤销后不偷偷复用缓存私钥，无法连接时保留UNKNOWN，等待另行授权的清理。

## 完成、失败与预算

SSH动作截止从含Git准备的原Attempt整体截止固定提前30秒，清理使用该原预算内窗口；root模型与非SSH路径的原截止不延长。准备前或准备后已无SSH动作窗口就拒绝启动，不从checkout完成时重新计时。远端SENT的hard deadline不得晚于此动作截止；未知或清理未完成仍HELD，不因截止已过而假称停止。

常规终态路径先停止Agent namespace和模型broker，再对原SSH操作有界STOP / QUERY；预算cutoff则在现有Worker循环中提前fence / 关闭SSH scope，为至多24秒的close留下原总预算内30秒窗口。根 / 模型可以在原截止前继续工作区工作，SSH关闭不代表Task结束、测试结果或远端已确认停止；清理失败仍RECOVERY_REQUIRED / HELD。服务端以canonical远端ledger验证所有已准入操作均有真实终态、unit inactive、cgroup empty和输出封存；Worker自报布尔、本地进程停止、SDK idle或模型drain不构成remote_closed。无操作时以canonical空ledger及冻结配置证明；不再把“无外部能力”证明套到已启用SSH的任务。

未确认远端操作阻止COMPLETE、复测和会释放预算的协调 / 结算；任务保持RECOVERY_REQUIRED与HELD。旧lease的原owner仅能查询 / 停止其原操作并追加真实观察，不恢复普通写权或START / RENEW。当前fenced Worker的完成与预算仍由既有事务、原key和固定接受版本读回治理。测试reported FAIL保留，诊断exit0也不提升为PASS、legacy VERIFIED或Gate通过。

输出通过host原件 / secret边界核验后才能返回；只保存有界、明示的诊断产物，不上传完整环境、任意路径、SSH调试日志、秘密或聊天。无法实施可靠helper / manager的目标只可另标连接检查，不宣称支持可取消远端执行。

## 验收与局限

先使用隔离sshd、专用新key与真实远端manager的fixture，验证精确host key / 目标 / 动作、输出上限、原ID去重、掉ACK / NOT_FOUND、kill broker、孤儿子进程、取消 / lease丢失 / 撤权、票据过期和时钟偏差；对全部操作检查unit / cgroup终态。真实staging配置、网络路径与环境变更需独立授权和验收。本决定不改变Mac管理SSH alias / key、VPN、现有生产服务、Local会话同步或PowerContext。

现有受控公有fixture六步与严格直接原件验收见[实现状态](../CLOUD_IMPLEMENTATION_STATUS.md)。source29独立合成transport另已观察同key去重、丢ACK原ID查询、NOT_FOUND不START与错误host pin拒绝，两个terminal及实际原cgroup停止由host独立核对；没有SDK / 模型 / 正式CloudTask，取消 / 超时 / 后代矩阵尚未执行。r8后续以source30 Worker / source29 helper获得canonical SSH专项PASS，source31对同v19固定快照strict重评PASS，原expectation与source30 NON_PASS保留；该重评无新的current GET / 模型 / SSH / SUT执行，不由19项重放直接推导PASS。各类证明身份分开，精确码 / 原件 / 预算与成因审查见实现状态；本ADR不声称生产可用或P0全部退出。

本轮目标路由另按[Cloud / Local环境路由](../CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)：XBlock staging的SSH / 日志 / 操作与166dev内网自建链均仅Local，本ADR不授权云端连接或绕过。纯Web / API的Cloud路径尚需在固定SSH小片之后独立接通与验收。

环境路由的仅收紧字段`cloud_access_policy=LOCAL_ONLY|WEB_ONLY|None`保持旧None序列化省略；LOCAL_ONLY拒绝Cloud创建 / 解析 / 下发和执行，WEB_ONLY限制HTTPS且当前HTTPS执行仍闭锁。未配置真实XBlock / 166dev资源，详见[环境路由](../CLOUD_LOCAL_ENVIRONMENT_ROUTING.md)。
