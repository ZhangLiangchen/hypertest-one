# 外部设备 CLI 接入（HTTPS over WireGuard）交付（2026-10-28）

外部设备需要用本机 `hypertest` CLI 把测试产物推送到 HyperTest One，但 CLI 只接受 HTTPS（`src/hypertest/cli/transport.py` 的 `HTTPS_SERVER_ORIGIN_REQUIRED`，API 侧 `require_tls` 也强制 TLS），且原 CLI TLS 监听只发布到回环 `127.0.0.1:18444`、证书 SAN 仅 `localhost`，因此外部设备无法使用。

本轮**不**放宽 HTTPS 合同（那需要发布新 CLI、放宽 API/协议并失去服务器身份校验），而是把同一 CLI TLS 入口发布到 WireGuard 地址 `10.66.66.3:18444`，重签带 WireGuard IP SAN 的证书，并在授权页安装 Prompt 中带入服务器地址与公开 CA 证书。CLI 二进制、发行资产、API 与归档/授权合同均未改动。

## 变更

| 范围 | 变更 |
| --- | --- |
| Bootstrap（部署） | 用现有本机 CA 重签 `cli-server.crt`：SAN 为 `DNS:localhost, IP:127.0.0.1, IP:10.66.66.3`（原证书仅 `localhost`/`127.0.0.1`）。新旧证书指纹见下文部署记录。 |
| BFF（部署） | CLI TLS 监听同时发布到 `127.0.0.1:18444` 与 `10.66.66.3:18444`；nginx Host 校验接受 `localhost:18444` 与 `10.66.66.3:18444`，其他 Host 仍 421；API/BFF 路由白名单、Operator key 隔离、批准页 302 均不变。 |
| Web 配置 | `HYPERTEST_CLI_SERVER_ORIGIN=https://10.66.66.3:18444`（外部设备使用的 CLI 地址），新增 `HYPERTEST_CLI_CA_FILE=/run/hypertest-bff-ca/ca.crt`（公开 CA，容器内已只读挂载 `bff/ca.crt`）。 |
| setup 响应 | `GET /api/cli-authorizations/setup` 额外返回 `cli_ca_certificate`（校验通过的单张公开 PEM 证书）；archive 域 setup 不返回。不返回 Operator key、内部 socket、私钥或其他配置。 |
| 安装 Prompt | 地址使用外部设备可达的 `https://10.66.66.3:18444`；新增私有 CA 段落：要求 Agent 把公开证书保存到仅当前用户可读文件（示例 `~/.hypertest-cli/ca/hypertest-one.crt`，0600），每条 CLI 命令（含 `doctor`）显式设置 `SSL_CERT_FILE`，不导出全局、不加入系统信任库。 |
| Prompt 清理 | 移除已退休实现的说明与升级特例：`0.1.0` 临时修补/`before-stable-key-fix`/旧 `local-v*`、`mcp-v*`/旧 MCP/Hooks 接入叙述等；保留安全性说明（固定版本与摘要、保留既有 profile/journal/未决请求、原 key 恢复、不重发未知上传、不安装额外集成/桥接/后台进程）。仓库发行 Prompt 文本由同一文本源重新生成。 |

CLI 的私有 HTTPS 入口仍只放行 `/api/v1/local-archive/` 与 `/api/v1/cli-authorizations/` 并显式清空 Operator key；外部设备获得的是配对/归档能力，不是 Operator 管理权限。授权仍需用户在校验短码后明确批准项目、权限与期限。

## 检查

- 定向 Web 回归 `archive-boundary`、`cli-install-prompt`、`cli-install-prompt-ui`、`archive-ui`、`local-mode-guide`：27 项通过；覆盖 CLI origin/公开 CA 的校验与降级、只有合规 PEM 能进入 Prompt、页面 Prompt 携带地址/CA/绑定命令，以及旧版本噪音已移除。
- 全量 Web 测试：164 项中 162 项通过。2 项为本次改动前已存在的本机环境失败（`cloud-server-tls` 的 `OPENSSL_CONF=/dev/null` 与本机 LibreSSL 不兼容；`memory-operation` 的 fake-indexeddb 本机异常），与本次改动无关，未标为通过。
- `npm run typecheck`（`next typegen` + `tsc --noEmit`）通过；`scripts/render-cli-install-prompts.cjs --check` 通过（仓库中英文 Prompt 与文本源一致）。

## 部署记录

- 代码提交与推送：Git `a3f8a28786fe3945120698b28b3c38c60d2fc7c9`。
- Web 镜像：`hypertest-mac-web:a3f8a28`，ID `sha256:8bc28718358a65a6b3032998bf63cd82adace77e1a9da878da14d337a8dd5bf5`，`linux/arm64`，由上述提交的干净 checkout 构建。
- 证书：新 `bff/cli-server.crt` 由既有 CA（`bff/ca.crt`，SHA-256 `44d01aa6…cffe0207`，未更换）签发，有效期至 2029-01-25；SHA-256 指纹 `A5:9E:72:7A:64:14:89:B4:EC:03:2D:C8:D8:F7:D5:80:DB:77:B2:3C:09:E3:15:27:31:4E:A6:45:A5:6B:20:3F`（旧证书指纹 `B8:3A:C9:D9:…:0C:07:C6`）。`server.crt`（`hypertest.internal` Web socket）未变。
- 部署配置：`~/.local/share/hypertest-mac/bff.compose.yml` 增加 `10.66.66.3:18444:8443`；`bff/nginx.conf` 更新 CLI 监听的 `server_name` 与 Host 校验；`wireguard.compose.json` 切换到新镜像并设置上述两个 Web 变量。变更前文件备份在 `~/.local/share/hypertest-mac/delivery-cli-external-20261028/*.before`；构建日志、镜像 ID、证书前后指纹与 setup 响应也在该目录。
- 仅重建 `bff-proxy` 与 `web-wireguard`；API（`hypertest-mac-api:cdc70d3`）、PostgreSQL、Worker、PowerContext、数据卷与 schema 未变，未执行迁移。
- 现场核实：
  - `netstat` 监听 `10.66.66.3:18444`、`127.0.0.1:18444`、`10.66.66.3:3000`；`web-wireguard` healthy。
  - 经 WireGuard IP 用公开 CA 校验 TLS：`https://10.66.66.3:18444/api/v1/cli-authorizations/requests/<uuid>` 返回 404 `CLI_PAIRING_NOT_FOUND`（TLS 校验通过、请求到达 API）；回环 `https://localhost:18444` 同样返回 404。错误 Host 返回 421；不提供 CA 时 TLS 证书校验失败（未关闭校验）。
  - CLI 入口批准页跳转：`https://10.66.66.3:18444/cli-authorizations?request_id=…` → 302 `http://10.66.66.3:3000/cli-authorizations?…`。
  - `GET /api/cli-authorizations/setup` 返回 `configured:true`、`cli_server_origin: "https://10.66.66.3:18444"`、`cli_ca_certificate` 为单张公开 PEM（与部署 `bff/ca.crt` 逐字节一致）；archive 域不返回这两个字段。
  - 本机既有 profile 只读诊断：`SSL_CERT_FILE=…/bff/ca.crt hypertest doctor --profile hypertest-mac --json` 返回 `READY`（历史回环入口保持可用）。
  - 本机 Headless Chrome 实际加载 `http://10.66.66.3:3000/cli-authorizations`：不再出现「无法生成安装 Prompt」；只读 Prompt 文本域含「目标 HyperTest One 服务器：https://10.66.66.3:18444」、`hypertest auth bind --server 'https://10.66.66.3:18444' …`、公开 CA PEM 与 `SSL_CERT_FILE` 说明；不含 `localhost`、`before-stable-key-fix`、`hypertest-local`、`local-v*`、`mcp-v*`、`0.1.0`。`/`、`/cli-authorizations`、API health 均 HTTP 200。
- 未从对端 `10.66.66.2` 实测外部设备；外部设备真实配对、批准、归档由用户验收（见下）。

## 边界与后续

- 本轮不放宽 CLI/API 的 HTTPS 要求：CLI 仍只接受 `https://`，没有 HTTP 或 `--insecure` 选项。若将来确实需要 HTTP，需新 CLI 发行、API/协议合同修改与新的无 Operator HTTP 入口，另行评估。
- 外部设备需要能经 WireGuard 访问 `10.66.66.3:18444`，并按 Prompt 保存公开 CA、为每条 CLI 命令设置 `SSL_CERT_FILE`；CA 证书是公开信任材料，不含私钥。CLI 回环监听保留只为历史本机 profile，不再写入新 Prompt。
- 外部设备的真实配对与归档属 USER_OWNED 验收：需用户在外部设备复制页面 Prompt、完成网页批准并推送真实测试产物；本记录的健康检查与只读探针不等于该验收。
