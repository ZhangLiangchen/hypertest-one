# Cloud Harness 外壳职责纠正（2026-11-04）

按 [ADR-041](architecture/ADR-041_CLOUD_AS_HARNESS_SHELL.md)，当前宿主 Cloud 沿用 Harness 的原生测试流程。任务页只保留 Agent 对话、报告/附件和折叠的会话/来源信息；删除阶段导航、平台恢复选择、人工接管、停止对账、旧结构化回答和重试审批表单。

普通消息在线与离线使用同一发送接口。离线且未终结时，服务端在保存消息的同一事务安排原会话连接，Worker 仅恢复原 SDK 会话，在 ready 后投递已保存文字，不发送默认 continuation 或原任务 prompt。SDK 接收入队只显示已交给会话，不声称 Agent 已处理。Harness 决定工具权限、审批、团队、步骤和原生队列；平台保留项目权限、消息归属、原 key 查询及单次投递。

Native 完成归档不要求平台分析/设计/实现阶段或结构化 Run 齐全。报告归属和结果一致性仍检查，结果显示为 Agent 报告结果；不会从聊天、idle 或归档成功推导测试通过，也不升级为独立 Evidence。既有未确认消息只查询原身份；断连保留尚未投递的消息，显式取消才取消它们。

本轮无新 schema 迁移，不删除业务数据。保留已部署的测试框架项目会话、Memory 及其他服务。旧 RESUME_ATTEMPT 接口新写返回410，原已接受回执仍可读；不再建设人工声明续接入口。

## 验证与部署

相关验证：消息/连接/claim 恢复及原生问题链路40项、原生归档/Worker API联调15项、既有handoff合同32项通过；Web相关64项与approval补充3项通过，类型检查及一次1440px合成界面检查通过。原key跨generation补充及Worker/检查合同57项通过，Ruff及差异检查通过。API、Web、宿主四槽 Worker 统一从推送提交更新，schema 保持0048。真实消息发送、原会话工具执行及业务测试结果仍为 USER_OWNED，未由本轮自动触发。


已推送并部署 `4dbeb61354223381bbeefdc17257eb5b35719df3`（`codex/cloud-harness-shell-20261104`），基于已部署的99c8707保留同期框架工作目录及诊断修复：

- API `hypertest-mac-api:4dbeb61` / `sha256:85e4e4b24d37aa626e49928b3b41794e58da886d281ed00d07b62f83c56eb40e`。
- Web `hypertest-mac-web:4dbeb61` / `sha256:04b35e25582c6aba062231c4d38af3851dd96cd0d13bf2fd04af20fcfc2cdb66`。
- 宿主 Worker PID `37142`，默认4槽；新源码定向安装并移除退休的adoption helper。schema `0048_concurrent_claim_slots`，无迁移。
- API健康、任务页HTTP 200；Worker running，四槽EMPTY/closed。BFF、数据库容器身份及启动时间保持，WireGuard/TLS、Memory18543及退休18443状态保持。
- 通过实际Web BFF只读查询指定任务：v13 / RECOVERY_REQUIRED / NOT_RUN，6条Agent公开历史消息+1条中断说明保留；会话OFFLINE、can_send=true、can_reconnect=true、CONNECT_ON_SEND。没有提交业务消息、人工接管或继续执行；实际SDK恢复和后续业务结果由用户发送消息验收。

部署证据在宿主 `~/.local/share/hypertest-mac/cloud-harness-shell-20261104/`。首次准备时观察到短暂SDK进程，未停止服务；其退出且所有原领取已关闭后部署成功。健康脚本最初直连HTTP被现有HTTPS规则拒绝，改用既有Web BFF完成只读检查，未修改访问边界。
