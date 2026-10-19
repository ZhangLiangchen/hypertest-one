# Web 结果复核与修复后复测验收

日期：2026-10-19，Asia/Singapore。范围为白皮书 §20 完整测试周期、§22 状态/产物/证据
工作台和 §25 第一阶段受控 API/Backend 功能测试。本轮完成隔离本地真实验收并交付代码；
生产继续使用 `f415fd0` 源码 / `95e92c5` 运行构建 / schema0014，生产部署记录仍以
[ADR-013 正式验收](ADR013_PRODUCTION_DEPLOYMENT.md)为准。

## 补齐的操作闭环

| 原缺口 | 本轮行为及证据边界 |
|---|---|
| 需求/风险/用例只有摘要，难以确认测试内容 | 点击标题读取完整 Canonical 说明、前置条件、预期结果，沿需求/风险/用例/实现关系跳转；不展示未接受的 Provider 草稿 |
| 无法查看已接受的生成测试代码 | 新增 Run 范围 GET 源码接口，复用 Runner 的 Artifact 根目录、符号链接、内容寻址与 SHA 校验，返回 UTF-8 text/plain；仓库原有测试保留固定提交引用 |
| 报告入口离质量结果较远 | 概览和已完成任务均可进入报告；保留 FINAL Verdict 为主要决策，报告不代替可信执行事实 |
| 终态和恢复后仍提示重试 | CLOSED/FAILED/CANCELLED 引导已保存结果与新轮次；RECOVERY_REQUIRED 核验原会话，ACTIVE 恢复后引导原失败 Job；刷新不依赖 mutation 的临时成功标志 |
| 修复后需重填全部输入 | 在原 Project 通过“基于本次运行创建新轮次”复制并审阅原输入；显式选择修复 SHA/服务。新 Run、新请求身份、新 Binding/原生 Session，原结果保留 |
| 策略或输入可能悄悄改变 | 默认保留全部原 Policy，包括未知扩展字段；明确选择替换才使用 Web 表单策略。PRD/context 读取保留 U+FEFF、CRLF、尾空格和空文本；读取失败不替换草稿 |
| 无绑定的首次源码准备失败可绕过重试关联 | 顶部入口及提交前 fresh-state 检查要求关联原 ADVANCE_RUN Job 显式重试；相同请求未知结果仍先按原 key 核对，旧的其他操作不误拦 |

环境只复制请求，创建时重新解析可信实际 image ID；归档 API-v1 或未绑定环境明确拒绝
直接复制，要求用户重新配置当前支持的环境，不静默升级。复制入口不自动提交业务请求，
已有草稿需明确替换。同页关闭和中英切换保留草稿；刷新不承诺恢复未提交草稿。

源码读取接口为
`GET /api/v1/test-runs/{run_id}/implementations/{implementation_id}/content`。
跨项目/快照返回404，缺失/篡改/符号链接/非UTF-8或越界文件返回409，不泄露存储路径。
同 SourceSnapshot 的不同 Run 可读取共享 Canonical 实现。返回 nosniff、no-store、
固定 SHA 与实际字节长度；没有新增独立 size 字段或改变 Evidence 信任规则。

无数据库迁移，head 保持 `0014_harness_operations`。四份奠基文档只同步实施状态及
实际生产版本，不改变字段、领域生命周期、工具权限、Planner 或 Gate 规则。

## 真实 Web → Codex → Docker 双链

在独立数据库 `hypertest_p1_web_acceptance_20261019` 与独立 Artifact/workspace/Bridge
目录执行。所有创建、文件选择、复制草稿和重试由实际 Web 控件完成；模型为既有官方
Codex CLI0.163.0 的真实调用，沿用本机 OAuth，没有模拟 Agent 输出或直接 SQL 写入
Canonical State。正式执行使用实际预制 `python-api-v2` Runner，HTTP 业务断言访问
容器内服务，不使用 TestClient、mock 或 Agent 自报结果。

Project：`01a15219-ef7e-7191-8daf-36d55debad5c`。
仓库：`https://github.com/ZhangLiangchen/hypertest-one.git`。
通过系统文件选择器实际导入 `sum-api-prd.md`，1980 UTF-8 bytes，SHA-256
`a77ead1718e820dc0f7c421f152b02dd112d5fa0fceea8b8b14cca577f3bb2ec`。
配置为空文本，SHA-256 为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

| 登记项 | 故障版本 | 通过复制输入建立的修复版本 |
|---|---|---|
| Run | `01a1521f-c015-7de1-aa28-a1461640ea7c` | `01a15229-f32f-75c1-8db7-e0892633aa49` |
| 固定 SUT SHA | `248b45dfcae2880087951f79baec5c4e7af26856` | `0a2af9c4f5034c118f1a19abd786290f0959a648` |
| 明确选择的服务 | `examples.api_sut.broken_app:app` | `examples.api_sut.app:app` |
| Req/Risk/Case/Implementation | 4 / 4 / 4 / 4 | 4 / 6 / 11 / 6 |
| 官方 Docker 执行 | 1；19 PASS / 9 FAIL / 0 ERROR / 0 SKIP | 1；50 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| 诊断和质量结果 | 5类Mission完成，含诊断；1个CRITICAL PRODUCT_DEFECT、5份可信证据、FINAL RELEASE_BLOCKED | 4类Mission完成；0Finding、5份可信证据、FINAL RELEASE_READY |
| 原生会话 | 唯一主Session、epoch1、101/3600秒活跃预算、终态CLOSED | 独立新主Session、epoch1、92/3600秒、终态CLOSED |
| 独立检查 | 44项全部通过 | 56项全部通过 |

故障确实来自加法处理器执行减法：a=2,b=3 返回-1而预期5。9条JUnit failure均为
AssertionError，没有环境error或skip；Finding来自已接受DIAGNOSE_FAILURE Proposal，
SUPPORTS关系指向同Run的RUNNER/VERIFIED Evidence。未修改应用或弱化断言以取得通过。
修复版本不是平台自动修复：操作者通过新轮次草稿明确选择已有修复 SHA 和 ASGI app。

两份已接受报告 SHA-256：

- 负向：`6c3e718bfea1256c500c9adebbfff4778247f14edd3d06a7573e38ddf6481585`。
- 正向：`5efbdda9430d9c46065bbdbd299605d65942ba10cd5cc2c6c3f48c54e8ef9928`。

独立重算 Gate Evidence manifest：
负向 `3148c120efabbb0d8c0cd075a573c2e47bb53e9f1724b46043a9c9702d8924b9`，
正向 `d66aa42c652c049386ecf1a3409eecc09a6077a0313745f90116cf8eb6af0277`，均与平台一致。

### 首次准备失败与显式重试

正向首 Job `01a1522a-c08e-7754-b3be-f9a8c02c6143` 在Git准备阶段失败，尚无Binding、
Session或模型调用。后续在相同Worker环境、独立临时目录获取相同提交成功（4.636秒），
没有关闭TLS、修改全局Git或更换OAuth。首次底层stderr未持久化，因此不追认具体
网络故障原因。失败快照保留，并据此补齐无Binding状态的原任务重试引导。

通过Web显式创建 `retry_of` 关联 Job `01a15230-6ace-7ac4-b176-2c05b04d75e2` 后，
完成真实正向周期；没有重写首个失败，也没有产生第二次官方Execution。
原collector两条硬性要求“两类人工问题必须发生”的检查为false，本轮PRD没有要求
人工问答，实际也未发生。原结果保留并明确标为不适用；56项独立清单不伪称已完成
新的问答验收，之前的真实问答证明仍见其各自验收记录。

### 输入和历史保全

实际Web从负向Run进入新轮草稿，原SHA/PRD/context/环境/完整Policy均可见。
修改SHA后关闭草稿、切换为中文、重新打开，SHA与正文保留。只明确修改SHA和服务app；
19项持久输入对照全通过，同Project、新SourceSnapshot、同Policy内容与hash，原服务
入口不变。当前实际image再次解析绑定；本次两轮恰好解析到同一预制arm64镜像。

独立检查负向历史38个表作用域、234行完整字段SHA不变，其中包含正向首个FAILED Job；
17个旧API资源完全一致，12个Artifact引用、8个唯一内容摘要及10个原快照文件全部
校验通过。原失败Execution、Evidence、Finding、FINAL和报告均保留，不将新Run通过
解释成旧Finding已解决。刷新终态页面没有重提业务任务。

## 自动检查与真实界面

- Ruff `src tests alembic`：通过；独立test库 Alembic upgrade head：0014。
- 后端：655 passed、18 opt-in Docker skipped、3条既有警告。142份源码/测试/迁移及
  配置输入在检查期间与结束后摘要相同。首次测试配置误用了queued验收模式的失败
  日志保留；修正为原测试模式、仅覆盖独立DB后全量通过，不属于产品失败修复。
- Web独立副本 fresh `npm ci`、86项回归、typecheck、production build均通过；
  npm audit为0。首次84项通过后，实际准备失败暴露无Binding边界，新增2项回归后
  重跑受影响Web检查；依赖未变。52份最终Web输入摘要保留。
- 真实浏览器检查：文件选择/Review、需求/风险/用例关系、生成源码、概览与任务报告
  入口、终态操作、复制输入、换SHA/app、空配置、完整Policy、同页语言切换、显式
  关联重试及刷新已完成结果。1280px桌面与390px同源iframe视口检查并保存截图；
  修正窄屏提示按钮压缩正文的问题。该视口检查不是物理手机或触摸设备验收。
- 独立最终代码审阅未发现阻断问题；Impeccable机械检测为空。自动回归中的合成数据
  仅用于状态/错误边界，不作为真实模型或Runner验收依据。

## 证据及本轮边界

本机证据目录：
`/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/p1-web-20261019/`。

- `acceptance/negative-acceptance.json`、`positive-acceptance.json`：44/56项独立清单。
- `acceptance/copied-inputs-persisted-comparison.json`、`copied-form-inputs.json`：真实表单与
  持久输入对照；`negative-history-preservation.json`：旧行及产物保全。
- `acceptance/*-final/`、`*-native*.json`、`*-relations.json`：实际API、JUnit、SQL和原生
  身份证明；`diagnostics/git-probe-result.json`：后续Git诊断，不代替首次故障原因。
- `acceptance/*.png`：实际输入、用例、源码、报告、质量结论与390px视口截图。
- `evidence/backend-checks.json`、`web-final-inputs.json`、`web-checks.json`及`logs/`：
  自动检查与输入身份。认证资料和Provider原始对话不放入证据包或Git。

本轮验证支持的受控单服务API路径，没有将它扩大为任意语言/服务/SIT、完整语义覆盖、
物理移动设备、其他Provider、多宿主或真实GitLab外部提单验收。Finding后续处置与
关闭Session之后的独立Gate重评估仍需明确准入契约；当前提示旧判定/报告保持历史，
验证修复通过新Run取得新事实与结论。该缺口未默许绕过绑定守卫。

生产数据、Codex OAuth、45.76.149.233/32白名单及SSH配置未改。本轮没有合并或部署
生产；实际生产状态由独立只读检查和已有部署记录确认。隔离验收结束后仅停止本轮
拥有的本地服务，原数据库卷、开发数据和验收记录保留。
