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

复用既有 Python 环境 `/tmp/hypertest-p0-backend-venv`、Web node_modules 与服务器 Node；数据库仅隔离为限额512MiB的临时 PostgreSQL 保存合成 fixtures，人工管理修复验证时按同规格重建，完成后均移除。与业务库分离，未复制全栈或模型环境。

| 检查 | 结果 |
| --- | --- |
| 后端相关自动回归 | 70 passed；含7条多场景协作测试和原任务/绑定/分页回归 |
| 最终协作契约回归 | 增加真实 ApiClient(ASGITransport)→LocalCollaborationAdapter→后端与Operator人工管理后，协作文件9 passed；覆盖JOIN/贡献/交接后发布、CASE/REPORT默认值、非ASCII原文跨页与真实摘要/回执/固定版本读回。与上行重叠不加总 |
| Local/MCP/技能相关自动回归 | 124 passed；最终微调后新协作39项再次通过，两次有重叠不加总 |
| 独立Local打包回归 | 61 passed；custom wheel真实隔离导入两份wire schema/协调器、中文REPORT规范化、源码摘要变化及缺件/链接拒绝 |
| Web 相关自动回归 | 56 passed；含独立账本、失答恢复、固定版本内容核验与组件流程 |
| Web 类型与静态检查 | typecheck、Ruff、技能验证、文档链接及 diff 检查按本轮范围执行 |
| 旧数据迁移合成回归 | 专用测试库0001→0028植入旧FAIL任务/SyncReceipt→0029；原UUID、version、source与旧JSON snapshot保持，来源注册正确、无补造participants |
| PC 合成组件检查 | 1440px英文、中文授权、中文交接三状态；修正新增Descriptions标签对比度后确认，无页面横向溢出。不作为真实宿主或用户验收 |

以上是实现自动回归，不是模型/SUT执行或用户验收。两条旧CI断言同步后，在无数据库连接的轮廓下定向2项通过；最终CI结果另列。

集成审查发现首片对旧 full sync 的拒绝一并阻止了已有 Operator UPDATE，原回归还包含错误的拒绝断言。已恢复 §50.4 人工标题/计划/进度编辑，新增回归验证 reported_result/成员/主代次保持、管理快照继承固定 roster、旧版本 PUBLISH 冲突及新版发布；最终9项覆盖修正，不把 Agent PRIMARY 约束扩大成人工管理权限变更。

独立Local custom wheel原本只手动纳入task_schemas.py；新协作schema需同时纳入wheel/必需文件/固定源码摘要。打包修正提交为`2cdd59a6ae3e552021abc2d5f0cab14961a3faaf`，freeze清单同步但不改旧BASE或历史发行；真实wheel导入及摘要回归已通过，没有另建venv或发布新tag。

[首轮代码CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40272764669)的Web与memory-api-profile成功，平台pytest为**2212 passed / 2 failed / 21 skipped**。两失败分别是旧迁移head仍固定0028、工具数仍固定13；已更新为0029/17，新增四工具存在性并保留caller context不由arguments提供的断言，不重标首轮失败。

## Git 与部署

本轮从 `codex/multi-session-task-adr` 提交并推送后，服务器复用干净 checkout fetch 并固定完整 SHA `66f69f17a249ee382d60096ef9871695be457ee5`，按既有 Compose/TLS/访问守卫停止受影响的 API/Web、在服务器构建、执行0029增量迁移并启动，重启容器nginx刷新上游。应用源码已部署；其后独立Local打包、测试断言与交付文档提交不改变这两个应用镜像的运行代码，不为此重复构建。

| 项目 | 实际身份 / 结果 |
| --- | --- |
| API | `sha256:6077cd442245aabbe19c86fa76515ed54801152175bd3ffd42729d7edf023ea2`，源码为上述66f69f1完整SHA；最小镜像无MCP/Agent SDK仍可导入新路由 |
| Web | `sha256:9d860c213fda79acfa1edfd5c715bef0c3d7d0fa198d799f25f376bd52d0b2eb`，相同Git来源；正式构建、类型检查和页面生成成功 |
| 迁移 | 0028→`0029_local_task_collaboration`；迁移前备份1,944,990 bytes；原15个Task数量保持，15个BOUND来源登记，新增成员/贡献/发布/协作回执均0，不创建线上fixture |
| 健康与技术关键路径 | 五容器healthy；API health、Web根页、既有Task协作GET及其Web转发均HTTP200；旧Task仍collaboration=false |
| 访问 | 原Compose/TLS/VPN/SSH、入口守卫和凭据保持；没有给Project启用协作或新增会话授权 |
| 清理与容量 | 本轮512MiB合成测试库容器已移除；未删旧数据、卷、镜像、发行或未决账本；构建后根盘剩余约5.2GiB |

部署回执目录为 `/var/lib/hypertest-cloud/delivery/20261026-local-collaboration-66f69f17`，含实际deployment.json、build/migration日志、迁移前备份及执行脚本。PR为[#26](https://github.com/ZhangLiangchen/hypertest-one/pull/26)，部署不以PR合并为前提。

Cloud 独立 Worker、legacy Worker、模型配置、权限、凭据及数据卷不因 Local 协作改为新运行身份。用户功能验收保持 USER_OWNED。

## 使用与限制

1. 先按既有 ADR-024 绑定首个真实 root；在任务详情“会话协作”显式启用。
2. Operator 用任务同一 owner actor 授权另一个真实 provider/session，并填写分工；新源码客户端通过 `hypertest_join_task` 加入，不能冒用原父会话 ID。
3. 参与会话通过贡献工具或已批准 Hooks 保存自己的产物；当前主会话显式汇总整体状态。需要接力时，Operator 选择已 ACTIVE 成员交接，不修改初始绑定。
4. 失答保留原 key，用协作 GET 的原 key 选择器恢复；NOT_FOUND 不允许重新 POST。授权待加入可只读选基线，ACTIVE 才可提交贡献。

公开 `local-v0.1.0` / `local-v0.1.1-rc.1` 资产、摘要及原宿主证明均未重标；新功能需要本次源码客户端，源码接入不代表新公开包已发行或真实宿主E2E已验收。逐调用 caller 仍限已实现的 Codex CLI `0.144.6` 路径，Claude/DeepSeek新协作写仍 unsupported。

首片只保存明确交接材料与服务端已知操作，不自动枚举失联 root 私有 UNKNOWN，不从自由文本建立依赖阻塞引擎，不据声明证明外部动作已停止。各客户端继续阻止越过自己的未决请求；标准 A2A adapter、跨 actor ACL 与新客户端公开发行分别交付。
