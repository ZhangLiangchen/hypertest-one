# 原生材料平台接入验收计划

日期：2026-10-21，Asia/Singapore。此验收计划在新 native API 材料接入前编写；原生框架已于 06:23–06:25 UTC 真实执行，平台验收不会重跑这些测试。

## 范围与事实边界

- 固定 profile `native-framework-intake/v1alpha1`，按 ADR-017 / 架构 §43 / TMP §44 / 领域 §49 验收。
- 两个真实 SUT 的 retrospective intake：XBlock 17 既有 consumer-parity 场景、Blockchain 60 既有 JUnit 用例。原件位于相邻 `native-framework-20261021` 目录；保留原始 stdout/stderr / JSONL / 4 份 Surefire XML / process metadata。
- 平台 created/submitted/accepted 时间采用实际入账时间，observed started/finished 使用原 process 时间，不能冒称平台事前下发执行。
- 独立本机 PostgreSQL `hypertest_native_qa`、容器 `hypertest-native-qa16-20261021`、回环端口 55439；不得碰生产、旧数据卷、受管 Harness、权限、VPN 或原生测试进程。
- 仅输入 / 传输已检查的 manifest 和报告，不上传源码、JAR、Git / Provider 认证或秘密值。管理 / writer key 只保存在忽略的私有运行目录，绝不进入验收 JSON / 命令 argv / 日志。

## 验收断言

1. 通过本机真实 HTTP / PostgreSQL 路径创建 2 个 Project 下的独立 native 轮次，计划 / 用例经 Verifier 接受并读回，固定输入和 Project 归属可追溯。
2. 上传原生结果与原件，执行 / case / material / verification 关联一致；读取有界原始内容并核验完整 hash / 长度，摘要不替代原件。
3. XBlock 二进制 SHA 与未知源码关联独立保留；Blockchain source SHA 与 framework / 测试资产分开固定，环境和原生入口可查。
4. 两条本机断言虽全部通过，来源仍 UNVERIFIED，平台只能 UNKNOWN / BLOCKED，不能 native PASS / RELEASE_READY 或旧 VERIFIED Evidence。
5. 两个独立客户端进程显式顺序 handoff；原已接受计划、用例、执行、材料、结论与贡献归属保持。旧 writer token 即使换新 generation / label 仍被拒。
6. 原 key 查询只返回已提交回执，不重新执行、不重签 token、不泄露 key/hash；同 key 异输入冲突、响应丢失与私有 journal 原身份保留。
7. 外部 operation UNKNOWN 阻断新执行与 handoff；NOT_FOUND / 无原件 / 摘要不能消除未知。仅 Operator 窄管理对账可在 key 遗失时记录原操作查证材料 / reason，不触发外部执行；对账后才允许新的显式 handoff。
8. 所有材料、失败 / 拒绝 / UNKNOWN、Audit / Outbox 和原始时间保留；旧 Runner / Binding / Evidence / FINAL 未被读成新材料或改写。

未执行的断言保持待验，不以单元测试或文档存在替代实际 API / 数据库结果。平台报告解析失败与原生测试失败须分别记录；本轮不人为修改真实 SUT 或伪造失败报告来声称产品缺陷。
