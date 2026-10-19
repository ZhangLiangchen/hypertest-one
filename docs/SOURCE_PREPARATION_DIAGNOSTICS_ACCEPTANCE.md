# 源码准备失败诊断与关联重试验收

日期：2026-10-19（Asia/Singapore）。基于 PR #12 合并后的 `4d597d41a4dff74df3fcb7d9bf32b2d8aff91010`。本节记录增量 PR 合并前的功能验收与生产只读核对。后续合并、部署身份及上线验证另见本机交接目录 `hypertest-one-handoff/pr13-deploy-20261019`，不得将本节旧证据重标为新生产验收。

## 第一阶段缺口与本轮范围

| 优先项 | 核对与结果 | 边界 |
|---|---|---|
| 源码准备失败无法定位、恢复 | 已补失败阶段、受控分类、双语行动建议及原任务关联重试；真实网络失败后恢复完整周期 | PR #10 旧失败没有保存 stderr，不能追认其原因；其他分类由定向回归覆盖 |
| 关键写操作的真实窄屏验收 | 实测390×844完成创建项目、导入PRD、创建/启动Run、查看失败、点击原Job重试与读取报告 | 属于本地隔离服务，不能冒称生产窄屏完整写流程；PR #12原合成交互/生产只读证据保留 |
| 当前状态与历史交付容易混淆 | README/MVP/本阶段索引增加当前只读核对与新验收入口，标明PR #11冻结段落 | 不改写PR #11/#12证据身份或将旧测试计数归给新代码 |

第二 Provider、真实 GitLab 外部提单、多主机、RBAC、通用语言/SIT仍是独立需求与验收范围；本轮没有创建外部Issue或通知他人。

## 实现与规范

- Workspace服务产生 `hypertest.source-preparation-diagnostic/v1`；Worker保存 `SOURCE_PREPARATION_FAILED` 及受控 result，API在读边界重新投影，Web使用固定中英文本。阶段覆盖输入、目录、Git初始化/remote/fetch/checkout、内容校验与发布。
- 分类包括认证、仓库访问/不可用、网络/代理、TLS、提交不可用、存储、超时、Git缺失、无效输入、内容完整性和未知错误。这些是错误线索，不证明最终根因或远端仓库/认证状态。
- 准备路径的Git命令每流最多采集16KiB；stderr仅在内存有界分类。原始输出、命令、URL、路径、凭据、Provider内容不进入诊断。未知/不兼容对象不展示正文；旧固定错误精确匹配后显示“未记录，无法追认”，不猜底层原因。
- 进程失败与真实HEAD/origin/tracked内容不匹配分开；超时、权限、认证、存储等故障保留可修环境后的重试。符号链接循环、异常origin、非法UTF-8和进程启动错误均返回固定安全说明，保留原目录/链接；取消继续传播，清理失败不覆盖原错误。默认Runner/Agent读取完整tracked文件列表的8MiB边界保持。
- 显式retry建立新Job并保留 `retry_of_job_id`、原payload和终态历史；固定输入变化使用审阅后的新轮次。原Binding恢复/终态准入、有效lease/claim、取消与旧epoch边界保持；迟到诊断不能覆盖已提交终态。

诊断属于Operational State，不是Finding、Execution、Evidence、Verdict或Agent协议。领域模型§23.1拥有持久化/历史规则，技术架构§20拥有Workspace职责；本轮同步两份规范及Web指南。无新增表/迁移，Alembic仍为 `0014_harness_operations`，不改变TMP wire/profile或Gate算法。

## 自动化与独立复核

运行后端源码为 `d39800db77ef9b1a5c2690884105e4e286ab8dae`。最终检查使用全新PostgreSQL容器中的独立测试库，从空库升级0014；未连接开发或生产数据库。源输入清单在检查前后逐文件相同。

| 检查 | 结果 |
|---|---|
| Ruff / diff-check | 通过 |
| Alembic upgrade/current/heads | 两个独立库升级成功，head均0014 |
| `HYPERTEST_TEST_CONTROLLED_DOCKER=1 pytest -q` | **808 passed / 0 skipped / 3既有warnings**，146.18秒；含18项实际Docker检查 |
| Web `npm ci` / `npm test` | 安装成功；**104/104**通过 |
| Web typecheck / production build | 通过；最终局部对比度修正后重新完成104项、typecheck与build |
| 独立代码复核 | 发现并修复校验进程错误分类及符号链接异常脱敏两项P2；再次不连DB复现通过 |

安全投影回归直接故意持久化包含canary的Operational诊断，再通过真实HTTP读取，确认固定说明重新生成、未知版本/枚举丢弃、原终态行不改。其余覆盖取消、lease过期、三种准备入口、retry lineage、有界管道、存储/启动异常、真实Git文件列表与原文件保全。它们是回归，不能替代以下真实模型链。

中途的758项和780项检查各自保留日志；780项运行期间边界修复文件曾变化，不作为最终冻结证明。最终808项及其源清单才属于上述固定后端。

## 真实Web → 失败诊断 → 关联重试 → 完整周期

独立目录：`/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/source-diagnostics-20261019`。

| 身份 | 实际值 |
|---|---|
| Project | `01a15373-dc67-79a7-9f73-f2d71538261b` |
| Run | `01a15375-a9a3-76e8-b1b5-98da0472c426` |
| 首次失败Job | `01a15375-f83e-79be-8398-c97966bf7019` |
| 关联成功Job | `01a15378-6f15-74d9-8a8c-27489daebc57` |
| 被测固定SHA | `0a2af9c4f5034c118f1a19abd786290f0959a648`，`examples.api_sut.app:app` / API-v2 |
| FINAL | `VER-01A1537A08D57C9A81796AF58C27021B`，sequence1 / RELEASE_READY |
| 报告SHA256 | `dc3be52238065aa2d9af35c1cbfb69235738270455cf986a73bbd1036adda7d7` |

通过真实浏览器在390×844创建项目，选择PRD文件、审阅固定输入和执行环境，提交Run与自动源码准备周期。PRD724字节、配置2字节均与SourceSnapshot固定hash及原始输入相同。

仅在本轮Worker专用Git配置为精确仓库注入不可达代理，实际fetch失败：`fetch_commit / network / exit128`。独立GET/SELECT证明13类Binding/Session/Mission及测试事实计数全0，10/10失败检查通过。没有启动模型或正式测试执行；原有Runner只读就绪预检仍可发生。Web中文390px、英文1280px和390px显示阶段、分类、退出码及行动建议，不显示原始proxy/命令/URL。

只从本轮配置删除故障项，保留原include与继承环境，不改全局Git/CLI、不重启或清数据；在390px原任务详情点击 **Retry as new task**，创建新关联Job。真实Codex在一个主原生会话内串行提交四类Mission，平台接受Proposal；可信Docker采集 **37/37 PASS、0失败/错误/跳过**，形成5Requirement、6Risk、10Case、6Implementation、1 OFFICIAL Execution、5 RUNNER/VERIFIED Evidence、0Finding、FINAL RELEASE_READY及报告。Job为SUCCEEDED/REPORT_ACCEPTED，原Binding/主Session均CLOSED，epoch1，总活跃调用结算106秒。

独立验证为：完整周期32/32、原生身份/预算7/7、失败到重试保全8/8（另有API读取16项）；原FAILED Job全行摘要、原payload与Source/Policy完整投影保持。报告、可信Artifact、JUnit与Evidence manifest分别读回并重算hash。没有mock Agent/Runner或SQL灌入Canonical State。Bridge在报告接受后受控关闭已停止调用的INTERRUPTED记录不代表Job失败。

模型周期使用d39800d对应前端。随后唯一产品修正是新增诊断字段label使用现有 `--ht-muted`；重新构建后真实只读打开原失败和报告，确认中文/英文、标签颜色 `rgb(82,97,119)` 对背景 `rgb(245,232,230)` 约 **5.27:1**。390×844的DOM `scrollWidth=390`、可见Drawer宽366；原报告正文/摘要可读，浏览器console为0 errors/warnings。会话CLOSED后原失败仍有诊断和新轮次入口，普通retry已隐藏。未因该视觉修正重跑模型或改写历史。

浏览器证据在交付目录 `evidence/browser/`、DOM检查在 `evidence/browser-*-dom.json`；独立API/SQL与结构化汇总在 `acceptance/independent-rollup.json`。一项早期测量选择了隐藏dialog而得到0宽，已弃用；最终宽度以可见dialog过滤后的366为准。PR #12的生产窄屏只读与合成检查保留原范围，本轮不声称完成生产窄屏写入、问答、epoch恢复、崩溃或产品缺陷诊断。

## 生产只读核对与数据保全

2026-10-19 17:03 SGT核对：远端main及生产源码均为 `4d597d4`，PR #12已合并、main CI test/web成功；最新交付SHA256SUMS的71项全部通过。生产Web镜像 `eec0cf1d…`、API `4897e70e…`、Worker `e99cda25…` 与交接相同，Bridge `95e92c5`、ops manifest `90037658…c2c96`、schema0014保持。

五容器healthy/restart0/OOMfalse；stack、Bridge与backup timer active，内部health200。受保护nginx配置、Docker guard/UFW、SSH禁转发及公钥/密码恢复保持，回环Web/API拒绝。39张非观测表逐行摘要、60 Artifact、2380 Workspace、11 Bridge文件与27指定原生会话文件均与PR #12相同；OAuth只读状态/元数据与受保护配置摘要保持。未复制或输出认证文件，没有生产写入、部署或重启。

未请求会写Operational队列的capabilities/readiness，不将本次只读核对称作动态能力或新的生产模型链验收；未重复外部来源矩阵、配对备份或恢复。PR #12原备份manifest仍为 `40fb155ad4f3375e7b6065ecfa36cf1ae6265fa433adbd4407f33027fba414c6`。

本地服务、PostgreSQL容器/卷/两个库、Artifact、Workspace与Bridge目录均独立创建。最终仅停止本轮拥有的临时服务和新PostgreSQL，所有新旧卷、验收/测试数据和原生会话文件保留；旧开发PG保持原停止状态，原OAuth、CLI与全局Git配置不变。临时密码/Bridge key仅在交付根的受保护目录，排除出可移交源码归档和SHA清单；不复制OAuth。停机与原环境比较另存交付记录。

## PR #13 合并前独立审查补充

独立审查发现一项 P2：已有检出符号链接指向不存在目录时，subprocess 的 cwd ENOENT 被误判为 Git 缺失。现仅固定 executable filename `git` 的 FileNotFoundError 归类为 Git 不可用；其他 ENOENT 归类存储，且安全异常不保留工作目录路径。真实缺失 cwd、Git 在预检后消失的初始化/校验启动三条进程路径均有回归，原目录/链接保留。

修复后在原专用 PostgreSQL 容器中新建独立库，从空库升级0014并冻结源码运行受控 Docker 全套：**812 passed、0 skipped、3既有warnings，143.03秒**；输入逐文件摘要前后相同。Web 独立复核重新执行 **104/104**，源码未改。该补充不重标上文 d39800d 的真实模型周期。
