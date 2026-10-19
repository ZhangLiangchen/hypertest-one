# 可选 Connector TLS 入口

本部署层对应 [本地 Connector 操作指南](../../docs/LOCAL_CONNECTOR.md)。它只把既有受保护的公网 `IP:INGRESS_PORT` 升级为 HTTPS/WSS，不增加监听地址或端口，不改变 VPN `/32`、UFW、DOCKER-USER、SSH、公钥校验或密码恢复通道。`HYPERTEST_INGRESS_TLS` 默认 `disabled`，仍生成原 HTTP 配置；服务器 Harness、Bridge 独立执行/管理 key、原生会话和 OAuth 配置继续保留。

## 配置归属

非秘密 `compose.env` 新增以下可选参数。地址、端口、来源白名单均使用现有受保护值；示例证书路径不是必须使用的生产路径。

| 参数 | 默认 / 含义 |
| --- | --- |
| `HYPERTEST_INGRESS_TLS` | `disabled`；显式 `enabled` 才选取 `compose.tls.yml` |
| `HYPERTEST_TLS_CERT_FILE` | 启用时必填，既有绝对路径，PEM leaf / chain 文件 |
| `HYPERTEST_TLS_KEY_FILE` | 启用时必填，独立绝对路径，PEM leaf 私钥 |
| `HYPERTEST_TLS_SERVER_NAME` | 默认既有公网 IPv4；可选小写 DNS 名，证书 SAN 必须匹配 |

以下参数仅保存在原受保护 `platform.env`，由 API / Worker 原有 `env_file` 注入；不写入 Web bundle、镜像、`compose.env`、命令参数或日志。

| 参数 | 配置要求 |
| --- | --- |
| `HYPERTEST_CONNECTOR_OPERATOR_KEY` | 随机管理 key，32–512 字符；TLS Connector 部署校验要求非空 |
| `HYPERTEST_CONNECTOR_OPERATOR_IDENTITY` | 现有单 Operator 身份，可用 `local-operator` |
| `HYPERTEST_CONNECTOR_ALLOW_INSECURE_LOOPBACK` | 生产必须为 `false`；不开放远程 HTTP 授权 |
| `FORWARDED_ALLOW_IPS` | Uvicorn 默认 `127.0.0.1`；追加 API 实际看到的唯一 host-nginx IPv4 peer，格式 `127.0.0.1,<observed IPv4>` |

nginx 使用 host network，反代到 loopback 发布的 API 时，API 通常看到既有 Docker network 的 gateway。应在该主机实测并核对既有 network，不凭示例猜测网段，不为此重建 network。校验拒绝 wildcard、CIDR、空格、重复地址及超过两个地址。API command 不覆写 Uvicorn 的 `FORWARDED_ALLOW_IPS`；readiness 会检查运行容器与受保护文件一致，拒绝命令行绕过代理限制。可信代理覆盖来客的 XFF / scheme / Host 转发字段，不启用 Real-IP 信任链。

## 证书与文件权限

使用公共 CA 或私有 CA 均可；证书 SAN 匹配实际 `api_url` 的主机。私有 CA 的签名私钥始终留在本机私有交付目录，服务器只接收 leaf 证书 / chain 及对应 leaf 私钥；不把 CA key 放入 Compose、Artifact、镜像或服务器。

nginx 身份是 `101:101`。leaf 私钥须可由该身份读取，且不得 group-writable 或 world-accessible，例如在受控服务器上安装为 `root:101`、`0640`；证书可为 `0644`。两个文件必须存在、为非 symlink 的独立常规文件。校验会检查可读权限并加载证书 / 私钥以确认匹配。`compose.tls.yml` 仅向 nginx 以只读 bind 挂载两个文件，禁止隐式创建路径；API、Worker、Web、PostgreSQL 均不挂载它们。

私有 CA 的公共证书通过客户端显式 `ca_file` / `curl --cacert` 使用，同时保留主机名验证；不关闭证书校验、不改变系统全局信任库。Connector 的 `api_url` 直接填写 HTTPS，不能依赖重定向。旧 HTTP URL 在原 IP / 端口返回 308 到 HTTPS，客户端仍须正确验证目标证书。

## 入口与验收

公网 HTTPS server 保留既有精确地址、端口、Host、Origin 和来源 ACL；TLS 1.2 / 1.3。loopback 同端口继续使用 HTTP，仅允许 `GET` / `HEAD /api/v1/health`，其余路径拒绝，不提供额外 Web/API 入口。

`/api/v1/harness-connectors/ws` 使用精确 WebSocket location，转发 Upgrade，读取 / 发送超时 150 秒。`/api/v1/source-transfers/` 使用独立前缀 location，正文上限 50 MiB，正文 / 读取 / 发送超时 150 秒，关闭请求缓冲。应用仍独立执行 24 MiB 单对象、32 MiB 总展开、48 MiB JSON 包限制及认证、scope、hash、过期和 quota 验收；代理限额不授予额外源码权限。

新运维包必须包含 `compose.tls.yml`、更新后的 `stack.py` / `readiness.py`。`ops-current` 是固定发布包，更新业务 checkout 不能替代运维包切换。`compose_command` 统一为启动、维护、备份和 readiness 选择 TLS overlay，也保留可选 GitLab Worker-only policy overlay。

在既有维护锁和成对备份流程内准备新配置文件；`render-nginx` 拒绝覆盖原文件。以下命令只验证或生成准备好的目标文件，不会激活监听；`HT_OPS_ROOT`、`HT_COMPOSE_ENV` 均由本次受控发布指定。

```bash
python "$HT_OPS_ROOT/ops/container/stack.py" --env "$HT_COMPOSE_ENV" --offline validate
python "$HT_OPS_ROOT/ops/container/stack.py" --env "$HT_COMPOSE_ENV" render-nginx
python "$HT_OPS_ROOT/ops/container/stack.py" --env "$HT_COMPOSE_ENV" validate
python "$HT_OPS_ROOT/ops/container/stack.py" --env "$HT_COMPOSE_ENV" config
```

维护锁内停止原 nginx 后、激活新入口前，使用同一 `compose_command` 执行 `run --rm --no-deps nginx -t`，确认固定 nginx 镜像及实际证书挂载可解析；该检查会测试 bind，不能让另一个 nginx 占用相同 IP / 端口。不要输出 `docker compose config` 的完整内容，它会展开秘密环境变量；`stack.py config` 使用 `--quiet`。

按既有受控启动流程切换后，readiness 检查 TLS 文件只读挂载、Operator 配置一致、精确代理 peer、网络守卫、HTTP health-only 回环及现有 Bridge / Runner 能力。它不证明外网 TLS、WSS、源码上传、Provider 或真实测试周期成功；这些需要本机从既有 VPN 使用指定 CA 做独立端到端验收，并核对原应用记录和服务器 Harness 仍可用。

回退使用维护锁恢复已记录的运维包、配置和镜像身份，保留原访问规则及全部数据。ADR-015 additive migrations 与现有 Run 历史不因入口回退而删除；不要回填旧 Run、复活终态会话或把本地离线 Run 自动切到服务器 Harness。需要数据回退时遵循原成对备份 / 隔离恢复演练流程。
