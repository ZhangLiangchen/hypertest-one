# Local 一任务多会话协作交付（2026-10-26）

本轮按用户指令实施 [ADR-026](architecture/ADR-026_MULTI_SESSION_TASK_COLLABORATION.md)，首片覆盖 Local 任务从显式启用、精确授权、真实 root JOIN，到各自贡献、主会话汇总与交接的管理链路。未启用的旧任务继续单会话；没有运行模型、业务 SUT 或用户功能验收。

## 实现

- 新协作 profile `local-task-collaboration/v1alpha1`，独立 Operator/成员 typed API；完整 schema、角色及固定版本读取见 TMP §45.5 / 领域 §50.6。
- `0029_local_task_collaboration` 为 SessionTask 增加协作开关和主会话角色代次；增加全局来源注册表、成员、贡献修订、发布记录和独立协作回执。原来源、UUID、owner、旧 snapshot/回执不改写；仅回填已有来源注册，不补造过去 JOIN。
- 各独立 root 使用自己的真实来源和批准产物策略；CONTRIBUTE 按成员命名空间追加，PUBLISH 只允许当前 PRIMARY/generation。发布保存准确贡献引用与处置映射，不物化为旧 CaseRevision/ReportRevision，也不删除旧 FAIL。
- 撤销主会话或 HANDOFF 递增代次，旧主会话迟到整体提交受拒绝。原 key 查重在版本前，原提交来源核对、SENT/UNKNOWN/NOT_FOUND 只查询、不换会话重发。
- Local 源码新增 `hypertest_join_task`、`hypertest_contribute_task`、`hypertest_publish_task`、`hypertest_get_task_collaboration`；独立私有账本、原 key 查询及完整固定版本原文读回复用 TaskSyncCore。Hooks 只提交获准成员贡献，不自动发布整体状态。
- PC Web 展示初始绑定、当前主会话/代次、授权待加入与 ACTIVE 成员、分工、贡献来源、原报告结果及交接历史；Operator 操作使用独立 IndexedDB 冻结请求并在固定版本读回后结算，版本冲突保留输入。
- 四份基础规范、相关 ADR、AGENTS 与源技能/指南同步。API Docker 构建上下文补入已由 pyproject 强制打包的唯一 Skill 源文件，避免新增源码安装时缺件。

## 相关验证

复用既有 Python 环境 `/tmp/hypertest-p0-backend-venv`、Web node_modules 与服务器 Node；只新建一个限额512MiB的临时测试 PostgreSQL 容器保存合成 fixtures，与业务库分离。未复制全栈或模型环境。

| 检查 | 结果 |
| --- | --- |
| 后端相关自动回归 | 70 passed；含7条多场景协作测试和原任务/绑定/分页回归 |
| 最终协作契约回归 | 新增真实 ApiClient(ASGITransport)→LocalCollaborationAdapter→后端的第8条后，协作文件8 passed；覆盖JOIN/贡献/交接后发布、CASE/REPORT默认值、非ASCII原文跨页与真实摘要/回执/固定版本读回。与上行重叠不加总 |
| Local/MCP/技能相关自动回归 | 124 passed；最终微调后新协作39项再次通过，两次有重叠不加总 |
| Web 相关自动回归 | 56 passed；含独立账本、失答恢复、固定版本内容核验与组件流程 |
| Web 类型与静态检查 | typecheck、Ruff、技能验证、文档链接及 diff 检查按本轮范围执行 |
| 旧数据迁移合成回归 | 专用测试库0001→0028植入旧FAIL任务/SyncReceipt→0029；原UUID、version、source与旧JSON snapshot保持，来源注册正确、无补造participants |
| PC 合成组件检查 | 1440px英文、中文授权、中文交接三状态；修正新增Descriptions标签对比度后确认，无页面横向溢出。不作为真实宿主或用户验收 |

以上是实现自动回归，不是模型/SUT执行或用户验收。CI 及部署构建结果在完成后补记，不预先宣称通过。

## Git 与部署

本轮从 `codex/multi-session-task-adr` 提交并推送后，服务器复用干净 checkout fetch 指定完整 SHA，按既有 Compose/TLS/访问守卫更新受影响的 API/Web，并执行0029迁移与基本健康、协作只读路径检查。部署的源码、镜像与结果在实际完成后补入本节；此处不将源码实现写成已部署。

Cloud 独立 Worker、legacy Worker、模型配置、权限、凭据及数据卷不因 Local 协作改为新运行身份。用户功能验收保持 USER_OWNED。

## 使用与限制

1. 先按既有 ADR-024 绑定首个真实 root；在任务详情“会话协作”显式启用。
2. Operator 用任务同一 owner actor 授权另一个真实 provider/session，并填写分工；新源码客户端通过 `hypertest_join_task` 加入，不能冒用原父会话 ID。
3. 参与会话通过贡献工具或已批准 Hooks 保存自己的产物；当前主会话显式汇总整体状态。需要接力时，Operator 选择已 ACTIVE 成员交接，不修改初始绑定。
4. 失答保留原 key，用协作 GET 的原 key 选择器恢复；NOT_FOUND 不允许重新 POST。授权待加入可只读选基线，ACTIVE 才可提交贡献。

公开 `local-v0.1.0` / `local-v0.1.1-rc.1` 资产、摘要及原宿主证明均未重标；新功能需要本次源码客户端，源码接入不代表新公开包已发行或真实宿主E2E已验收。逐调用 caller 仍限已实现的 Codex CLI `0.144.6` 路径，Claude/DeepSeek新协作写仍 unsupported。

首片只保存明确交接材料与服务端已知操作，不自动枚举失联 root 私有 UNKNOWN，不从自由文本建立依赖阻塞引擎，不据声明证明外部动作已停止。各客户端继续阻止越过自己的未决请求；标准 A2A adapter、跨 actor ACL 与新客户端公开发行分别交付。
