# ADR-016 生产部署与线上验收记录

日期：2026-10-20，Asia/Singapore。状态：**Production Deployed / Online Current-Agent Core E2E Verified / Historical Preservation Verified / Extended Recovery Matrix Pending**。

生产切换已于 **2026-10-20 06:34:11.197055 UTC** 完成，正式库为 `0020_interactive_tool_inbox`。**生产当前 Agent MCP 核心周期与最终历史保全均已通过**：同一真实 Codex Desktop Agent 经官方 MCP SDK console 完成 Proposal、可信远端 Docker Runner 的33项 HTTP 测试、五份 VERIFIED Evidence、FINAL `RELEASE_READY` 和已核验内容的报告。此前的[隔离真实 Agent 验收](ADR016_ACCEPTANCE.md)保留其27项测试和独立环境，不替代或混入本轮生产结果。

本记录依据独立切换前快照、镜像准备结果、两次切换结果、第二次冷备 / 恢复演练、本轮实际 MCP 结果和最终独立只读保全核验。脱敏摘要见[生产机器证据](evidence/adr016-production-20261020.json)。完整配置、原始备份和详细机器证据保存在受保护的私有交接目录；不公开实际访问地址、凭据、私有源码或本机原生会话身份。

## 发布身份与验证

| 项目 | 本次结果 |
| --- | --- |
| 合并发布 | PR #17；`c7cd43ad6346d8ce6c85564f7838afbb017f2da4` |
| PR / main CI | 均通过；完整回归为967 passed、21 skipped、3 warnings |
| 针对性验证 | 28项 API / runtime / constraints / scope 检查通过，含2个真实 Docker 场景；继续授权、集成撤权和设备轮换的3个并发锁测试通过 |
| API 镜像 | `sha256:8cfc764b1ccacc97ff3faf2b23b61b937bfdf0b1f29afda3349b3dd954d25a33` |
| Worker 镜像 | `sha256:7796433173907d7b4d3aa62f55a24dedc49af8ac91f959b3b1999a13a1c47f60` |
| Web 镜像 | `sha256:6b10ea21d3d3d9128cc77d0cff14d7d4e9de27d45e0f5af6819a4d705171e795`；源码文件 hash 比较一致后复用原镜像 |
| 数据库迁移 | `0018_harness_selection` → `0019_interactive_mcp` → `0020_interactive_tool_inbox`，向前 additive migration |
| 固定运维包 | 原 manifest `61b4e2800472db67d0e52cbc1507663fc8ac9d707b43e308e6fb88e32ff8214d`，安装内容及原运维入口保留 |
| 服务器 Harness | 原 `95e92c5` Host Bridge 运行时、稳定 unit 配置、认证与原生会话保留；没有用新插件替换既有受管 Harness |
| PostgreSQL | 原容器、镜像、数据卷、启动时间和重启计数保留；没有停止、重建或重启数据库容器 |
| 依赖与访问配置 | API / Worker 依赖版本及安装的 Bridge 源码未变；原 TLS、SSH、公钥 / 密码恢复访问、VPN 白名单和网络守卫保留 |

上述 CI 对应合并发布；隔离验收文档中的967 passed / 18 skipped、wheel 和源码 manifest 对应更早的验收快照，两组身份和结果不混用。

## 两次切换与原始证据

| 尝试 | 结果 | 正式库与恢复 |
| --- | --- | --- |
| 第一次 | 冷态全行 hash 检查发现 `harness_nodes` 与独立基线不同，迁移和应用镜像切换均未开始 | 自动恢复旧软件及入口，正式库仍为0018；没有 restore 覆盖、drop 或 downgrade。失败记录保留，既有备份未覆盖 |
| 第二次 | 重新独立采集完整基线，仅对获准的四个节点连接观测字段采用受限比较；冷备、全量恢复演练、clone 迁移、正式迁移、内部检查和入口前保全均通过 | 新 API / Worker 已运行，Web 复用原固定镜像，正式库为0020；原运维包、Bridge 和 PostgreSQL 身份保留 |

第一次失败的差异来自节点连接观测变化，没有通过修改旧快照或回填新字段将其改成通过。第二次从新采集的独立基线开始，仍严格比较节点身份、注册状态、capabilities、权限及其他全部配置列。

仅以下四个 `harness_nodes` 字段允许按连接观测处理：`presence`、`last_seen_at`、`connection_generation`、`row_version`。比较同时约束相同节点集合、全配置 aggregate hash 和逐节点配置 hash；presence 必须为合法枚举，时间必须带时区，原有 heartbeat 时间、generation 和 row version 不得回退，generation 增量须有相应 version 增量。该例外不适用于其他表、授权字段或原文件。

## 冷备、迁移与历史保全边界

整个预检、冷备、恢复演练、迁移、切换、公共 admission 与异常恢复由同一个维护 flock 覆盖。先关闭 API admission，再核对全部活动 / 等待 / 取消中 Job、开放 Binding、控制请求和未知工具 / Connector / Issue / Runner 工作；不能证明空闲时保留原 Worker 和 Bridge。确认空闲后才停止应用及 Bridge，PostgreSQL 始终保持运行。

第二次冷态捕获包括原 **52张业务 / 运行控制表**，以及单独的 Alembic 版本表。配对备份包括数据库、Artifact、workspace 和 Bridge state；在全新、独立命名的数据库和文件目录恢复，全部冷态原始行与文件先精确匹配，再以新 API 镜像的默认非 root UID 演练0018→0020迁移。clone 迁移后原52张表仍逐表全行 hash 一致，新协议表为空；正式迁移结果再与该冻结 clone 比较一致。**此冷态恢复、clone 及正式迁移比较仍使用完整原始节点行，没有归一化节点字段。** 正式数据库未被恢复覆盖、删除或降级，既有备份和演练目录没有复用或覆盖。

新服务内部启动后、公共 admission 开启前，原历史保全范围为 **50张表、3,699条原始历史行**：其中49张表全行 count / hash 精确一致，另1张 `harness_nodes` 表按上述规则确认原1个节点的配置严格一致。只有4个连接观测字段允许受限变化。`worker_heartbeats` 与 `runtime_control_requests` 两张运行控制表在服务重启后单独处理；它们仍属于此前冷态52张表的完整恢复 / 迁移检查范围，不能被描述为未备份或未比较。

Artifact、workspace、Bridge ledger、原生会话文件，以及既有 OAuth metadata / 官方登录状态、固定运维包 / Bridge 源码和 unit、受保护配置、SSH / VPN / Docker 守卫与 backup timer 均已在入口前核对。新业务追加后的最终独立只读校验已通过39项检查：原49张历史表的3,698条完整原始行以 row-digest 多重集保留，原1个节点的稳定配置保留，合计50张历史表 / 3,699条原记录。原7,429个文件保留，新增1,230个文件及1个节点单独计数；不是要求新增业务后的整表 hash 等于冷态值。最终快照采集于 **06:57:03.819558 UTC**，逐行摘要采集于 **06:57:18.465262 UTC**。

最终保全核验的第一次失败只涉及 Docker inspect 的 Mounts 数组顺序，失败结果保留；修正后按唯一、非空 Destination 映射比较每份完整 mount 字典，Source、Type、Name、RW、Mode、Propagation 等字段不放宽。校验器 SHA-256 为 `a9dca2757270528ae41d9f38d27a07e636be0f433497e9abd9605f3556df32ff`。原 PostgreSQL 身份及启动 / 重启计数、平台认证、SSH / VPN / UFW / Docker 守卫、受保护配置、原本地受管配置和设备 token metadata 均保留。TLS leaf / key metadata 与 timer Calendar 依据已通过的公共 admission 前切换核验；最终快照验证其实际采集的受保护配置与访问守卫，不冒称另行采集了缺失的 leaf / key metadata 或 Calendar。

恢复边界保持不变：只有能证明空闲且没有新协议历史时才可回退软件；schema 保留向前状态。入口开启后若已有活动、未知工作或新协议记录，先关闭 API / nginx admission，保留 Worker、Bridge 和已接受 Runner 的收尾及对账，显式修复向前。不能通过旧驱动重解释新协议记录，也不能为恢复而重发未知副作用。

## 生产当前 Agent MCP 核心验收

[ADR-016](architecture/ADR-016_INTERACTIVE_AGENT_MCP_ACCESS.md)的本地交互路径已部署：当前本地 Agent 通过受控 stdio MCP、私有 Connector 和 typed HTTPS 执行任务；API 只鉴权、记录 / 排队请求，原 Job Worker 执行九个 TMP 领域工具并调用正式 Docker Runner。本地 Agent 负责推理和 Proposal，服务器可信 Runner 负责执行事实，HyperTest 负责 Canonical State、Verifier 与 Gate。`SERVER_HOST / PLATFORM_MANAGED` 及既有 `LOCAL_CONNECTOR / PLATFORM_MANAGED` 路径继续保留。

首版 LOCAL 绑定仍要求[安装文档](INTERACTIVE_MCP_CLIENT.md)规定的受控 Codex Desktop 启动上下文、真实 native session、固定节点 / workspace / source，以及钉住的 stdio peer。普通 MCP 安装或查询不会绑定执行权；新进程、重新连接、journal 查询不会自动创建 native session、Job 或 grant。Agent 原生上下文停止后 Connector 不替身推理，已接受 Runner 可按原 Execution 完成。

当前真实 Agent 使用官方 `mcp.ClientSession` 经透明 stdio console、私有 daemon、严格证书校验 HTTPS、API inbox 和原 Job Worker 完成任务。console 不生成 Proposal、不启动第二个模型或 Provider；这也不是向已经打开的聊天热加载新工具目录的验收。使用独立公共 Sum HTTP API fixture 的完整源码 `cc84398ad81c26bd484ebaae46e6f61713d912ad`，本地获准采集的7,900,054字节 bundle 已由平台接受，受控本地 workspace 对齐同一固定源码。该 SHA 是 SUT 身份，发布代码身份仍为上文 `c7cd43a`。

| 验收项 | 独立核验结果 |
| --- | --- |
| Run / 执行选择 | `01a15808-b307-7531-b038-04e4f2b7ffdf`；`LOCAL / LOCAL_CONNECTOR / INTERACTIVE_MCP` |
| Requirement / Risk / TestCase / Implementation | 2 / 3 / 4 / 4 |
| 正式 Execution | 唯一 `01a15817-cbbb-7756-be32-f52eced2a574`；平台可信 `docker / OFFICIAL / COMPLETED / PASS` |
| Runner JUnit | 33 passed、0 failed、0 skipped；1.24秒，实际 HTTP 测试 |
| Evidence | 五份 `RUNNER / VERIFIED`，全部经 MCP 读取并核验 SHA-256 / 字节数 |
| Gate | `FINAL / RELEASE_READY` |
| 报告 | `01a15818-baae-71e4-993a-ec8690e3e151`，已接受；经 MCP 两页读取共1,077字节，SHA-256 为 `dec45325a819db8c7dab0fa606a61888c5b01c05bc44ebf33071e1b8eb9d19e7` |
| 终态 | Run `COMPLETED`、成功 Job `SUCCEEDED`、Binding `CLOSED`；原个人聊天继续可用 |
| 传输与恢复 | 初次提交后重启传输，按原 key 查回原 receipt；实际短执行授权过期后两次显式恢复至 epoch 3，身份保持 |
| 最终线上后历史保全 | 独立只读校验39项通过，原50张历史表 / 3,699条记录及7,429个文件保留 |

本轮120秒短执行 grant 在 Implementation 阶段过期。平台停止新工作；显式 Operator 恢复由 Worker 验证原 Run / AgentSession / native / workspace 后推进 epoch 1 → 2。第一次恢复的 claim 在显式 continue 前再次过期，第二次受控恢复推进至 epoch 3。失败 Job 和原阶段 Attempt 保留，旧 Attempt 的完成请求及执行条件不足时的 Runner 请求均被权威拒绝；新的阶段 Attempt 经接受后才继续，最终只产生上述一个正式 Execution。恢复没有重置任务身份或隐藏失败；本轮没有 UNKNOWN 写入，也未为对账重复提交。

初始提交的传输重启只验证按原 receipt 对账；本轮没有注入运行中失答或 Runner 在途断线，不能将它描述为运行中断线故障矩阵通过。既有服务器受管模式和本地 Connector 受管模式保留，原本地受管配置与设备 token 的 metadata 未变；本轮没有为这两条受管路径另做完整测试周期，也没有新增问题单或私有 SUT 业务执行。

从 **06:38:21.260628至06:53:09.634205 UTC** 的60份健康采样覆盖约14分48秒，服务健康且无重启。**06:58:17 UTC** 的 `ops/check-remote.sh` 检查为10 / 10就绪；该巡检有意只验证平台运行状况，业务通过结论另据上表的正式 Runner / Evidence / Gate / 报告证据。外部 MCP 通路使用严格 TLS 校验，既有 VPN / 白名单边界沿用；不把本轮描述为重新执行了全部允许 / 拒绝网络矩阵。

本记录不主张扩展设备故障矩阵、真实私有 Git 业务测试或新增外部问题单写入通过。原[ADR-015生产验收](ADR015_PRODUCTION_DEPLOYMENT.md)保留其既有证据，隔离周期的恢复与传输时序仍按原记录解释；本轮真实过期恢复和提交对账使用本节的生产身份。新 Web 执行选择界面、其他宿主 / Provider、不可恢复身份和真实外部 UNKNOWN 场景仍须独立交付或验收。

最终只读数据库核验确认为1个 CLOSED Binding、1个交互 attachment 及1个 CLOSED 原真实 native 主 AgentSession，3个关联重试 Job 依次为 FAILED / FAILED / SUCCEEDED，当前 Run 的4个 Mission 均 COMPLETED，5个 Attempt 中4个 ACCEPTED、1个 FAILED，并仅有1个正式 Execution、5份 Evidence 和1份报告；其余12类运行控制 / UNKNOWN 计数均为0。原严格“全局非终态 / 待处理工作均为零”检查仍为 **false**（原19项严格检查中18项通过），因为另一个旧 BLOCKED Run 保留1条 RETRYING Mission，其完整行 SHA 在切换前独立基线的摘要多重集中精确匹配，关联的待处理 Job、Attempt、Binding 和 Runner 计数均为0。该结果单独登记为 `VERIFIED_WITH_RETAINED_INACTIVE_HISTORY`，没有放宽查询、执行任何数据库或业务写入或改动旧记录，也不宣称19项严格检查全部通过。
