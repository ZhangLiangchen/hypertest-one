# CLI HTTPS 信任配置（2026-10-27，远端部署历史）

> **历史记录。** 本文的 CA、路径和命令属于 2026-10-27 的远端 Linux 部署，该主机及
> `ssh hypertest-one` 入口已不存在。当前测试环境是本 Mac 的 `hypertest-mac` 容器栈，
> CLI 入口使用本机生成的私有 CA `~/.local/share/hypertest-mac/bff/ca.crt`
> （CN=`HyperTest Mac Local CA`），不入库；当前配置见
> [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)和本机 `~/.local/share/hypertest-mac/README.md`。

本机 curl 与 Python 报 `unable to get local issuer certificate` 的本轮根因是未信任服务自有的 HyperTest One Connector CA。服务证书由此根 CA 直接签发（CA pathlen=0），没有缺失中间证书；把根证书添加到服务端发送链也不能替代客户端的信任配置。

## 可信公共证书

[下载 CA 公共证书](certificates/hypertest-one-connector-ca.crt)。此文件只有 X.509 公共证书，不含任何私钥、客户端凭据或平台授权。

- 文件 SHA256：`9647d9a2b33572f328e225910aafe276756a6acb90f44427db37a793b4389396`
- 证书 SHA256 指纹（DER）：`9B:3C:F1:B7:92:FC:14:BE:C8:84:03:47:57:CB:7D:DA:95:AB:8C:BA:0E:94:6C:D2:36:CB:9A:53:1A:1D:67:E6`
- CA 有效期至 2027-10-19 12:06:16 UTC；当时服务证书有效期至 2027-04-17 13:02:50 UTC。续签和 CA 轮换应分别维护，不能关闭有效期检查。

当时通过已验证的 GitHub 仓库连接取得此证书，或经当时运维 SSH 通道读取公共文件；不要从发生证书错误的连接中直接抓取证书并盲目信任。当时的服务器公共 CA 路径为 `/etc/hypertest/cloud-platform/d065ae2e27b6ff37c87a8ebe0c549a96dda45a73/issuer-ca.crt`，不是用户本机路径；该路径现已不可用。

## 当时的本机修复

将公共证书保存到用户级固定位置，例如 `~/.config/hypertest/connector-ca.crt`；先核对上面的文件摘要及证书指纹，再配置调用。不要覆盖该位置已有的不同证书。

```sh
openssl x509 -in "$HOME/.config/hypertest/connector-ca.crt" -noout -fingerprint -sha256
```

curl 对 HyperTest 地址使用 `--cacert "$HOME/.config/hypertest/connector-ca.crt"`。Python CLI 在每次 HyperTest 调用时显式传入公开 CA 文件：

```sh
SSL_CERT_FILE="$HOME/.config/hypertest/connector-ca.crt" hypertest auth reconcile --request-id ORIGINAL_REQUEST_UUID --json
```

这保持证书链、主机名与有效期校验。只给 HyperTest 命令配置此环境变量；无需修改整个操作系统信任或关闭 TLS 校验。后续本机 Agent 运行 HyperTest 时也必须继承或显式设置该变量，不能假定上一个工具调用的 shell 环境会自动保留。

先按原 request ID 查询。只有确认上阶段状态、且下一阶段尚未发送时才使用原请求的 `auth bind --resume`；UNKNOWN/NOT_FOUND 不允许换 ID 重发。授权已过期或恢复仍被拒绝时，报告实际状态，不把 TLS 修复等同于配对成功。用户仍须亲自完成网页授权。

## 本轮验证与范围

2026-10-27 在现有 nginx TLS Unix socket 上，以实际服务身份验证：默认 Python 系统信任复现 issuer 错误；显式使用上述 CA 后 TLSv1.3 握手成功、证书身份验证通过。实际服务叶证书 SHA256 为 `bfa3fbb7b6fcb30e9232770871492f9d8167264cfa0c747288eec1be13f0c04f`；本地 OpenSSL 验证服务证书由该 CA 签发通过。

本轮发布公共 CA 与操作指导，没有更换服务证书/私钥、修改 nginx ACL、部署应用、修改数据库或查询用户配对记录。用户本机 curl/Python 的复核及原请求恢复仍需在原本机执行；不能将服务器 TLS 检查写作本机安装或项目授权已验收。
