# HTTP 授权页剪贴板复制修复（2026-10-28）

用户在 `http://10.66.66.3:3000/cli-authorizations` 点击「复制安装 Prompt」时看到「无法写入剪贴板 / 请选中下方 Prompt，手动复制」。

## 根因

`navigator.clipboard` 只在安全上下文（HTTPS 或 localhost）可用。当前 WireGuard Web 为普通 HTTP，浏览器中 `navigator.clipboard` 为 `undefined`；三个自定义复制按钮直接调用 `navigator.clipboard.writeText`，异常被捕获后一律显示“无法写入剪贴板”，即使浏览器支持传统复制命令。

## 修复

新增 `web/lib/clipboard.ts` 的 `copyText(value)`：安全上下文优先使用异步 Clipboard API；不可用或写入被拒绝时，在同一次点击的用户手势内退回临时 textarea + `document.execCommand("copy")` 的传统路径；两条路径都失败才抛出，由页面展示原有手动复制 textarea。临时元素始终移除并恢复原焦点。

以下已改为共用该助手，不再直接访问 `navigator.clipboard`：

- `/cli-authorizations` 安装 Prompt（本次报告的问题）；
- `/cli-authorizations` 已授权客户端的「添加项目授权」Prompt；
- 任务页「复制归档 Prompt / 模板」。

## 检查

- 新增 `tests/clipboard.test.cjs`：安全上下文路径、无 Clipboard API 的传统复制路径、异步写入被拒后回退、两条路径都失败时拒绝并清理临时节点。
- 相关组件回归：`clipboard`、`cli-install-prompt-ui`、`archive-ui`、`local-mode-guide`、`archive-prompt` 共 26 项通过。
- 全量 Web 测试：168 项中 166 项通过。2 项为本次改动前已存在的本机环境失败（`cloud-server-tls` 的 `OPENSSL_CONF=/dev/null` 与本机 LibreSSL 不兼容；`memory-operation` 的 fake-indexeddb 本机异常），与本次改动无关，未标为通过。
- `npm run typecheck`（`next typegen` + `tsc --noEmit`）通过。

## 部署与浏览器验证

- 代码提交与推送：Git `7433ccfd7702f68e55035f0ba3dd2b41010e21e9`。
- Web 镜像：`hypertest-mac-web:7433ccf`，ID `sha256:44f9034ea30e3b39a12350506475237c6a9330ee73c34d856b646bcf5af22b3f`，`linux/arm64`，由上述提交的干净 checkout 构建；`wireguard.compose.json` 切换到该镜像，仅重建 `web-wireguard`。API、BFF、PostgreSQL、Worker、PowerContext、数据卷与 schema 未变，未迁移。
- 通过 Chrome DevTools Protocol 驱动本机 Headless Chrome 实际加载 `http://10.66.66.3:3000/cli-authorizations` 并点击「复制安装 Prompt」：
  - `window.isSecureContext=false`、`typeof navigator.clipboard="undefined"`，确认本页只能走传统复制路径；
  - 点击后状态文本为「已复制，请粘贴到本地 Agent 会话。」，页面不出现「无法写入剪贴板」；
  - 手动复制区域保持折叠，Prompt 文本域仍含外部设备地址 `https://10.66.66.3:18444`。
- 未执行真实用户浏览器/不同操作系统剪贴板权限的逐一验收；手动复制 textarea 始终保留为兜底。外部设备真实配对与产物推送仍属 USER_OWNED 验收，见[外部设备接入记录](CLI_EXTERNAL_DEVICE_ACCESS_DELIVERY_20261028.md)。
