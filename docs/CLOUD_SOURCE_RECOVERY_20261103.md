# 指定 Cloud 任务源码准备恢复（2026-11-03）

用户授权修复任务 `01a1a0e9-8db8-7be9-8a7c-43c42518a6b6` 的源码准备恢复状态，并通过新流程开始测试；随后明确本次框架使用实际默认分支 `master`。

## 诊断与修复

- 原解析 `01a1a0ea-cee4-7b4d-8e49-421045cfde52` 为 `RECOVERY_REQUIRED`。原 key 为 `web:149ac002-bc11-48ff-a87b-fb9b1eb8b0f0`；租约已清空、授权已撤销，原 claim 已关闭，无接受源码结果、无 Attempt。此前同一时段 Worker 日志记录 Git fetch 连接重置。
- 使用与宿主 Worker 相同的代码与环境检查，SUT MR head 可解析至 `bbd065cdc502fe9f249e3d9e46b4b9caaadf3e88`；框架 `main` 返回引用不存在。glab 确认 `zhangliangchen/hypervise_pure` 的默认分支为 `master`，`main` 查询 404。诊断时 master 为 `5122a6bf29e739d78d2938981fee17ed744bf9ad`；这只是诊断观察，最终执行版本以新解析接受结果为准。
- 新增 `CLOSE_INPUT_RESOLUTION`，仅允许关闭原 claim 已明确 fence、无活动租约或授权、未接受源码、无 Attempt 的 DRAFT 解析。需原解析 ID/key、操作者停止观察及原因；原回执和来源保持，关闭为 FAILED，不伪造源码接受或 Git 未执行事实。
- 相关恢复及 START_TASK 回归 21 项通过，Ruff 通过；复用已有依赖和 PostgreSQL，专用测试库已删除。无迁移。

## 部署

API 来自推送提交 `52584f7aa4763532156edad174fc6657242a2442`：`hypertest-mac-api:52584f7`，镜像 `sha256:edb8531e596eda6d946f3be7681c5949df4882808e8c78e3ff7cbd6e28244c99`。

仅更新 API，schema 仍为 `0045_local_archive_status`。Web 保持 `c356291`，BFF/数据库容器和 Worker PID 7620 保持。API healthy、健康接口及指定页面 HTTP 200。完整 Compose 链追加 `cloud-resolution-recovery-20261103/compose.json`，CURRENT_DEPLOYMENT 已更新。

## 原任务操作

1. 核对无活动 Git 进程、无原结果文件，按原解析身份关闭失败准备，任务 v2 → v3；旧解析保留并标为 FAILED。
2. 按用户确认，将此草稿框架选择器改为 `BRANCH master`，任务 v3 → v4。任务名称、MR 和测试说明保持；不改变全局 main 默认值。
3. 提交一次 `START_TASK`，任务 v4 → v5，新解析为 `01a1a119-9798-73a3-9764-577d37a5e12b`，`start_requested=true`。原 key 为 `repair:5e70a68a-9c49-4d1b-bba7-1cbd1f14746e`。三步均固定读回接受版本，未重放原请求。

11:10 UTC 新解析 PENDING，等待唯一 Worker 完成另一条任务；11:13:51 UTC 已领取。11:14:20 UTC 观察解析 ACCEPTED，系统自动建立 Attempt `01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba`，任务 v6 / PREPARING；11:15:06 UTC 进入 v7 / RUNNING。接受的 SUT SHA 为 `bbd065cdc502fe9f249e3d9e46b4b9caaadf3e88`，框架 master SHA 为 `5122a6bf29e739d78d2938981fee17ed744bf9ad`。

后续只读核对确认实际 `native_sdk_driver` 进程及官方 Harness runtime 子进程已运行，工作区已检出 SUT 和 framework。此时 Worker PID 为 14711，driver 为 14858、Harness runtime 为 14862；不将部署时的 PID 7620 描述为全程未变。任务仍 RUNNING / NOT_RUN，尚无回传的测试分析、用例或报告；启动成功不代表业务用例执行完成或测试通过。

测试框架仓库已经以 framework 角色进入任务快照，Agent 指令明确使用工作区 framework；README 也提供快速开始、业务域与 E2E 入口。配置可发现不等于本次 Agent 已正确使用，仍需实际分析/执行产物确认。

本机证据：`~/.local/share/hypertest-mac/cloud-resolution-recovery-20261103/` 中的部署记录、停止观察、三个原请求/接受回执/固定读回及 latest-status。原请求文件权限 0600，未进入仓库；未复制任何凭据。
