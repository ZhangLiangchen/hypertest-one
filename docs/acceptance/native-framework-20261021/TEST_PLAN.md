# 本轮测试分析与设计（执行前冻结）

日期：2026-10-21，Asia/Singapore。本轮仅使用既有真实 SUT / 项目测试资产；没有部署、链交易、共享配置变更、问题单或私有源码外发。

- 目的：验证 HyperTest 原生执行接入所需事实形态，并观察真实产品组件的协议行为。
- 主路径：已有 `consumer-parity/run.sh` 加载真实 xBlock asset JAR 的 `TronSaveEnergyRentalProvider`，调用既有 loopback Node 假供应商/内存链。JAR 来源仅历史说明，二进制身份可核对；不推导当前部署/链上行为。
- 正向：正常购能、延期查询、精度扣款、已激活地址。
- 负向：400/401/429、丢失订单ID、断连、数量边界、重复未完成订单、余额不足、拆单delegate、错误回显、非法地址、TRON_TEST链门控；均核对既有消费者分类断言。
- 预期：业务负例被正确拒绝或归为 UNKNOWN 计为测试断言通过；不是失败执行，也不表示产品所有业务均正确。
- 不制造新失败；若测试自身发现失败完整保留。共享环境不作故障注入。
- 第二路径候选：真实 Blockchain Git clone 的 standalone `blockchain-rpc-spring-boot-starter` Maven/JUnit 广播四态及 single-send 合约；先核验依赖，离线可行才运行。
- 原始输出：每次分开 stdout、stderr、process metadata（argv、cwd、开始/结束UTC、exit、工具版本与环境变量名）。保留原始 JSONL / Surefire XML，不把聚合摘要或hash当可信执行证明。
- 当前准入：本地探索/待验证材料，尚无独立平台 Verifier 签收，不是正式 Evidence。

全部缓存、临时服务状态和编译输出在本目录忽略的 `private-runtime/`。既有 SUT 和 hypervise_pure 不改动。
