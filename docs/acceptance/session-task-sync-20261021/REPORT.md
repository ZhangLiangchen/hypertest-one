# Codex 会话任务同步：本机开发检查

**范围：LOCAL_DEVELOPMENT_ONLY。用户已明确要求优先远程环境；本记录不代表线上同步完成。**

本轮按 [ADR-018](../../architecture/ADR-018_CODEX_SESSION_TASK_SYNC.md) 验证管理同步。使用真实既有 UC18 资产，没有运行 SUT 测试、创建替代样例应用或调用平台执行路径。远程环境的版本、schema、能力、Project映射和授权由主控另行实际核验；本地UUID不能用于盲写线上。

## 实际保存与读回

- 来源 Codex 会话：`01a143f4-4ec0-7451-ab23-8e59c6deb223`，标题「xblock异步接口能量购买供应商接入」。父任务确认捕获时会话仍工作，因此管理任务保持 **IN_PROGRESS**，reported result **FAIL**。
- 捕获时间：**2026-10-21 15:33:54 +08:00**。直接读取现有 `hypervise_pure/docs/usecases/UC-TX-18-dev166-multi-energy-provider-routing/` 的设计、库存、执行报告、完成材料和独立业务复核；读取后冻结，不把后续可变文件冒充同一快照。
- 库存实际15项；本次按原执行报告导入12项已执行逻辑用例，另3项 CASE-013/014/015未导入，不推定它们通过或已经执行。
- 12项自动结果 **10 PASS / 2 FAIL**，CASE-002/CASE-009保留FAIL；原独立业务报告 **11 PASS / 1 FAIL** 作为独立 report key保存。AT03自动FAIL没有被业务复核覆盖。
- 官方 MCP SDK 启动真实 stdio 子进程 → 私有 daemon → scoped HTTP API，先同步计划/12用例/原执行报告（version1），再显式同步既有独立复核报告（version2）。第二次省略cases，原12项及原失败仍在。
- 每次原key重复调用只查询回执；按会话读取任务、用例和两份原始Markdown，并逐字节与捕获原文比较。version1读回仍只有原执行报告；version2包含两份报告。

本机 Project：`01a15d61-85ef-7ded-8371-81ce7675f1fb`；Task：`01a15d61-87f5-7f9a-adac-4a226f23a7bb`。页面：<http://127.0.0.1:3001/tasks/01a15d61-87f5-7f9a-adac-4a226f23a7bb>。平台身份是 **AGENT_REPORTED**，没有改造成 legacy VERIFIED Evidence、FINAL Verdict或发布通过。

## 没有触发平台执行

本次同步前后直接查询同一隔离PostgreSQL，各表计数完全相同：

| 表 | 前 | 后 |
| --- | ---: | ---: |
| test_runs | 30 | 30 |
| durable_jobs | 30 | 30 |
| run_execution_bindings | 18 | 18 |
| test_executions | 3 | 3 |
| evidence | 3 | 3 |
| verdicts | 0 | 0 |
| native_test_runs | 12 | 12 |

这些非零值是本地隔离库已有测试记录，不是这次同步生成的执行。具体观测见 [MCP_OBSERVATIONS.json](MCP_OBSERVATIONS.json)，检查完成时间15:33:55 +08:00。

## 客户端检查与修正

最终客户端检查：

```sh
.venv/bin/python -m pytest tests/test_session_task_mcp.py tests/test_interactive_client.py -q
```

**19 passed in 0.23s**。新管理用例覆盖无device/workspace/host绑定同步、完整请求digest与compact journal、原key查询/冲突、失答后重启、404不重POST、严格查询参数、原FAIL/Markdown保留及官方SDK工具协商；包含既有客户端兼容回归。Ruff检查相关客户端、测试及实际验收脚本通过。该输出来自本轮工具chunk `466e16`；原测试stdout未重定向成独立日志，不冒称存在原始pytest日志文件。

MCP journal只存Project/session/key查询身份与完整请求digest，避免重复持久复制大报告；原始Markdown直接保存在服务端PostgreSQL ReportRevision。旧工具的journal行为未改变。

一次捕获前置检查发现库存15项而非预期12项，脚本在任何Project/grant/sync POST前停止（chunk `d092e4`）；核对为额外恢复与离线契约case后，明确选择原执行报告中12项并保留excluded清单。这个开发脚本失败不是SUT失败、同步UNKNOWN或被删除的执行历史。

## 材料与后续

- [UC18_SOURCE_BUNDLE.json](UC18_SOURCE_BUNDLE.json)：真实计划、12用例、两份原始Markdown、来源文件byte/hash及捕获时间；**无目标Project UUID**，可供远程实际映射后复用。Hash仅标识捕获字节，不是执行证明。
- [accept_uc18_sync.py](accept_uc18_sync.py)：明确仅本机的实际SDK验收脚本。原key与私有journal保留；不能把脚本改URL后直接重复部署或创建线上Project。
- 私有本机配置、scoped token、bootstrap intent与journal：`~/.local/share/hypertest/session-sync-dev-20261021/`。不复制到仓库或聊天。
- 规范与MCP源代码的实现不等于远端已发布。下一步先核验用户指定远程环境的能力/版本与授权，再映射已有Project、GET已有同session任务与版本，形成审阅的远程同步请求；失答只GET原key。

本轮没有生产部署、生产迁移、远程授权复制、VPN/白名单调整或SUT测试重跑。原raw报告、自动失败、独立复核、原UNKNOWN/恢复局限与旧两种受管模式历史均保留。

## 后续审查与远端材料准备（不覆盖上述本机事实）

审查发现原客户端仅把2xx JSON对象视为ACK，未核对回执是否属于原key；内存边界复现`original-key`请求收到`different-key`却ACKED（chunk `e0183d`，没有环境写入）。已仅为新管理工具修复：核对薄回执的status/profile/source、Project/provider/session、task UUID、原key及expected version+1，后续查询固定已确认task ID；无效回执保持UNKNOWN、只GET。保留旧有效回执关联，避免连续无效查询污染原task ID。旧执行工具不改。

MCP按会话读取现为固定version的current-only JSON分页，limit默认/最大24,000字符，不带无界全history，不调大旧1MiB通道；完整原文按next_offset拼接，首片后固定version。客户端对offset、version、长度、complete、next_offset和source进行校验。相关客户端组合检查更新为**37 passed in 0.46s**（chunk `877fd2`）；后续远端候选集成结果单独登记，原本机实际SDK记录仍是其当时完整读回方式。

远端材料更新为[UC18_REMOTE_SOURCE_BUNDLE_V2.json](UC18_REMOTE_SOURCE_BUNDLE_V2.json)，15:51:38 +08:00派生，80,150 bytes。全部15个已生成用例纳入管理：CASE013/014/015来自原已冻结plan中的03a完整小节，无逐项结果则UNKNOWN；原12项自动结果、两份原报告、原15:33:54捕获时间保持。未刷新正在工作源会话，未改本机12项bundle/回执。实际远端SDK脚本见[accept_remote_uc18_sync.py](accept_remote_uc18_sync.py)，执行前仍需主控确认候选路径、scope与Project映射。
