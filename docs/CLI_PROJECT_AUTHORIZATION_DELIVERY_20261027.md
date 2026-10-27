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

## GitHub 安装 Prompt 更新

已更新 [cli-v0.1.0 Release](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0) 的推荐安装说明和完整中文 Prompt：用户核对短码、客户端、项目、权限与期限，平台自动关联专用 CLI 上传身份。指南与 Prompt 源码链接固定为 Git `006100788751a416b0d6f1dbe8d78c96d3155a5f`；原 CLI 0.1.0 功能说明原文保留。

新增以下附件，内容与该 Git 中生成的中英文 Prompt 逐字节一致：

| 附件 | Asset ID | 大小 | SHA256 |
| --- | --- | --- | --- |
| [hypertest-cli-install-prompt.20261027-2.zh-CN.txt](https://github.com/ZhangLiangchen/hypertest-one/releases/download/cli-v0.1.0/hypertest-cli-install-prompt.20261027-2.zh-CN.txt) | 680675479 | 4076 bytes | `50d418d6b60d1afcbd033e2aa385ab158abfdfed4f4fc482ce715a580b66ba50` |
| [hypertest-cli-install-prompt.20261027-2.en.txt](https://github.com/ZhangLiangchen/hypertest-one/releases/download/cli-v0.1.0/hypertest-cli-install-prompt.20261027-2.en.txt) | 680675477 | 4626 bytes | `9981d2e348714d81d27e92fdb4d55ccf69214de014372aaaa242c4d944804fa2` |

两文件均经无授权 HTTPS 公开下载，字节、大小和 SHA256 与源码及 GitHub 资产摘要一致。原四个 CLI/安装器/manifest/SHA256SUMS 和上轮两个 Prompt 附件的 ID、大小、摘要及更新时间均保持，未覆盖历史附件。Release 推荐链接已指向本轮带日期附件，并说明旧 Prompt 仅供历史追溯。更新前后 metadata、精确正文及核验记录保存于 `/opt/hypertest/cli-releases/0.1.0/project-authorization-20261027/`。本次仅更新安装说明，不重新发行 CLI 二进制，也不代表本机安装或授权验收完成。

## 部署与发行状态

API/Web 已从干净复用 checkout 的推送 Git `006100788751a416b0d6f1dbe8d78c96d3155a5f` 构建并部署，数据库向前升级至 `0032_cli_archive_uploader`。

| 组件 | 本轮身份 |
| --- | --- |
| API | `sha256:2fd7d36542f90f4961b87a958e2576cb509db29d48378516df83e39d17045002` |
| Web | `sha256:53ea16f9292fbee2c14d6b2136eedcf503354950083c5b8ec16657fd4484881e` |
| 固定 ops | 继续使用 `1512d11f99c5e500e4fc56c685410ffa9e533530`，无新部署配置需求 |

部署前逻辑 DB 备份位于 `/opt/hypertest/backups/cli-identity-20261027-0061007/database.dump`。迁移只追加映射表及约束，无业务fixture写入、旧身份回填或记录删除。

五容器 healthy、网络守卫 protected；API health与授权页均HTTP200、CLI setup configured、授权grants只读路径HTTP200；使用现有受保护Operator凭据核验旧actor列表HTTP410 / CLI_UPLOADER_SELECTION_RETIRED。未执行真实用户批准。

legacy Worker、PostgreSQL和nginx镜像保持；独立Cloud Worker active，启动时间仍为2026-10-23 16:29:49 UTC。TLS/CA、SSH/VPN限制和数据卷保持。运行记录及构建日志位于 `/opt/hypertest/container-builds/cli-identity-0061007/`。本轮临时测试库容器及tmpfs已删除，复用依赖/构建缓存保留，根盘可用约13GiB。

当前 cli-v0.1.0 可继续使用，无需重装。用户刷新授权页后核对原请求状态；旧已批准/绑定请求按原回执恢复，已过期请求不自动延长，不自动换key配对。

USER_OWNED：尚未执行真实用户批准、CLI兑换或产物上传；本轮不代用户签发授权。
