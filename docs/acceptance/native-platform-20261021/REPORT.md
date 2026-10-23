# 原生框架材料平台接入验收（2026-10-21）

**最小材料治理闭环已完成并验收；正式原生质量 PASS 未证明。** 两条真实 SUT 原生结果随后补录到本机 HyperTest，计划与77个用例被接受，2条执行记录、10份原始执行材料、报告验证、保守结论和顺序贡献者交接均可追溯。原生断言为 XBlock 17 PASS / Blockchain 60 PASS，平台执行来源始终 UNVERIFIED；这不证明当前部署、活链、业务 E2E 或发布通过。

## 实际范围与时间

[执行前分析与设计](../native-framework-20261021/TEST_PLAN.md)、[原生实跑报告](../native-framework-20261021/REPORT.md)及其 JSONL / 4份 Surefire XML / stdout / stderr / process 是原件。平台 create/submit 发生于 **06:44:25 UTC（14:44:25 SGT）**，早于它的原生运行时间分别是06:23:47–06:24:26 / 06:25:48–06:25:54 UTC；observed start/end 与 accepted/submitted 分别持久化。本轮是 retrospective intake，没有回填时间或宣称平台事前下发并执行了这些测试。

| 本轮真实轮次 | 用例 / 执行 / 原件 | 最终状态 |
| --- | --- | --- |
| XBlock `01a15d34-35d5-7199-8b78-4d6327053b4b` | 17 cases / 1 execution / 3份原始执行材料；另1份明确标注的治理control查证材料 | generation 2；报告 CONSISTENT，provenance UNVERIFIED；结论 UNKNOWN→UNKNOWN→BLOCKED，后者由 control-only UNKNOWN 操作阻断 |
| Blockchain `01a15d34-3637-7b59-9057-5bebc5ccc4fc` | 60 cases / 1 execution / 7份原始执行材料（含4 XML） | generation 2；报告 CONSISTENT，provenance UNVERIFIED；3条 UNKNOWN结论，包括最终代码下CLI显式评估 |

范围筛选、身份、时间及结论历史见[机器索引](CAMPAIGN_SUMMARY.json)和 [XBlock 最终状态](xblock-final-state.json) / [Blockchain 最终状态](blockchain-final-state.json)。派生索引不替代原件，也不因 Artifact hash 校验就获得可信执行来源。

同一隔离 QA 数据库还保留自动化测试 fixtures；[只读全库快照](database-state.json)中的96个 Project / 27个 NativeRun / 102个 NativeCase不等于本轮真实 SUT 的2轮次 / 77用例。旧表中的317行也属于隔离测试 fixtures，不能据此宣称生产数据比较或保全验收。本报告只按上述精确2个 NativeRun ID 评估，未清理任何 fixture 或旧数据。

## HTTP、CLI 与交接验证

- 客户端进程22808完成20次真实HTTP调用：2个 Project、2个固定计划 / Case Proposal 接受、2条执行材料提交、2次 UNKNOWN评估、状态与10份原件读取；每个原件byte count / hash一致。[原始HTTP记录](http-one.json)
- 独立客户端进程22870完成15次调用：2个 Operator 显式 handoff，generation 1→2，计划 / 用例 / 原执行 / 原件 / 验证 / 原结论 ID均保留。旧私有 writer token 即使用新 contributor / generation 也返回403；原key GET回执不返回 token / hash。[交接记录](http-two.json)
- 最终源码服务PID27312重启后，客户端27733完成27次调用：10份执行原件与2份冻结handoff快照读回，旧capability 403；缺attestation的旧 summary-only reconcile 422；带明确control-readback attestation的NOT_FOUND仍保留UNKNOWN，新执行提交 / handoff均409，没有第二条执行。[最终源码读回记录](http-readback.json)
- 产品原生CLI也在最终源码下实际执行 evaluate / get / operation：Blockchain仍UNKNOWN，XBlock状态及原handoff回执可读，不泄露私有writer key。[CLI评估](cli-evaluate.json)、[CLI状态](cli-xblock-state.json)、[CLI原key读取](cli-operation.json)
- `control-only-unknown` 是明确标注的本机治理测试，没有发出外部测试、CI、Issue或交易请求。其NOT_FOUND查证不足以解除未知，XBlock最新BLOCKED因此是治理阻断，不能称为产品缺陷或SUT失败；原17个断言观察仍保留PASS。

协议权限仍是 Operator管理入口，非管理写另需当前run/generation私有capability。contributor session label不是可信Provider native身份；本轮证明的是两个独立客户端的顺序贡献者接续，不是接管真实新聊天或跨Provider迁移。source refs / 完整性 / 报告结构校验不等于 Requirement/Risk语义覆盖或真实执行出处证明。

## 代码与兼容验证（独立于真实SUT执行）

实施代理最终原生接入 / 客户端 **22项通过（0.75s）**；相关组合回归 **82项通过（13.61s）**，其中是当时9项native加73项已有测试，存在重叠，**不能与22相加为104，也不能称82项全部legacy**。组合回归有1个Starlette/httpx弃用warning，无失败。修改文件Ruff与文档diff检查通过，独立评审剩余P1/P2为0。

准确命令、环境变量名称、exit、原工具chunk / session与输出摘录见[实现验证记录](IMPLEMENTATION_VERIFICATION.json)。原始pytest/Ruff输出仅保存在会话工具记录，事先没有tee本机日志；该文件明确是transcript-derived记录，不冒充原始运行日志或正式SUT Evidence，也不替代上文直接HTTP / 原件验收。

## 持久化、运行时身份与停止

临时运行目录已逐文件复制到 **`/Users/zhangliangchen/.local/share/hypertest/native-dev-20261021`**：16个原文件逐字节/hash相同，再只修改副本的 `HYPERTEST_ARTIFACT_ROOT`；所有目录0700 / 文件0600。11个客户端状态 / 私有journal文件另复制到该目录的 `acceptance-client/`，原tmp及仓库忽略目录均保留，没有覆盖其他持久资料。[复制与核验记录](persistence-migration.json)

随后精确停止原PID27312，用相同最终源码、相同PG及持久配置启动PID29428（**06:55 UTC**），实际核对该PID唯一监听127.0.0.1:8097。新进程下21次**纯GET**核验11份材料（10原件+1control）、2份handoff快照、2轮次generation / 归属 / 原key无secret及UNKNOWN保留；未创建新轮次或执行。[运行时身份与11文件清单](runtime-identity.json)、[持久配置读回](persistent-readback.json)

首次持久配置读回脚本把无Operator读取预期写成403，实际服务返回401。原件 / 快照已经读回，脚本在该错误期望处停止；服务正确要求认证，属于 **TEST_EXPECTATION_ERROR**，记录保留。仅修正预期为401后重做纯GET；没有重试写入或当作产品缺陷。[原始验收脚本错误](persistent-readback-initial-error.json)

本轮没有创建新Git提交、push或发行。代码身份是起点 `5a68dd1bd6375fad0b271b2b86af48bdf857fe31`、分支 `codex/native-framework-evidence` 加未提交开发改动；运行时清单记录11个实际源文件，并在进程启动及纯GET复核时匹配。hash只识别源码 / 文件内容，进程启动与HTTP响应是独立观察，不用hash代替SUT执行证明。

验收结束后已精确SIGTERM本轮API **PID29428**，8097不再监听；仅停止既有精确容器 **`hypertest-native-qa16-20261021`**，状态exited，未删除容器 / mounts / 数据 / Artifact / journal。没有全局Docker/Provider/进程清理。[停止记录](runtime-stopped.json)

生产服务、schema、数据卷、授权、VPN/SSH/TLS、两种受管Harness及其历史未操作；没有部署、源码/JAR上传、Issue或共享链写。完整接续命令和私有配置引用见[新Mac进展交接](../../handoffs/MAC_NATIVE_TEST_FRAMEWORK_PROGRESS_20261021.md)。

公开候选72个文件经本轮5个私有Operator / writer真实值的内存精确扫描，无命中；持久目录0700/0600核验通过，未输出或保存秘密值。[隐私核验](privacy-verification.json)

## 尚未完成

独立可信CI/SCM来源Verifier、正式native PASS、Web/MCP原生接入、完整语义覆盖、可信原生会话交接和真实产品失败执行材料仍待实现 / 验收；XBlock JAR→源码 / 当前部署关联未证。测试框架负例断言通过不是失败执行。按ADR-017 §8完成实际可信来源契约后才能讨论正式质量放行，不能把本轮UNKNOWN当作全部架构迁移完成。
