# Local 预创建任务与显式绑定：2026-10-23 验证记录

**范围：ADR-024 管理接口、Local 客户端及兼容回归；真实原生绑定 E2E 尚未证明。**

本记录保留首次失败和原失败项复验，不把后续通过改写为首次运行全通过。HyperTest测试服务器是单用户专用测试环境；本轮使用临时隔离容器和数据库，没有切换原服务器主栈，也不代表Cloud执行或业务SUT测试完成。

## 源码与执行环境

| 项目 | 已记录身份 |
| --- | --- |
| 候选A | `b56ca334153583b91600ec40160014a1e60788bb`；tree `28decf2f6e4e1a4fe3b12778338b62b285033e76` |
| fixture修正b6 | `b6babe8d49aa76614f4bae4e1ce1a4e8d2fc71ad`；仅为新安装fixture补选Project，4行测试修改 |
| caller fence候选F | `4c6231e559ca5fd750112fd4f94291c9673d8b43`；MCP/IPC/协调器修正与独立拒绝断言，首轮远端定向128 PASS / 3 FAIL |
| caller fence修正F2 / 私有源码客户端 | `86f7659254cf2253de6376e64b287352e6df7f89`；原3失败及14个相关边界定向复验17 PASS / 0 FAIL / 0 SKIP，2.70s |
| 执行位置 | 远端临时隔离环境；本机没有运行pytest、Web测试、typecheck或build |
| Python / 导入源 / 数据库 | Python `3.12.15`；workspace `src`；独立 `test-postgres` |
| 迁移 | 隔离库升至 `0024_local_task_binding`；父级 `0023_project_task_management` |
| A/b6 Python镜像 | `sha256:df18428df8a0f9189c84e7424d214b4c50092af1f9dca5842a00c41c39bda316` |
| A/b6 PostgreSQL镜像 | `sha256:327daa8fae7178d61f93142f146b098467b345e10997b9eb79f63bd58e5c8f3c` |

这是Git来源的隔离回归，不是将未提交工作树打包部署。原始证据由远端执行者保存，主会话已核对其回执；本文不复制私有验收原文、认证材料或聊天记录。

## 原始运行与复验

| 运行 | 范围与结果 | 解释 |
| --- | --- | --- |
| A首次 | 11个相关测试文件，161项：157 PASS / 4 FAIL / 0 SKIP，16.98s；90条SQLAlchemy警告 | 原Junit与日志保留，没有抹除失败 |
| 原4失败项定向复验 | b6测试fixture及隔离临时目录设置修正后：4 PASS / 0 FAIL / 0 SKIP，0.32s | 仅复验原4项，没有在b6重跑全部161项 |
| 按case ID归并的最终覆盖 | 161个唯一用例最终均有PASS记录，共165次用例执行 | 不写成单次“161全通过”，也不覆盖首次4 FAIL |

首次3项失败来自远端临时目录默认`noexec`阻止测试所建fake CLI。复验仅为该隔离容器的tmpfs允许`exec`，继续保留`nosuid,nodev`，没有修改服务器主机默认策略。另1项失败是新增安装fixture未配置所选Project，产品按约束正确拒绝；b6只补齐该fixture的`project_id`。

验证覆盖预创建UNBOUND、intended actor授权、一次性BIND、同UUID连续版本、固定版本读回、错actor/Project/source/版本拒绝、soft delete/恢复、旧auto任务历史保全及resume、UNKNOWN原key查询和已批准产物保全。合成SessionStart、故障注入API和ASGI/PostgreSQL测试均属于管理/适配器证据，不是实际Codex、Claude Code或DeepSeek父子会话的原生transport验收。

## Caller fence后续修正的独立边界

A/b6远端运行早于本次逐调用caller fence修正。随后静态审查发现：仅检查“所填父session已有私有root”不能防止child携已知父ID发起MCP绑定。此次源码补充Codex CLI `0.144.6`的宿主`_meta.threadId`→MCP request context→私有IPC→协调器核对；新BIND与手动已绑定Task显式新sync均受此限制。原生metadata不从arguments选取，不上传平台，也不是服务端独立身份证明。

Claude Code与DeepSeek的逐调用caller适配尚未实现，新MCP绑定与手动已绑定任务显式新sync应明确unsupported；既有auto任务resume、授权GET和原key只读恢复保留。旧`local-v0.1.0`固定包、tag、digest及旧三宿主证明保持原身份。

新增独立断言包括child携已知父ID、手动Task同步含旧target文件缺私有flag、arguments伪造metadata、缺context、unsupported宿主及PREPARED不得借恢复转成新POST。SDK内存transport→真实私有UDS→service/协调器测试由fixture提供metadata；通过结果属于协议和适配器验证，不能当作真实宿主注入和parent/child E2E，也不能由上述161项历史结果推导通过。

F首轮远端对受影响的5个文件定向验证：**128 PASS / 3 FAIL / 0 SKIP，12.29s，36条警告**。执行者以`evidence-native-context-F/junit-F.xml`和`pytest-F.log`索引保存原件，失败不删除、不追认为首次通过。其中1项发现真实恢复回归：UNKNOWN BIND后携有效native context提交完整sync，错误地先做baseline读取并返回TASK_BINDING_REQUIRED，未优先查询原BIND key。另2项为独立测试预期的拒绝层不符：官方MCP SDK已按schema先拒绝arguments中的`_meta`或`native_caller_context`，实际零API写入且本地状态未变，测试原先误期待daemon的INVALID_TOOL_ARGUMENTS。

F2仅调整恢复顺序及上述两个精确拒绝文本断言：先按原BIND key query-only对账，再决定能否读取baseline/接纳新sync；PREPARED保持原状态，不借恢复发POST；child context仍须在相应新写入前匹配真实root。两个spoof断言改为完整SDK Additional properties错误文本，继续要求isError、零API调用及target/journal/snapshot逐字不变。F2从固定推送提交`86f7659254cf2253de6376e64b287352e6df7f89`在远端复验：**17 PASS / 0 FAIL / 0 SKIP，2.70s**，包括原3失败和14个与F已通过项重叠的pending/caller边界；没有全量重跑原128通过项。

F/F2按case ID归并，131个唯一用例最终均有PASS记录，累计148次用例执行；原3 FAIL保留。此汇总不等于F2单次131项全通过。私有源码客户端固定使用F2，不把仅有静态资格的A/F用于新caller绑定；服务器主栈部署、真实宿主E2E及新公开发行仍分别记录。

独立拒绝文件本地只做AST静态解析：21个测试函数、47个参数实例；没有在本机执行这些测试。静态评审已确认移除writer锁外的`PENDING→UNKNOWN`修改：manual PREPARED缺caller先拒绝，已发请求原key可只读恢复，锁内query-only遇未发PENDING只阻塞、不自动发送。

## 原件索引与清理

远端证据目录：`/var/tmp/hypertest-local-binding-20261023-f855-075600/evidence`。

| 原件 | 用途 |
| --- | --- |
| `summary.json` | 两次运行、逐例ID与唯一用例最终覆盖 |
| `junit-A.xml`、`pytest-A.log` | 首次157 PASS / 4 FAIL原件 |
| `junit-rerun-failures.xml` | 原4项定向复验PASS记录 |
| `migration.log`、`runtime-check.json` | 隔离迁移、Python、源码导入与数据库目标 |
| `cleanup.json` | 按owner label清理临时资源，`remaining=[]` |
| `services-before/after`记录 | 原主栈5个容器的ID、image、restart count、started time均保持一致 |
| `SHA256SUMS` | 原件摘要清单；该清单本身SHA-256为`832354090956585e874390320dd78c4ae7ca31bb5e8c70a218c0f5963cf6936f` |

执行者清理了本轮拥有的5个临时容器与1个network，未触碰原主栈5个容器、持久卷、任务/修订/回执或私有身份。本记录不等同最终服务部署、Web功能验收、新客户端公开发行、真实原生绑定E2E或Cloud执行证明。

F/F2原件独立保存于`/var/tmp/hypertest-local-binding-20261023-f855-075600/evidence-native-context-F`：

| 原件 | 最终记录 |
| --- | --- |
| `summary.json` | F 128 PASS / 3 FAIL；F2 17 PASS，原3失败加14个重叠边界；最终131个唯一case均有PASS |
| `junit-F.xml`、`pytest-F.log` | F首轮原3失败保留 |
| `junit-F2.xml`、`pytest-F2.log`、`rerun-source-sha` | 固定F2提交及17项定向复验 |
| `runtime-check.json` | 隔离执行运行环境与源码来源 |
| `cleanup.json` | ctxf本轮拥有的3个临时容器与1个internal network已移除，`remaining=[]`；原主栈5容器ID/image/restart/start time不变 |
| `prior-evidence-verification.log` | A/b6原摘要清单逐项`ALL_OK`，未改写旧原件 |
| `SHA256SUMS` | 清单本身SHA-256为`7609bb40a1b4286139b8cb0607a47d59d5a63dd33685b17f9a2473c20a95c88e` |

F/F2没有调用模型或业务SUT，没有变更常驻服务；清理后保留源码checkout、运行环境及证据供追溯。最终结论为相关远端管理/组件回归通过，SDK内存transport→真实UDS合成caller边界通过，真实Codex宿主parent/child绑定E2E仍为 **NOT_OBSERVED**；Claude/DeepSeek新caller适配仍unsupported。
