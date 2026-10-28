# 文档导航

文档中的设计合同、源码实现、某次部署和用户验收是不同状态。日期、提交号、镜像和检查结果只说明相应记录的时点；查询当前运行状态时应实际核实，不能取历史记录中最后出现的“当前”作为依据。

## 现行入口

- [当前待办](TODO.md)：未完成的开发、操作和用户验收。
- [产品白皮书](foundation/HYPERTEST_WHITEPAPER.md)、[技术架构](architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)、[测试任务协议](protocol/TEST_MISSION_PROTOCOL.md)、[领域模型与状态机](domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)：按 [AGENTS.md](../AGENTS.md) 的优先级及后续 ADR 增补阅读。
- [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 与 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)：新 Local 显式归档及安装授权；旧 SessionTask 仍有独立的历史合同与恢复边界。
- [服务器操作](SERVER_OPERATIONS.md)：现行测试服务器操作规则和 SSH 指引；运行身份以现场检查为准。
- [PowerContext 服务](POWERCONTEXT_SERVICE.md)及 [Cloud 实现状态](CLOUD_IMPLEMENTATION_STATUS.md)：各自能力与范围，部署和验收以具体轮次记录为准。

## 历史与兼容资料

[交付跟进](FOLLOWUP_DELIVERY_20261023.md)、各 `*DELIVERY*`、`*ACCEPTANCE*`、`*PRODUCTION*`、旧方案和发行文档保留当时的事实与证据，不是现行部署或新接入教程。[服务器历史快照](SERVER_OPERATIONS_HISTORY.md)保留从现行指南移出的操作记录。旧 ADR 仍可能规范对应的 legacy 数据、合同与恢复，不能因为新入口替代旧入口就删除历史约束。原始验收材料、回执和机器可读证据保留原路径。

新增或修改文档时，把长期规则放在其权威文档，未完成工作放在 TODO，按轮次记录实际结果并说明时间和范围；避免在多个入口复制易过期的部署状态。
