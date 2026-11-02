# Cloud Agent 运行中提问：SDK 调查（2026-11-02）

**状态：能力已核实，HyperTest 端到端问答尚未实现或部署。** 本文为调查记录与后续实现输入，不改变现行状态机。原进程退出后的会话恢复仍是独立问题。

## SDK 事实

- 当前 Worker 固定 `deepseek-harness-sdk==0.2.1rc2` 与同版本 runtime，对应上游源码 `687f282e8625c6b8d11ff58211a90524be2e4317`。其 Python 客户端的 `next_request` / `respond` 是通用 JSON-RPC，固定版本服务端没有用户提问桥接；不能据此认定可在线提问。
- 上游 [b9fb31c2](https://github.com/deepseek-ai/deepseek-harness/commit/b9fb31c2ddfca639dcf9c3deff6e7cf5731b4b23) 引入原生提问桥接。调查时 [SDK 文档](https://github.com/deepseek-ai/deepseek-harness/blob/ce7073d51254c26cd63b22a60835b8f948deb447/python/sdk/README.md#native-user-questions) 描述 `on_user_question`：回调接收原 request ID、session ID、结构化问题和取消事件，返回每个问题的选项或自定义回答，也支持取消。SDK 不提供用户界面。
- 调查时 PyPI 的 SDK 和 runtime 最新版仍为 0.2.1rc2；不能仅升级 Python SDK 或以通用队列冒充完整支持。实施需要同一固定上游版本的 SDK 与 runtime，并验证兼容现有 Harness profile。

## 本轮验证

从固定上游 `ce7073d51254c26cd63b22a60835b8f948deb447` 临时检出和构建，未修改实际 Harness profile、身份或 Worker 安装。上游 Python 问答回调测试 9 项通过，覆盖取消与迟到回复；另以隔离工作区、本地模拟模型和真实上游源码 runtime 执行计划审阅提问与回答，1 项通过。生成的候选可执行文件通过同一模拟测试。模拟结果不代表真实模型或 HyperTest 端到端验收。

官方完整二进制打包未成功：上游构建的部署步骤选择了 `tslib@2.9.1`，而该源码锁文件记录 `2.8.1`，因缺少受审 SHA-512 校验而停止。尝试在临时 workspace 固定旧版后，冻结锁文件检查拒绝了不匹配的覆盖。未绕过完整性检查，候选可执行文件未安装或部署。

## 后续接入范围

1. 取得并固定具备该能力且可复现的 SDK/runtime 配对，检查实际 profile、启动、模型选择与取消语义。不能将非正式候选二进制标记为已发行或兼容。
2. 增加独立的活问题和回答通道，绑定 Project、Task、Attempt、当前 Worker lease generation、SDK 原 request/session ID。Worker 持续续租；其 SDK 子进程不接收平台令牌。旧 `WAITING_INPUT` 会在隔离后保存答案，不能作为活会话回答。
3. 明确回答已保存、已交给 SDK、取消、过期、失联与交付不确定的状态。对同一问题只接受一次有效回答；失答或中途崩溃只能按原身份对账，不能把回答投给新的进程或 generation。用户回答不能扩大原任务授权。保留 SDK 的问题选项、自定义回答及取消能力。
4. 任务详情提供当前活问题的双语操作入口，展示问题、选项及实际交付状态。需要覆盖并发问题、重复提交、撤销、迟到回答、Worker 失联、权限与原 key 恢复，并分别记录自动回归和用户验收。

本轮现场观察到宿主 `com.hypertest.cloud-native-worker` 未运行，状态目录存在 `SENT` 的待对账 claim；这只是当时观察，后续应重新核实，不删除或重发未知请求。
