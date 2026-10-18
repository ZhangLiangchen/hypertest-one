# ADR-013 实现与验收

日期：2026-10-19，Asia/Singapore。对应 [ADR-013](architecture/ADR-013_CONTAINERIZED_PLATFORM_AND_PERSISTENT_HARNESS.md)。

本轮实现生产 Compose、宿主 Harness Bridge、Run 持久主会话、运行中领域工具和 Web 会话/报告/恢复入口。真实模型验收使用 Codex；正式测试事实均来自 Docker Runner。**正式服务器尚未切换至本版本**，不能把独立 staging 的验收当作生产迁移完成。

## 实现范围

| ADR 要求 | 本轮实现及证据 |
|---|---|
| 平台容器 / 宿主 Harness 分离 | nginx、Web、API、Worker、PostgreSQL 的独立固定镜像；Bridge 是宿主受管服务。API 无 Docker / Bridge / Provider 权限；Worker 经数据库控制队列返回实际运行能力及镜像身份。 |
| 一个 Run 一个主 Session | `RunExecutionBinding` 固定逻辑 Worker、节点、受控副本与主 Session；多 typed Mission / Attempt 复用该 Session。历史 Run 不回填绑定。 |
| Harness 自驱、平台准入 | 九个固定工具由原生 Codex 调用；Planner 只执行确定性的依赖/覆盖准入。Proposal 经 Verifier，正式执行经 Runner，质量结论由 Gate 生成。 |
| 可靠调用与预算 | Job claim、绑定 epoch、签名授权、原调用身份、过期拒绝；外部结果不明先对账。冻结 Run 总活跃秒数预算，等待不消耗活跃预算，未知调用预留全额。该预算不表示模型计费 token 限额。 |
| 两类人工输入 | Mission / Run 问题跨表互斥，原子暂停；回答重新排队同一 Job，恢复同一原生 Session。阶段边界问题不重开已完成的 Mission。 |
| 显式恢复 | 核验原生会话、原副本和源 SHA，停止并隔离旧调用后提高 epoch；会话/副本缺失明确失败，旧 Run 内不创建替代 Session。 |
| 报告与 Web | 中英双语会话状态、身份与限制、恢复操作、完整性校验后的报告读取、外部 Issue 状态。终态绑定引导新 Run，不能通过历史失败 Job 绕过会话生命周期。报告不决定发布质量。 |
| GitLab 受控集成 | Worker 专有 policy / token、固定项目与负责人映射、同 Run Finding / Runner Evidence 校验、关联记录及未知结果仅 GET 核对。真实创建 Issue **未验收**：本次没有该外部副作用的配置和授权。 |

迁移为 `0013_run_bindings` 和 `0014_harness_operations`。它们新增 Operational 状态、关系与生命周期约束，不合并旧 Session，不改写旧 Attempt / Execution 的 Job 归属，不将会话或报告加入 Gate 的 Canonical hash。

## 本地真实 Codex → Docker → Evidence → Gate → 报告

使用独立数据库 `hypertest_adr013_acceptance`、独立 Artifact/受控源码/Bridge ledger；未修改既有本地业务库。PRD 是 Sum HTTP 示例的有限测试需求，源码按完整 SHA 固定。以下是实际运行记录，不是合成 Agent 输出。

| 场景 | TestRun | 原生 Codex Session | Runner JUnit | 正式结论 |
|---|---|---|---|---|
| 正常完整周期 | `01a14ff3-ea06-74b7-aa4d-68c406ef8fff` | `01a14ff4-e561-7ae1-9aad-a8d2d1a5e492` | 28 通过，0 跳过 | `RELEASE_READY`，报告已接受，Binding CLOSED / epoch 1 |
| 真实缺陷诊断及显式恢复 | `01a14ffd-52f9-7ddc-9374-f5b5950ae83c` | `01a14ffd-5f52-7f22-9f13-643f557a2147` | 22 项，10 失败，0 error/skip | `RELEASE_BLOCKED`，1 条 Critical Finding，报告已接受，Binding CLOSED / epoch 2 |
| Mission + Run 问答及重启恢复 | `01a14ffd-53cd-7f24-ad71-bf2ea131b818` | `01a14ffd-5f2d-7961-b440-1ad75f0b0057` | 26 通过，0 跳过 | `RELEASE_READY`，两问题 CONSUMED，报告已接受，Binding CLOSED / epoch 1 |

每个 Run 都有 5 个 Runner Evidence（stdout、stderr、JUnit、服务日志、执行元数据），已从实际 Artifact 文件重算 SHA-256；三个报告经 API 读取并独立重算 hash。Canonical case 数量与参数化 JUnit 数量不同，不相互冒充。

正常与问答 Run 固定源码 `0a2af9c4f5034c118f1a19abd786290f0959a648`，故障 Run 固定 `248b45dfcae2880087951f79baec5c4e7af26856`，均属于同一 Project。后两 Run 实际并发，独立绑定、原生 Session 与工作副本；分别使用正常 `examples.api_sut.app:app` 和故障 `examples.api_sut.broken_app:app`。

### 问答、恢复与实际修复

问答 Run 的原 Job `01a14ffd-53dd-7296-bd88-804e4624b66d` 连续领取三次，保持原 Session / epoch 1。第一次在需求分析阶段提问，等待期间重启 Worker，通过真实 Web 回答；第二次在正式执行完成后提问，等待期间重启 Bridge 与 Worker，再通过真实 Web 回答。四个 Mission 均只有一个 Attempt，没有重开已完成阶段。

三次活跃调用分别结算 24、123、27 秒；后续授权从 3,600 降至 3,576、3,453 秒。两段等待时间没有重置总预算，也没有计入活跃执行时间。问答结果及报告在 Web 可见。

负向验收发现并修复了真实缺陷：已完成的诊断被 Planner 的“下一动作必须匹配意图”检查误判，导致 Gate 再次要求诊断。修复将该检查放在**创建新阶段之前**，已完成诊断仍可用于 Gate 的确定性完成检查；新增 PostgreSQL 回归验证不会重复创建诊断。

该失败 Job `01a14ffd-5315-708e-8b66-ae31d2d9f518` 原样保留。通过 Web 的“核验并恢复会话”先隔离旧调用，epoch 1 → 2，随后 Web 创建新 Job `01a15003-861b-74ff-bfde-648964cc0e87`。新 Job 复用同一原生 Session，接受负向 Gate 与报告，未重跑已完成的五个 Mission。Job SUCCEEDED 与 RELEASE_BLOCKED 同时如实显示。

同轮真实集成还修复了 Worker 控制队列 datetime JSON 序列化、持久工具协议默认版本、Attempt/checkpoint 写入顺序，以及未知调用预算结算边界；对应回归覆盖实际 PostgreSQL 守卫。

### 可核对的内容身份

| 场景 | 报告 ID | 报告 SHA-256 |
|---|---|---|
| 正常 | `01a14ff6-c651-7199-b821-e92238f3e67b` | `8f91a8b35bdab5f1123785993587500b016ffe956f5e873677fe2c6399d8d7a1` |
| 故障 | `01a15003-f254-7039-9eff-b1c4a6c59764` | `839ef8fa6b617c32d99f1e96267a352b946ba2be3e7ca3098b1577f036a5f286` |
| 问答 | `01a15008-11e1-7dca-8962-6c484eb870ef` | `c920430d7c1ac86ee0a1118208fc4a5ffe621de92d0555fd30614614bd04e6c8` |

本机交接证据位于 `/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/adr013-acceptance-local/`：`*-final-api.json`、`*-execution.json`、`canonical-session-proof.json`、`runner-artifact-proof.json`、报告和真实 Web 截图。Bridge keys、OAuth、原生会话 transcript 不入库、不作为正式 Evidence。首条正常周期早于总预算记账功能，因此不能单独证明预算；预算由后两条真实运行和专门回归验证。

## Linux 最终容器拓扑验收

实现提交：`dae0ef8cf3cd7ad2fe5498b62c017c557127847b`。Debian 隔离构建快照为 `b70acc4b015823f5f790acca9cb93b8f06315ec34800bdee55dbb4d49a333233`；独立逐文件核对平台 97、Web 46、运维 14 个构建输入的内容与权限，均与该提交一致。验收记录补充不改变这些构建输入。

| 服务 | 实际 Linux image ID |
|---|---|
| API | `sha256:b0cf72e8e005b462474c6b880843d90c5f0802657d981fc57a8944fa6e559da8` |
| Worker | `sha256:08b04db3b63f78ceeff540289e0a7b62c5726f81dccd8b77ffeff8b85b906866` |
| Web | `sha256:c698b031557bf297e389e970676cc9f33f256872431947eef23ff4c7a4af29fe` |
| PostgreSQL | `sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c` |
| nginx | `sha256:8f59ff5046a70e421d35ed7d1e862a963215c9689b36cb8f64a6c42f9cf2955d` |

隔离栈 `hypertest-adr013-staging` 使用独立目录、socket、数据库和卷。最终新卷 `hypertest_adr013_staging_final_pgdata` 从空库升级到 0014；早期 staging 卷和正式 `hypertest_pgdata` 均保留。受管启动实际验证五个容器 healthy、非 root 应用/只读根/权限挂载边界，以及 API/Web/nginx 回环 HTTP 200、Worker 返回真实 Bridge/Docker 能力。

正式端口不变；staging 仅监听 `127.0.0.1` 的 15432/18000/13000/18080。宿主 Docker 26 的回环发布风险通过本栈专属 DOCKER-USER 首条 DROP 规则治理，实际隔离 netns 对 API/Web/PG 的转发探测均失败、DROP 计数增加 6；生产和 staging 的宿主回环仍可访问。启动器先停止本栈，再校验 restart=no / live-restore=false、安装并检查守卫，最后启动并轮询真实健康；任何失败保持停止。没有重启生产 Docker 或整台服务器，整机重启验收仍未执行。

Linux 上的新真实 Run `01a1501c-509f-7806-8340-4adb9c6abfb8`，Job `01a1501c-51ad-73cd-8909-c73b2043312b`，四个 typed Mission 共用原生 Session `01a1501c-5b66-72a3-a9e2-acab0e4fd5d7`。容器 Worker 驱动宿主 Codex，正式 Docker Execution `01a1501d-9ceb-7b65-b9e7-6f77441c5659` 为 COMPLETED/PASS：JUnit **26 项通过，0 error/failure/skip**，5 个 RUNNER/VERIFIED Evidence，报告已接受，Binding CLOSED / epoch 1，Verdict `01a1501d-f040-702e-b77d-925ec59a30fe` 为 FINAL RELEASE_READY。JUnit 和报告内容 hash 已独立核对。远端 Web Run 页及 18 个静态资源均 HTTP 200；Linux 此处是 HTTP 核验，真实浏览器点击证据来自前述本地 Web 验收。

另外对**正式 0012 库的只读 dump**进行隔离恢复和迁移：新库 `hypertest_verify_historical_0012` 升级 0013/0014 后，33 张既有表所有原有列/行 hash 不变，5 个旧 Verdict 的聚合 hash 仍为 `44cb9f46c3b80a704eeddca9ff80d39dc6d0bc5c97afdef4ba56d81759309c7a`，新 Binding 数为 0。该恢复库没有启动 Worker。正式服务在整个取样和迁移演练期间保持运行。

上述证据在交接目录的 `adr013-staging-build-inputs-b70acc4b015823f5.json`、`adr013-staging-commit-mapping.json`、`adr013-staging-readiness-b70acc4b015823f5.json`、`adr013-staging-network-guard-probe.json` 和 `adr013-staging-historical-migration.json`。Readiness 命令本身不证明真实测试周期或历史保全，二者由各自记录单独证明。

### 配对恢复与守卫丢失演练

完成真实周期后，对停止的 staging 生成配对冷备，恢复到新数据库 `hypertest_verify_final_cycle` 和新目录 `/var/lib/hypertest/adr013-staging-restore-final`。41 张表的完整行 hash 一致；Artifact 9 个文件、workspace 529 个文件、Bridge ledger 2 个文件均逐字节一致。原 staging、历史恢复库和正式数据未被覆盖。证据为 `adr013-staging-paired-recovery.json`。

恢复库又通过真实应用 CAS reader 读取 11 个内容引用（25,361 bytes），并核对 2 个 PRD/config input 摘要，所有数据库约束均 validated。验证容器以 UID 999/GID 989、Artifact 只读挂载、network none 运行；没有启动恢复 Worker 或 Provider。

全部 staging 端口关闭后，只删除本栈自有网络守卫；实际检查拒绝缺失规则，再通过 systemd 受控启动重新安装并核验首条守卫，恢复健康状态。此项证明受控停启时的守卫恢复，不代表共享 Docker Engine 或整台宿主已经执行真实重启试验。

随后完成兼容 **Web-only** 回滚：旧 Web `sha256:e67115577e8ee0de87a368105b4093af040f26a429c7036c0cd8c72309c2f0c0` → 当前 Web `sha256:c698b031557bf297e389e970676cc9f33f256872431947eef23ff4c7a4af29fe`。API、Worker、Bridge 和 schema 保持当前兼容版本，两次就绪检查通过，前后完整 Binding/Report JSON 相等。此项不证明旧核心二进制可读取并继续执行新持续会话数据，不作为全栈降级许可。

最终证据集合位于交接目录 `adr013-staging-final-evidence/`，包含真实周期、旧库迁移、配对恢复、Web 回滚和清理结果及逐文件 manifest。证据包 `evidence.tar.gz` 的 SHA-256 为 `6f5c975ccfda0463a35f9f28152ca591031ba72bdd9e60a5f06f6e0bc44a7775`。

## 自动检查

- `.venv/bin/ruff check src tests alembic`：通过。
- 实现提交 `dae0ef8` 执行 `HYPERTEST_TEST_CONTROLLED_DOCKER=1 .venv/bin/pytest -q`：629 passed，0 failed，0 skipped；3 条既有警告（测试类收集 2 条、Starlette/httpx 弃用 1 条）。
- 随后 CI 发现 Compose 的 JSON 序列化在版本间会省略 `create_host_path=false`。提交 `100b1cf` 仅修复测试兼容性，覆盖显式/省略 false 两种输出，并确认自动创建目录、可写挂载及向 API/Web/Migrate/Bridge 暴露策略均被拒绝；该文件 15 项通过（新增 1 项），Ruff/diff 检查通过。运行代码、镜像输入和部署配置未变化。
- 修复后 GitHub Actions run `39151725058`：后端 612 passed、18 skipped（CI 默认不启用受控 Docker）、3 条既有警告；Web 61 passed、0 skipped，安装/类型检查/构建通过。18 项 Docker 测试已有前述本地完整验收结果，CI 的跳过不作为集成通过证据。
- 新建独立数据库 `hypertest_adr013_migration_20261019_final` 执行 `alembic upgrade head`：从空库顺序完成 0001 → 0014，head 为 `0014_harness_operations`，没有历史绑定回填。
- PostgreSQL 回归包括跨表问题互斥、绑定/Job/Attempt 关系、旧 epoch 与过期 claim 拒绝、终态不可重开、丢 ACK 对账、未确认结果预算预留、报告完整性与 Gate 新鲜度，以及 GitLab 未知结果不重复 POST。
- Node 22.22.0：`npm ci`（0 vulnerabilities）、`npm run typecheck`、`npm test`（61 passed）、`npm run build` 全部通过。最终 Linux Compose 检查见上文；构建或合成 UI 回归不代替上述真实模型链。

真实 Web 另复核了终态绑定的任务历史：失败记录保留，重试按钮替换为“从项目创建新轮次”的提示与链接。验收结束停止本轮临时 Web/API/Worker/Bridge 进程及本地 PostgreSQL 容器；`hypertest-one-pg17-data` 卷、数据库、报告、源码和会话资料全部保留。

## 交付边界

本轮只在独立 Linux staging 栈验证新拓扑。正式实例仍为 `0a2af9c4f5034c118f1a19abd786290f0959a648` / `0012_api_environment_v2`；原 PostgreSQL 卷、Artifact、源码、认证、`45.76.149.233/32` 白名单和 SSH 隧道保留。正式切换应按 [部署与恢复手册](CONTAINERIZED_DEPLOYMENT.md) 在合并发布后进行，不能同时让两个 PostgreSQL 容器挂载原 PGDATA。

本轮独立执行 `ops/check-remote.sh`，正式 API/Worker/Web/nginx active、PG healthy/SELECT 1、API/Worker 与 Web HTTP 均通过；另新建临时 SSH 转发验证正式 HTML 和 API health 均 200，随后仅关闭该临时隧道。正式 release、schema、业务计数、原 32 个 Artifact（79,623 字节，manifest `7ef4dd1171808d9b0878ac17e6d50ace2018ac5a98bee05ce3759af4fe0f1d5c`）、PG 卷、服务 PID 和 UFW 与前置取样一致。

验收结束已停止 staging 的五个容器与 Bridge，两项 staging systemd unit 均 inactive/disabled，四个 staging 端口全部关闭；仅移除自有网络守卫，保留所有卷、备份、恢复目录、会话和镜像。最终正式快照 `adr013-staging-production-final.json` 与前置 JSON 逐字段完全一致，正式 Web/API 仍为 HTTP 200。

剩余范围：正式迁移及切换后的允许/拒绝公网来源复核；真实 GitLab 提单；Claude Code / 其他 Harness 适配和真实验收；多宿主调度。当前实现限定单宿主 Codex，未声称这些能力完成。
