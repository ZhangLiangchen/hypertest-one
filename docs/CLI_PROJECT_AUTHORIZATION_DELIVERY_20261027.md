# CLI 项目授权入口简化（2026-10-27）

授权页原先列出所有 ACTIVE integration actor，包含旧任务管理和 Local 验收身份，用户无法据此判断本机 CLI 应选择谁。本轮移除这项选择：核对短码和客户端后，只选择项目与有效期，确认 archive:read/write 即可批准。

## 实现与历史边界

- API 首次合法 APPROVE 为稳定 `connector_operator_identity` 建立专用 CLI 上传 actor；`CliArchiveUploader` 不可变映射使同一 Operator 的不同设备复用任务归属，各客户端仍独立批准项目授权。撤销不自动重建或改绑。
- `0032_cli_archive_uploader` 只新增映射表及不可变约束，不回填或删除历史身份，不在部署时创建实际用户身份/授权。
- 新 APPROVE 无 actor 参数；原参数仅用于已接受旧 APPROVE 的原 key/原正文回执恢复。旧 APPROVED/BOUND 按原身份继续兑换和查询。未决旧请求不得改正文、换 key 重发。
- 旧 `/cli-authorizations/actors` 在 Operator 认证后返回410，Web BFF 停止代理该列表；授权页不再查询或显示历史身份下拉框，授权记录按客户端显示。
- 已有 Task owner、grant、报告、审计记录和回执保持。任务管理按项目有效归档 grant 选择 owner 的独立规则保持，新配对不会自动接管旧任务。
- 中英文安装 Prompt、README、CLI 指南、ADR-027 及领域/协议/架构已同步。CLI cli-v0.1.0 二进制、原发行 tag 与四资产身份保持。

## 定向验证

- 复用已有 Python 环境；只为本轮创建临时 PostgreSQL 测试库容器，合成数据与业务库隔离。从空库迁移到0032成功。
- `tests/test_cli_authorization.py` 与 `tests/test_local_archive.py`：21 passed。覆盖并发首次批准、跨设备稳定身份、跨 Operator 隔离、项目权限和撤销拒绝、新批准拒绝旧身份、旧批准回执/待兑换兼容及不可变映射。
- Web `archive-ui`、`archive-operation`、`archive-boundary`：11通过；回执补强后受影响4项再次通过，不另累计。Prompt 4项通过；首次旧文案断言失配已按“用户核短码并批准项目”新文案修正，未削弱人工批准要求。
- Web类型检查、后端目标Ruff、Prompt文本一致性与差异检查通过。设计静态扫描无 findings；未作浏览器用户验收。

## 部署与发行状态

待从推送的固定 Git 构建 API/Web、备份业务库并向前迁移0032、检查健康和身份列表退休路径。Prompt发行说明更新及精确Git/image随后记录。

USER_OWNED：尚未执行真实用户批准、CLI兑换或产物上传；本轮不代用户签发授权。
