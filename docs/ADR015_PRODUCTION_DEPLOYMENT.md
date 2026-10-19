# ADR-015 生产部署与线上验收记录

日期：2026-10-19，Asia/Singapore。状态：**Production Deployed / Online Core E2E Verified / Extended Recovery Matrix Pending**。

生产切换已于 **2026-10-19 13:01:10.760991 UTC** 完成。严格外部 TLS 已通过 CA 与主机名校验；线上本地 Connector 核心周期已在 **13:07:50 UTC** 完成，形成唯一正式 Docker Execution、可信 Evidence、FINAL `RELEASE_READY` 与已核验内容的报告。脱敏机器摘要见[生产证据](evidence/adr015-production-20261019.json)，原始配置、完整备份与详细尝试记录只保存在受保护的私有交接目录。

## 当前发布与保全范围

| 项目 | 本次结果 |
|---|---|
| 业务源码 | `63bd6cc6710d2937d189acc90acaa15502d73a24`；API / Worker / Web 使用对应固定镜像 |
| 数据库 | `0018_harness_selection`；`0015`—`0018` 为 additive migration |
| 固定运维包 | manifest `61b4e2800472db67d0e52cbc1507663fc8ac9d707b43e308e6fb88e32ff8214d`；来源与复用记录单独保留 |
| 服务器 Harness | 原 `95e92c5` Host Bridge、原 unit / 路径、认证和原生会话保留；内部能力确认 `READY` |
| PostgreSQL | 原容器、镜像、数据卷与启动身份保留，全程没有停止 / 重建数据库容器 |
| 原有业务状态 | 公共 admission 前，原 38 张业务表 row count / hash 精确一致；第39个版本表单独确认0014向前升级至0018。线上追加后的保全口径为原2,719条历史行逐行 hash / 多重集全部保留 |
| 原文件与认证 | Artifact、workspace、Bridge ledger、原生会话文件 hash 和既有 OAuth metadata / 官方登录状态通过核对 |
| 原访问与运行配置 | SSH、公钥 / 密码恢复访问、UFW、Docker 网络守卫、唯一 VPN 来源和 backup timer 保留 |
| 线上验收 | 严格外部 TLS / HTTPS、设备配对、源码接受、本地 Codex → 正式 Docker Runner → 5 Evidence → FINAL `RELEASE_READY` → 报告已核验 |

`SERVER_HOST` 与 `LOCAL_CONNECTOR` 两种模式并存。控制平面、Canonical State 和可信 Runner 仍在服务器；本地设备承载原生 Harness 与获准的源码 / 问题单适配器。平台没有获得本机 Provider、Git 或 GitLab 凭据。Implementation 通过 typed Proposal 接受为 Artifact，不能将本地探索或 Agent 自报当成正式执行事实。

## 三次尝试与保留的历史

| 尝试 | 触发与结果 | 正式库及恢复行为 |
|---|---|---|
| 第一次 | 新镜像的迁移目录对默认服务 UID 不可读，独立 clone 库演练未通过。随后修复镜像权限，并以默认非 root UID 核验迁移 head | 正式库仍为0014；旧软件与 readiness 自动恢复，原备份和失败记录保留 |
| 第二次 | clone 恢复 / 迁移演练通过，原38业务表 hash 一致。正式库升级0018后，入口前将 systemd 执行观测字段误当静态 unit 变化，触发保守回退 | 旧软件恢复，正式库保留向前的0018；没有数据恢复覆盖或 schema 降级，原失败记录保留 |
| 第三次（v3） | 分开严格核对 unit 原文、已加载稳定配置和文件 hash；确认变化仅为重启观测。从保留的0018重新完成全新 clone 恢复及幂等升级演练，然后切换服务并通过入口前保全与内部 readiness | 新软件已运行，正式库为0018；原38业务表与全部原文件 / 认证 / 访问 / 数据库身份检查通过 |

两次失败不是通过证据，也没有通过删除旧任务、改写 Canonical State 或恢复覆盖正式数据库来消除。v3 的0018演练不冒称再次执行了0014→0018迁移；实际向前迁移发生于第二次尝试。

## 切换与恢复约束

整个检查、备份、演练、迁移、切换、公共 admission 和异常恢复均持有同一个维护 flock。先停止 API，再核对排队 / 运行 / 取消中 / `WAITING_INPUT` Job、开放 Binding、控制请求，以及未知 Bridge / Issue / Connector 消息；不能证明空闲时保留 Worker 和 Bridge。确认空闲后才停止 Worker、Web、nginx 和 Bridge，PostgreSQL 保持运行。

配对冷备由此前已验收的运维包执行，包含 DB、Artifact、workspace 和 Bridge state。每次演练使用全新、独立命名的验证数据库与文件目录，先校验备份完整性，恢复后比较全部冷态表和文件，再以新 API 镜像迁移验证库。只有演练通过才能对正式库执行向前升级；已经是0018时只做幂等检查。旧验证库、备份及失败记录不删除、不覆盖，正式库没有被 restore、drop 或 downgrade。

本次仅切换三应用镜像、业务 / 运维入口与显式 TLS 配置。platform.env 只更新 Operator key 与精确代理信任值，其他行保留；旧 Bridge 配置、两类权限密钥和授权设施不变。真实 nginx 配置 / leaf 预检通过后，先守卫启动内部 API / Worker / Web，确认原服务器 Bridge 与 Docker Runner 可用，再核对原始38业务表、文件、认证、SSH / VPN / Docker 规则与数据库身份，最后开启 nginx 公共 admission。

无活动且结果确定时，软件 / 配置可以回退至保留的旧版本，数据库仍保留 additive schema。公共入口开启后若有活动或未知工作，先关闭 API / nginx admission，保留 Worker、Bridge、原生会话和已有 Runner 收尾，延后软件回退。不得以整栈重启、重新创建 Session 或重发未知副作用来替代对账。

## 验收后的历史保全与观察

线上公共 fixture 与私有 source-only 补验后，独立 row-digest 多重集核对确认：**原38张业务表的2,719条历史行全部保留**，允许本轮新 Run 等记录追加；这不是要求新增业务后的整表 hash 仍与冷态相同。原66个 Artifact、2,909个 workspace 文件、13个 Bridge-state 文件及全部原生会话文件 hash 未变。原 Bridge 源码、稳定 unit 配置、OAuth metadata / 官方登录状态、SSH 公钥 / 密码恢复访问、VPN / nginx ACL / UFW / Docker 守卫、backup timer、PostgreSQL 容器 / 镜像 / 数据卷 / 启动身份及依赖版本均通过保全核验。

上线就绪至最终保全快照的范围为 **1,259秒（约21分钟）**；资源记录包含80份采样，未见 OOM 或重启。最终五个服务容器全部健康，活动 Job / 控制请求、开放 Binding 与未知工作均为0。该观察范围不代替长期负载测试或未执行的故障注入矩阵，具体断言见[生产证据](evidence/adr015-production-20261019.json)。

## TLS 与访问边界

新运维包在既有受保护监听启用 HTTPS / WSS，保留原监听地址、端口与唯一来源白名单。API / Web / PostgreSQL 仍绑定回环，nginx 回环入口仍仅以 HTTP 提供 health。可选 TLS overlay 由同一 Compose 入口自动加载，start / backup / readiness 不得遗漏。

叶证书与密钥仅由 nginx 只读挂载；Operator key 留在保护的 platform.env，`FORWARDED_ALLOW_IPS` 限于回环与实测单个代理 peer。CA 私钥不上传服务器。实际地址、代理值、密钥及配置原文不进入公开记录。外部客户端已启用严格 CA / 主机名校验，确认实际服务证书与批准 leaf 一致，HTTPS API health、Web HTML、capabilities 均为200；原 IP / 端口的 HTTP 仅308跳转到同一 HTTPS 入口。没有关闭校验或修改系统信任，也没有改变 CA 或 leaf key。TLS 验证与原服务器 Harness `READY` / Docker 可用已确认；WSS 设备执行另由实际线上周期验证，不由 HTTPS health 推定通过。

## 线上核心周期与验收边界

线上本地 Connector 核心周期已通过。使用公开 HyperTest Sum API fixture 的固定源码 `63bd6cc6710d2937d189acc90acaa15502d73a24`，经本地采集、HTTPS 接受和 WSS 原生 Codex，向服务器提交 typed Proposal；服务器可信 Docker Runner 独立产生正式事实。

| 链路 | 独立核验结果 |
|---|---|
| Run / Job | `01a15449-f81e-7af1-9903-e898359b7855` / `01a15449-ff0e-7bcc-90e0-95f465b1e25c`；Job `SUCCEEDED` |
| Binding / 主 Session | `01a1544a-0515-7d64-a51e-cf692ce19e4a` / `01a1544a-0511-7e2b-8c90-8e02021c4833`；Binding `CLOSED`、epoch 1 |
| 正式 Execution | 唯一 `01a1544c-d660-7422-ab1d-a66986749b2d`；Docker，`COMPLETED / PASS`，固定同一公共源码 |
| Evidence / Verdict | 5份 Evidence；`VER-01A1544D5D717483B8DE39F52D19AD67`，`FINAL / TEST_RUN / RELEASE_READY` |
| 报告 | `01a1544d-9a40-7329-9ed8-c602c6b00506`；引用上述正式 Verdict，实际内容 SHA-256 与 `6806077434bc752adae2d6c4ef23cb554bf9a8b4120fb2a2d31e9b38cdcbde8d` 匹配 |
| 外部问题单 | 该轮 operation count为0，没有新建或修改外部 Issue |

只有 Job 成功或能力 `READY` 不足以通过；本次结论同时依据正式 Execution、Evidence、FINAL 以及报告内容核验。公共 fixture 的身份可公开，不包含私有 SUT 指纹。

生产私有源码的 **source-only 接受补验已 `PASSED`**。以下为该补验唯一公开的结果字段；原始来源、内容指纹、项目和 Transfer 身份仅在私有记录中保全：

| 公开字段 | 结果 |
|---|---:|
| `bundle_bytes` | 44,271,128 |
| `raw_object_payload_bytes` | 32,840,412 |
| `file_count` | 1,431 |
| `object_count` | 1,737 |
| `source_only_run_count` | 0 |
| `issue_operation_count` | 0 |

该结果只证明受控源码接收补验通过，没有启动私有 SUT 的业务 Run，也没有新增问题单操作；不能将公共 Python fixture 的正式测试结果套用于私有项目。

设备配对后，首次本机 daemon 因 macOS Unix socket 路径过长在创建 SourceTransfer、Run 或 Job 前退出。处理范围是本地验收配置：保留原 Project / node、keys、journal 和首次源码请求身份，将 runtime 移至足够短的受管路径后续接；没有重新配对或替换任务身份。这不是运行中的断线或 epoch 恢复验收，也不是服务器发布故障；服务器功能版本仍为上述源码身份。

已完成的[隔离真实验收](ADR015_ACCEPTANCE.md)仍保留其独立拓扑、正反周期、首次失败、原会话恢复、报告 hash 和一次获准 GitLab 测试 Issue。该外部操作不冒称本次生产创建，**本轮生产部署没有新增问题单写入**；既有操作仅可只读核验，不能为重复验收再创建或修改 Issue。[源码预验](ADR015_ACCEPTANCE_SOURCE.md)的私有源统计也不能代替生产接受或证明私有 Java 项目的业务已在 Python fixture 中被测试。

本次生产核心周期未注入断线或执行 epoch 恢复，Binding 保持 epoch 1；没有新 Issue 创建。全部操作系统休眠、离线取消 / 撤销、`WAITING_INPUT` 离线、原 Session / workspace 丢失及真实外部 UNKNOWN 故障注入矩阵仍未逐设备全覆盖。隔离自动化、已完成真实结果与待验场景继续分别陈述，不能由上线成功推定全部可用。

## 线上驱动与本地路径

`scripts/adr015_online_cycle.py` 连接已有 HTTPS 平台，只启动本地 Connector；它不启动 API、数据库、Worker 或 Runner，也不配置 / 授予问题单集成。下列值为占位示例，须替换为获准平台、Operator 文件、CA 与公共 fixture 完整 SHA；保留 `--dry-run` 时仅做本地检查，不产生网络或写入：

```bash
python scripts/adr015_online_cycle.py \
  --api-url 'https://hypertest.example.invalid/api/v1' \
  --operator-key-file /private/tmp/operator.key \
  --ca-file /private/tmp/ingress-ca.crt \
  --commit-sha '<approved public fixture full SHA>' \
  --state-dir /private/tmp/hypertest-online-new \
  --connector-state-dir /private/tmp/htc-online-new \
  --dry-run
```

Operator 文件须为当前用户所有的0600普通文件，证据目录和显式 runtime 目录须全新。`--connector-state-dir` 默认仍为 `--state-dir/node`；macOS Unix socket 路径有限，线上驱动在 API / 网络初始化或创建目录前检查 `control.sock` / `relay.sock` 的完整路径不超过103文件系统字节。显式 runtime 须为规范非 symlink 路径，不得等于或包含证据目录。过长路径在任何 Project / node 写入前返回受控错误。

已配对节点的路径修复须保留原身份、完整 keys / journal 与配置，不能盲目重新配对或以新 Project / Run 绕过失败。此参数与预检属于线上驱动，不是隔离 `adr015_live_cycle.py` 的参数。

公开证据只保留平台发布身份、公共 fixture 身份、摘要 / 数量和通过状态。私有 SUT 的 URL、SHA、tree、bundle hash、源码路径，GitLab 项目 / Issue / 用户、IP、认证材料及 Provider transcript 均留在权限受限的私有保全目录，不随公开仓库发布。
