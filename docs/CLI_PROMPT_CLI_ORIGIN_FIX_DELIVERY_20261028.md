# CLI 安装 Prompt 服务器地址修复（2026-10-28）

本机 WireGuard Web 只经普通 HTTP 提供（`http://10.66.66.3:3000`），而 HyperTest CLI 只接受 HTTPS 服务器地址。授权页此前用 `window.location.origin` 推断 CLI 服务器地址，于是把 HTTP 站点地址交给严格的 HTTPS 校验并抛错，`/cli-authorizations` 与项目页 CLI 安装指引都显示「无法生成安装 Prompt」。

本轮让页面在无法从站点推断时仍生成有效 Prompt，并为本机部署显式配置 CLI 的 HTTPS 入口（`https://localhost:18444`）。这是 Web 展示层与部署配置修复，不改变 CLI 授权、归档、原 key 恢复、Operator 边界或用户身份合同。

## 修复内容

| 范围 | 变更 |
| --- | --- |
| 部署配置 | 新增可选 Web 配置 `HYPERTEST_CLI_SERVER_ORIGIN`：CLI 实际连接的规范 HTTPS origin。它不同于浏览器站点 `HYPERTEST_ARCHIVE_WEB_ORIGIN`。 |
| BFF setup | `GET /api/cli-authorizations/setup` 在归档 Web 边界就绪时额外返回校验后的 `cli_server_origin`；不返回 Operator key、内部 socket、CA 或其他配置。archive 域的 setup 不返回该字段。 |
| 客户端解析 | `cliServerOrigin(configured, site)`：部署配置优先；否则仅在站点自身为 HTTPS 时复用站点 origin；都不可用时生成不含服务器地址的通用 Prompt（与仓库/Release 发行文本一致），不再报错，也不把普通 HTTP 地址当作 CLI 服务器。 |
| 授权页 | 安装 Prompt、手动「绑定此服务器」命令、已授权客户端的「添加项目授权」Prompt 共用同一解析后的 CLI origin；从项目入口进入时仍带入 Project ID 预选。 |
| 安装 Prompt 组件 | 可显式接收 CLI origin。未接入配置数据的入口（如项目页 CLI 安装指引）生成通用 Prompt，不再显示错误；错误提示文案不再要求「通过 HTTPS 地址打开页面」。 |

配置值只用于生成公开 Prompt 与绑定命令文本；校验失败或未配置时退化为通用 Prompt，不泄露内部地址。

## 定向检查与结果

- 定向 Web 回归 `archive-boundary`、`cli-install-prompt`、`cli-install-prompt-ui`、`archive-ui`、`local-mode-guide`：26 项通过；覆盖配置值验证与降级、HTTP 站点不再报错、页面 Prompt/绑定命令携带配置地址、archive 域不暴露该字段。
- 全量 `npm test`：163 项中 161 项通过。2 项为本次改动前已存在的本机环境失败，不是本轮引入、也不标为通过：`cloud-server-tls` 依赖的 `OPENSSL_CONF=/dev/null` 组合在本机 LibreSSL 3.3.6 下无法签发证书；`memory-operation` 的 fake-indexeddb 在本机 Node 环境报 `NotFoundError`。两项均不涉及本次修改的文件。
- `npm run typecheck`（`next typegen` + `tsc --noEmit`）通过。

## 部署记录

- 代码提交与推送：Git `b21a312226fe98e6da26da6204576c9a89bec47a`。
- Web 镜像：`hypertest-mac-web:b21a312`，ID `sha256:469600a68790e64d471a103739dd768677982fc8742ff44df47a5a2c9be0da81`，`linux/arm64`，由上述提交的干净 checkout 构建；构建产物内确认包含 `HYPERTEST_CLI_SERVER_ORIGIN` 路由代码。
- 部署配置：`~/.local/share/hypertest-mac/wireguard.compose.json` 增加 `HYPERTEST_CLI_SERVER_ORIGIN=https://localhost:18444` 并切换到新镜像；变更前配置备份在该目录 `delivery-cli-prompt-origin-20261028/wireguard.compose.json.before`。
- 仅重建 `web-wireguard`。API（`hypertest-mac-api:cdc70d3`）、BFF、PostgreSQL、Worker 配置与 PowerContext 容器、镜像、数据卷保持不变，未执行迁移。
- 现场核实：`web-wireguard` healthy；`/` 与 `/cli-authorizations` 均 HTTP 200；`GET /api/cli-authorizations/setup` 返回 `{"configured":true,"cli_server_origin":"https://localhost:18444"}`；`GET /api/archive/setup` 仍只返回 `{"configured":true}`；`/api/v1/health` 为 200 / `status: ok`。
- 用页面同一解析与生成逻辑对现场 setup 模拟：HTTP 站点 + 配置 origin 生成完整中文 Prompt，包含「目标 HyperTest One 服务器：https://localhost:18444」和 `hypertest auth bind --server 'https://localhost:18444' ...`；无配置时通用 Prompt 与仓库发行文本逐字节一致。
- 用本机 Headless Chrome（`--dump-dom`，虚拟时间预算 12 秒）实际加载 `http://10.66.66.3:3000/cli-authorizations`：DOM 中不再出现「无法生成安装 Prompt」，只读 Prompt 文本域为 2891 字符，含「目标 HyperTest One 服务器：https://localhost:18444。」、`hypertest auth bind --server 'https://localhost:18444' ...`、Skill 安装命令与 `SSL_CERT_FILE` 说明；页面同时显示「复制安装 Prompt」按钮和手动绑定命令。
- 未执行真实浏览器中的剪贴板点击、视觉截图或完整 Agent 安装执行；未重新运行全量后端回归，也未创建任务、执行测试或上传产物。用户功能验收为 USER_OWNED。

## 已知边界

- 本机测试部署的 CLI TLS 入口只发布到回环 `127.0.0.1:18444`，CA 为 `~/.local/share/hypertest-mac/bff/ca.crt`，所以配置值为 `https://localhost:18444`：Prompt 指向的执行机器是本 Mac 上的 Agent。若 Agent 运行在其他 WireGuard 对端，需要另行提供该对端可访问的 CLI HTTPS 入口；本轮不扩大现有回环边界，也不把 WireGuard HTTP Web 地址当作 CLI 服务器。
- 项目页 CLI 安装指引未接入 setup 数据，仍生成不带服务器地址的通用 Prompt（Agent 会再询问），不再显示错误；带地址的完整 Prompt 由 `/cli-authorizations` 提供。
- 使用私有 CA 的终端仍需按[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)为每条 CLI 命令显式设置可信 CA（如 `SSL_CERT_FILE`）；安装 Prompt 沿用其「复用既有受信 CA 配置」的既有说明，本轮不新增部署专属 CA 参数。
