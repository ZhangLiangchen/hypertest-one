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

## 自动检查

- `.venv/bin/ruff check src tests alembic`：通过。
- `HYPERTEST_TEST_CONTROLLED_DOCKER=1 .venv/bin/pytest -q`：629 passed，0 failed，0 skipped；3 条既有警告（测试类收集 2 条、Starlette/httpx 弃用 1 条）。
- 新建独立数据库 `hypertest_adr013_migration_20261019_final` 执行 `alembic upgrade head`：从空库顺序完成 0001 → 0014，head 为 `0014_harness_operations`，没有历史绑定回填。
- PostgreSQL 回归包括跨表问题互斥、绑定/Job/Attempt 关系、旧 epoch 与过期 claim 拒绝、终态不可重开、丢 ACK 对账、未确认结果预算预留、报告完整性与 Gate 新鲜度，以及 GitLab 未知结果不重复 POST。
- Node 22.22.0：`npm ci`（0 vulnerabilities）、`npm run typecheck`、`npm test`（61 passed）、`npm run build` 全部通过。最终 Linux Compose 检查另记；构建或合成 UI 回归不代替上述真实模型链。

真实 Web 另复核了终态绑定的任务历史：失败记录保留，重试按钮替换为“从项目创建新轮次”的提示与链接。验收结束停止本轮临时 Web/API/Worker/Bridge 进程及本地 PostgreSQL 容器；`hypertest-one-pg17-data` 卷、数据库、报告、源码和会话资料全部保留。

## 交付边界

本轮只在独立 Linux staging 栈验证新拓扑。正式实例仍为 `0a2af9c4f5034c118f1a19abd786290f0959a648` / `0012_api_environment_v2`；原 PostgreSQL 卷、Artifact、源码、认证、`45.76.149.233/32` 白名单和 SSH 隧道保留。正式切换应按 [部署与恢复手册](CONTAINERIZED_DEPLOYMENT.md) 在合并发布后进行，不能同时让两个 PostgreSQL 容器挂载原 PGDATA。

剩余范围：正式迁移及切换后的允许/拒绝公网来源复核；真实 GitLab 提单；Claude Code / 其他 Harness 适配和真实验收；多宿主调度。当前实现限定单宿主 Codex，未声称这些能力完成。
