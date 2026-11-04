# Cloud 任务内对话与多会话交付

日期：2026-11-04。合同见 [ADR-039](architecture/ADR-039_CLOUD_CONVERSATION_BRIDGE.md)。

## 实现

任务详情主区显示 Agent 对话、用户文字、现有结构化问题及运行事件；报告和附件留在产物区。公开根消息经过内容校验后持久化，采用独立游标与 1 秒页面轮询，正常连接下目标 2 秒可见。单条拒收显示固定提示，不截断其他输出。产物内容在冻结请求前明确被拒收时，Agent 可以用新 key 修正；已发送或 UNKNOWN 请求仍只能恢复原 key。

用户消息区分已保存、交给会话与投递未确认；SDK messageId 只证明入队。Worker 共用一个 supervisor，默认 4 个独立槽；会话 idle 等待用户不调用模型。数据库租约监视器可在 Worker 异常退出后撤销原执行权并显示中断事件，不推断外部进程已停止。

原会话续接保持同 Attempt、新 generation、原 Worker/工作区/session，仅发送本次 continuation。旧 inbox、用户投递 UNKNOWN、原报告或外部操作未决均阻止继续。缺历史锚点时可显式 OPERATOR_ADOPTED；本次接管来源不冒充过去的原身份证明。

迁移 0047 增加对话表；0048 将领取高水位改为 (worker_id, slot_id)，旧行进入 legacy 槽，原 key/digest/恢复语义保持。旧单槽协议仅允许原领取恢复，不再执行新领取。无任务历史删除。

## 回归与部署

实现回归覆盖公开文字/秘密拒收、独立游标、重复事件、原 key 失答、投递未知、旧 generation、取消、正式完成、产物拒收后修正、多槽领取、单槽异常、同会话续接及人工接管。只使用专用测试库和合成 SDK；页面验证使用拦截数据的 PC 宽屏测试。

已部署推送分支 `codex/cloud-conversation-20261104`。主体源码 `27bbce9d034dcbff9bce2724bab9e2f2ecebc97d` 基于并行 Memory 版本 `d71aff5f99a4fa30b95c2369a22c7b52a7887ff2`，保留其现行协议与知识入口；没有改动共享 checkout 的分支或其他会话未提交文件。

- API：`c69af66b9b14154c7aee7977e9c0c9f7aa2cb3df`，镜像 `hypertest-mac-api:c69af66` / `sha256:bd01caa379c8bff9360692455180c86894e6c20ebaab2c54f1b69f5fe1cf3455`。末次修正只区分离线与正在连接，未再次迁移或重启 Worker/Web。
- Web：`27bbce9d034dcbff9bce2724bab9e2f2ecebc97d`，镜像 `hypertest-mac-web:27bbce9` / `sha256:a39d300df25b70670c83a22864452662d752c1e7a230c48f29de09efd9396b3e`。
- 数据库：`0048_concurrent_claim_slots`。宿主 Worker 主体同 `27bbce9d034dcbff9bce2724bab9e2f2ecebc97d`，PID `24985`；四个槽均观察到 `EMPTY / closed=true`，legacy 原高水位保留。所更新文件与推送源码逐一核对。
- 相关后端合成回归通过；最终 Worker 相关 50 项、Web 相关 76 项通过，TypeScript、Ruff、差异检查及部署构建通过。API/Web healthy，任务页与对话增量读回成功；BFF/数据库容器未替换，WireGuard/TLS/凭据及现行 18543 PowerContext 保持，未启动退休的 18443。

指定旧根会话 `cloud-01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba` 的 6 条现存公开文字（seq 18 至 1133）通过内容检查补录，另加一条固定中断/缺失说明，共 7 条。来源为 `IMPORTED_HISTORY`、原 generation 1，分别保存原时间与补录时间；未读取子会话正文、推理或原始工具负载作为消息。补录前后任务均 `v12 / RECOVERY_REQUIRED / NOT_RUN`，无模型调用、原业务输入重发或正式结果变更。HTTP 增量读回为空页游标已核对；原会话离线时 `can_send=false`，不会把回复显示为已送达。

本机非敏感交付证据位于 `~/.local/share/hypertest-mac/cloud-conversation-20261104/` 的 `deployment.json`、`worker-health.json`、`history-import.json`、`readback.json`、`status-fix-deployment.json`；最新完整 Compose 链保存在 `CURRENT_DEPLOYMENT.json`。PC 合成页面截图在 `output/playwright/cloud-conversation-20261104/`。以上是回归、只读补录与健康检查，不代表 USER_OWNED 业务验收。

## 用户验收

指定任务 `01a1a0e9-8db8-7be9-8a7c-43c42518a6b6` 的普通回复、人工接管和继续执行由用户操作。本轮不启动该任务的模型、SUT 或链上交易，不改其正式结果。建议核对：旧公开消息可见；按实际停止/对账情况选择续接；一个会话等待回复时另一个授权任务可正常运行。重试表单改造暂缓。
