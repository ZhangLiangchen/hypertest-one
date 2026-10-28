# CLI TLS 严格校验证书修复与原配对请求排查（2026-10-28）

外部设备（`zhangliangchendeMacBook-Air.local`）实测报告两个问题：

1. 其 Python 3.13 的严格 X.509 校验拒绝服务器叶子证书：`Missing Authority Key Identifier`；沿用 Python 3.12 的默认校验才能通过证书链、IP 主机名与有效期。
2. 首次 `hypertest auth bind` 返回 `UNKNOWN`，随后用原 request ID `58966389-8daf-44b0-8223-921eed7b1e38` 对账得到 `CLI_PAIRING_NOT_FOUND`，设备上既没有授权链接也没有短码。

本文记录证书修复、服务端排查结论、合同允许的恢复路径和用户侧下一步。

## 一、叶子证书缺少 SKI/AKI

- 根因：上一轮重签 `cli-server.crt` 时只写入了 `basicConstraints`、`keyUsage`、`extendedKeyUsage` 与 `subjectAltName`，没有 Subject Key Identifier 与 Authority Key Identifier。CA 证书本身已有 SKI（`EA:36:EC:…:44`）。Python 3.13 及更新版本的默认安全上下文启用 `VERIFY_X509_STRICT`，要求叶子证书带 AKI，因此握手在客户端证书校验阶段失败。
- 修复：用**同一 CA**（未更换，`bff/ca.crt`）重签叶子证书，新增 `subjectKeyIdentifier=hash`、`authorityKeyIdentifier=keyid:always,issuer:always`，并把 `basicConstraints=critical,CA:FALSE` 改为 critical；SAN 保持 `DNS:localhost, IP:127.0.0.1, IP:10.66.66.3`。新证书有效期至 2029-01-25，SHA-256 指纹 `7C:33:59:32:67:E2:7D:26:B9:37:DE:DD:3C:25:FD:0A:B7:3C:5A:61:EB:6F:C9:87:F7:39:CF:75:5F:C9:F9:C8`（旧指纹 `A5:9E:72:7A:…:20:3F`）。
- 部署：仅重启 `bff-proxy` 加载新证书；Web、API、数据库、镜像和 schema 均未变。旧证书、密钥与 CSR 备份在 `~/.local/share/hypertest-mac/delivery-cli-aki-20261028/`。

验证（详见该目录 `strict-verification.txt`、`leaf-after.txt`）：

- 修复前可用 Python 3.14 默认上下文复现 `FAIL 85 Missing Authority Key Identifier`。
- 修复后 `openssl verify -x509_strict` 通过；Python 3.14 默认上下文（含 `VERIFY_X509_STRICT`，与 Python 3.13 严格行为一致）对 `10.66.66.3` 与 `localhost` 均以 TLSv1.3 通过校验，HTTPS 请求可到达 API（只读 404 探针 `CLI_PAIRING_NOT_FOUND`）。
- Python 3.12 默认校验、`curl --cacert` 均通过；已发布 CLI 0.1.1 直接在 Python 3.14 下执行 `doctor` 返回 `READY`（本机既有 profile，只读）。
- CA 未更换，已按安装 Prompt 保存 CA 的外部设备无需重新安装或更换 CA。

## 二、原配对请求没有服务端记录

排查对象：request `58966389-8daf-44b0-8223-921eed7b1e38`，CREATE `idempotency_key=18da6331-6b68-4636-8efa-c79d62a0e030`。

- `cli_authorization_requests` 中该 request ID 计数为 **0**。
- API 日志（`2026-10-28T07:00Z` 起）只有两条该 request 的 `GET /api/v1/cli-authorizations/requests/by-key?…operation=CREATE…`，均返回 404；同一时间窗内 `POST /api/v1/cli-authorizations/requests` 计数为 **0**。
- 结论：CREATE 在客户端严格 X.509 校验阶段即失败，从未到达 API/DB；服务端没有可恢复的原请求记录（也不存在可对账的回执）。按“不得补造历史/未知外部操作不自动重发”的规则，未伪造或补写服务端记录。证据保存在 `delivery-cli-aki-20261028/pairing-attempt-evidence.txt`。

## 三、恢复路径（operator 核对结论）

- 外部设备上的该请求记录继续保持 `UNKNOWN`：不重放、不改正文、不换 key、不删除；它不构成任何服务端授权或事实。
- 由于服务端已确认该 request 从未创建（DB 无行、API 无 POST），旧请求不产生需要消除的副作用；在证书修复后，用户可为同一设备发起**新的显式授权意图**（新的 request ID，即重新执行 `hypertest auth bind`）。这不是对旧请求的重放，也不是在不确定结果上换 key 重签。
- 若未来按原 key 查询意外出现该请求的记录（当前证据下不应发生），应停下并按原 key 对账，不得把新请求的授权当作旧请求结果，也不得替换、改写或删除旧记录。
- 不要把本结论套用到其他 `UNKNOWN` 请求：任何其他失答请求仍只按原 key 查询，先核对服务端记录，再决定恢复路径。

## 四、用户侧下一步

1. 外部设备可直接继续用 Python 3.13（或既有 3.12）重试；Prompt、CA 和 CLI 版本都不需要更新。
2. 不要对 `58966389-8daf-44b0-8223-921eed7b1e38` 执行 `--resume` 或重放；保留其本机 UNKNOWN 记录。
3. 发起新的配对（新 request ID），示例：

```sh
SSL_CERT_FILE="$HOME/.local/share/hypertest-cli/ca/hypertest-one.crt" \
  hypertest auth bind --server https://10.66.66.3:18444 --profile default --wait-seconds 0 --json
```

需要为项目预选时附加 `--project-id PROJECT_UUID`（预选不是授权）。随后在网页核对短码并批准项目、权限与期限；CLI 用 `auth bind --resume --request-id <新请求ID>` 继续原请求或 `auth reconcile` 恢复。

## 五、边界

- 未在外部设备上复测：本轮以本机 Python 3.14 严格校验 + 已发布 CLI 0.1.1 `doctor` 验证；外部设备的真实配对、批准与产物推送仍属 USER_OWNED 验收。
- 证书仍由本机私有 CA 签发，外部设备必须按 Prompt 保存公开 CA 并逐命令设置 `SSL_CERT_FILE`，不加入系统信任库。
- 本轮没有重新构建或替换 Web 镜像（仍为 `hypertest-mac-web:7433ccf`），也没有改动 API/数据库/数据卷。
