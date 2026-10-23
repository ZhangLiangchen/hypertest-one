# PowerContext 共享记忆服务部署与运维

核验日期：2026-10-22（Asia/Singapore）。这是独立服务的实际部署记录；HyperTest 的 Memory Broker、Project 授权映射以及 Cloud / Local Agent 接入仍待实现。本轮没有安装 Host 插件、启用聊天捕获或导入已有会话。

## 当前部署

PowerContext 部署在用户指定的独立主机。该主机同时承载既有 VPN / 跳板服务；既有 Xray、SSH、443 监听及原有规则保持。遵循[服务器入口信息规则](SERVER_OPERATIONS.md)，真实地址和完整入口只保存于远端受保护的 `/etc/powercontext/deployment.json`，本文及模板使用 `POWERCONTEXT_HOST`。

| 项目 | 实际配置 |
| --- | --- |
| 操作系统 | Debian 13.7，x86_64，Python 3.13.5 |
| 资源基线 | 1 vCPU，约 962 MiB 内存、2.3 GiB swap、15 GiB 可用盘 |
| PowerContext | `1.4.0`，官方 tag `powercontext-v1.4.0`，对应 commit `cab054dbf6d86e2311b079388e5158178257def2` |
| 安装 | 独立 venv；`powercontext[cli,server]==1.4.0`，121 个依赖采用完整 SHA-256 lock |
| Bootstrap | `uv 0.13.5`，官方 PyPI wheel SHA-256 已校验；不修改系统 Python 包 |
| 运行身份 | `powercontext` 系统用户，独立 `powercontext.service` |
| API 后端 | 仅 `127.0.0.1:8000`；服务网络仅允许回环 |
| 外部入口 | 独立 HTTPS 8443；不占用原 443；本机完整 endpoint 见受保护部署 profile |
| TLS 代理 | Debian nginx `1.26.3-3+deb13u10` 包经 SHA-256 校验后独立解压，`powercontext-proxy` 非 root 用户；没有安装或启动默认 `nginx.service` |
| TLS 证书 | Let's Encrypt 正式 IP SAN 短期证书；staging 签发先验证；当前证书有效至 2026-10-28 |
| 续期 | 独立 Certbot `5.8.0` venv；每 6 小时检查，加最多 15 分钟随机延迟，持久 timer |
| 数据 | `POWERCONTEXT_HOME=/var/lib/powercontext`；SQLite `powercontext.db` 及同目录相关状态 |
| 鉴权 | `ACCESS_MODE=enforced`；服务器生成的静态 Bearer；`server.env` 为 `root:root 0600`，由 systemd 加载 |
| 能力 | Basic：显式 Memory 写入与全文检索 `fts`；无 Generation / Embedding 模型配置 |

没有承诺上述小规格主机的生产容量。本轮后端 cgroup 采样峰值约 234 MiB；systemd 设置 `MemoryHigh=300M`、`MemoryMax=420M`、最多 256 MiB swap、60% CPU，避免该独立服务挤占既有 VPN。持续负载、并发容量、重启风暴以及模型功能未验收。

静态 Bearer 对应同一服务身份；`access/me` 实测 `multi_principal=false`。Scope 是记忆组织单元，当前服务 token 不是按 Project 隔离的普通 Agent 凭据。token 仅留服务器受保护配置，不能分发到普通 Agent、子代理、仓库、URL、命令参数或聊天。面向多 Project / 多用户的接入需要 HyperTest 授权 Broker 或独立身份与部署隔离，不能把 Scope 当作 RBAC。

## 目录与配置

| 路径 | 用途 / 权限 |
| --- | --- |
| `/opt/powercontext/releases/1.4.0/venv` | 固定应用运行环境，root 管理 |
| `/opt/powercontext/releases/1.4.0/requirements.lock` | 实装应用依赖版本及 SHA-256；旁有 `requirements.in`、`provenance.json` |
| `/opt/powercontext/bootstrap/uv-0.13.5` | 经官方 digest 校验的独立 bootstrap |
| `/opt/powercontext/proxy/nginx-1.26.3-3+deb13u10` | 独立 Debian 包、二进制及来源 |
| `/opt/powercontext/certbot/5.8.0` | 独立证书环境及依赖 lock |
| `/etc/powercontext/server.env` | 非公开服务设置与 token，root 0600 |
| `/etc/powercontext/deployment.json` | 真实主机与入口，root 0600 |
| `/etc/powercontext/proxy.conf` | 渲染后的固定 Host / Origin / TLS 入口配置 |
| `/etc/powercontext/acme` | 正式 ACME 账户、续期记录、证书及私钥；保持受保护 |
| `/etc/powercontext/acme-staging` | 独立 staging 账户和测试证书；不用于正式代理 |
| `/etc/powercontext/proxy-tls` | 成对的正式证书版本；`current` 原子指向通过校验的完整版本；TLS key 仅 root / 专用代理组可读，后端用户不能读取 |
| `/var/lib/powercontext` | 服务用户私有持久数据，0700 |
| `/var/lib/powercontext-proxy` | 代理自己的临时文件，不与业务数据混用 |
| `/var/log/powercontext` | 受保护部署 / 验收记录；不采集请求 token 或聊天 |
| `/var/backups/powercontext` | root 私有的一致性备份；包含秘密配置，禁止公开归档 |

非秘密配置模板位于 [ops/powercontext](../ops/powercontext/)。它们只用于这个独立服务，不能覆盖现有 HyperTest Compose、SSH、VPN、主机全局 nginx 或其他 timer。`server.env.example` 中的 placeholder 必须在服务器替换为新生成的秘密，不能作为真实凭据使用。模板不包含可直接运行的通用安装器。

应用服务使用 `--no-env-file`，配置由 systemd 的 `EnvironmentFile` 从 root 私有文件注入，避免服务用户直接读取 root env 文件。显式设置：

```dotenv
POWERCONTEXT_SERVER_ACCESS_MODE=enforced
POWERCONTEXT_SERVER_DASHBOARD_ENABLED=false
POWERCONTEXT_SERVER_RUNTIME_ARTIFACT_PROCESSING_FAMILIES=[]
```

未配置 `INFERENCE_GENERATION_MODEL` 或 `INFERENCE_EMBEDDING_MODEL`。`capabilities` 实测 `memory_extraction=false`、`experience_generation=false`、`managed_skill_generation=false`、`handoff_generation=false`，检索仅 `auto` / `fts`。`tools/list` 仍列出部分生成工具；目录中出现名称不能证明模型能力已启用。

## TLS 与网络边界

PowerContext 原生服务使用 HTTP；独立 nginx 在 8443 终止 TLS，并将请求转至回环后端。80 仅为 Certbot standalone HTTP-01 challenge 放行：签发 / 续期期间短暂监听，平时没有 HTTP 服务；不在该端口接受任何 Bearer 或记忆请求。只新增这两个服务所需的精确 IPv4 UFW 规则，原规则保留。后端 8000 不对公网开放，8443 不提供匿名管理员访问。

代理严格接受受保护配置里的固定 Host，Origin 仅允许为空或精确的本服务 HTTPS origin；其他 Host 返回 421、其他 Origin 返回 403。外部验收保留真实 Host / Origin，MCP 可以正常初始化；未禁用上游 DNS rebinding 防护，也未修改固定 PowerContext 源码。访问日志关闭；不在 URI、日志或证据中放 token。健康路径按上游设计免鉴权，其余受保护 API / MCP 需要 Bearer。

短期证书需要持续续期。`powercontext-cert-renew.timer` 每 6 小时运行；Certbot 使用 `--no-random-sleep-on-renew`，随机延迟仅由 timer 管理。实际 renewal config 的 `deploy_hook` 与 timer unit 都已核对指向 `/opt/powercontext/deploy-certificate.py`，`preferred_profile=shortlived`；没有旧 shell hook 的有效引用。[deploy hook](../ops/powercontext/deploy-certificate.py) 先暂存完整证书 / key，核验有效期、私钥、配对、证书链及候选 nginx 配置，再原子切换一个 `current` 目录指针。它只 reload 专用代理，并以正常 CA / IP 校验确认实际服务的 leaf；失败恢复旧指针并尝试恢复旧代理配置，保留所有旧版本，不覆盖正在使用的一对文件。首次部署未启动代理时只准备完整有效版本。不能重启 Xray 或应用。

```bash
systemctl status powercontext powercontext-proxy
systemctl list-timers --all powercontext-cert-renew.timer powercontext-backup.timer
systemctl show powercontext -p ActiveState -p NRestarts -p MemoryCurrent -p MemoryPeak
journalctl -u powercontext.service -u powercontext-proxy.service --since '30 minutes ago'
```

检查外部入口时使用正常 CA / IP SAN 验证；不能用 `curl -k` 或关闭证书校验。需要鉴权的人工检查由受信运维工具从 root 私有配置读取 token 到内存；不要把 token 展开到 shell 参数、回执或终端输出。

## 本次实际验收

验收只涉及本 PowerContext 服务和合成数据，没有执行 SUT、模型调用或 HyperTest 测试任务。

| 检查 | 已核验结果 |
| --- | --- |
| `/health/live` / `/health/ready` | HTTP 200；ready JSON 明确 `status=ready`，database / runtime / authentication / access 均 ready，access_mode 为 enforced |
| 无 token / 错误 token | 受保护 REST 及 MCP 返回 401；不是仅检查 HTTP 200 |
| 正式外部 TLS | 独立本机客户端使用正常 CA 校验连接成功，无自签信任绕过 |
| 入口限制 | 错误 Host 421，错误 Origin 403 |
| Basic 能力 | 无模型，显式写入和 `mode=fts` 搜索成功；响应模式可以是 `text`，按真实命中判断 |
| 跨连接写入 / 读回 | 回环与独立 HTTPS 客户端各明确写入 1 次；原真实 Artifact、revision 1、content digest 保留；最终 FTS 命中 2 条合成记录 |
| MCP | 真实外部 Host / Origin；initialize 200、initialized notification 202、tools/list 200，56 个工具 |
| ACME | staging 和正式签发均成功；Certbot 续期 dry-run 与当时 deploy hook 通过；最终原子 hook 另行完成下一行实际验收，没有为修复重复申请正式证书 |
| 证书激活 / 回滚 | 新原子 hook 用现有有效证书激活成功；仅本代理临时注入 reload 失败后，hook 返回失败且指针恢复 previous、原代理 master 仍 active；移除探针后正常激活和 CA / leaf 校验成功 |
| 重启持久性 | 冷备后重新启动独立后端，新的外部进程读回两件原 Artifact 固定 revision / digest，FTS 命中两件；MCP 初始化及 56 工具目录再次通过 |
| 冷备 / 隔离恢复 | 08:26 UTC 备份双 SHA-256 成功；用独立 HOME / 8001 恢复后，原 revision / digest 与 FTS 一致，克隆已停止；08:36 UTC 后续配置 / 数据 checkpoint 另核双 SHA-256 成功 |
| 既有服务 | Xray 保留原 PID，`NRestarts=0`；原 22 / 443 监听保留 |

合成验收使用新创建的独立 deployment acceptance Scope（真实返回值），没有绑定或冒用 HyperTest Project。记忆只包含非秘密 marker，明确标注不是生产项目知识：

```text
scope_id: scp_468dp6dtf1g058pb5txvhqrg48
artifact: atomic-memory / art_fc5586a5db964f2fb2e56f3c7492dbaf / revision 1
external-write artifact: atomic-memory / art_34b301adaaf44eaa81ea8d89465d1dc1 / revision 1
marker: hypertestpowercontextacceptance20261022t0818
content_digest: sha256:504e8c794b5b66667f24fcbd86e4ea22778f690714b50d217dd95f1c5ff0ff0e
```

两次写入都由本次部署验收明确发起。实测相同文本的第二次 `remember` 返回 `changed=true` 和不同 Artifact，不能假设重复文本会幂等去重。两件合成记录及来源保留，不放入正式 Project 经验，未知写入结果也不能靠再次 `remember` 试探。最终跨进程读回核验两件实际引用，而非仅依赖搜索摘要。

MCP `serverInfo.version=3.4.11` 是此次 FastMCP 运行时版本；PowerContext 包版本由实装元数据另核为 1.4.0，不把两者混为一谈。一次 tools/list 成功不等于 Claude Code / Codex / DeepSeek Harness 已完成插件安装与真实会话接入。

最终外部复验时间为 08:37:33 UTC。原始部署证据保存在服务器 `/var/log/powercontext/` 的受保护 JSON / 日志中，包括 `backend-acceptance.json`、`restore-acceptance.json`、`certificate-activation-acceptance.json`、`final-backup.json`、`final-external-acceptance.json`、`final-operational-state.json` 和 `renew-hook-readback.json`；本仓库仅保留上述非秘密结论。外部客户端验收把 token 限制在进程内存，输出仅状态、真实对象引用与合成 marker 是否命中。

## 备份、恢复与升级边界

独立 `powercontext-backup.timer` 每日 UTC 03:15，加最多 15 分钟延迟。备份与证书维护共享本服务专用的 `flock`；不触及其他服务的锁。备份短暂停止这个独立后端，等待进程退出后保存完整 `POWERCONTEXT_HOME` 和配置 / 固定版本身份，再恢复原先 active 状态。代理与 VPN 保留；暂停期间记忆请求可能失败，调用方应降级处理，不能据此改写测试结果。

备份目录 0700、文件 0600，成对包含 `home.tar.gz`、`config.tar.gz`、`SHA256SUMS`。配置包含真实 token、ACME 账户及私钥，不能上传仓库、聊天或普通 Agent。禁止直接复制活跃 SQLite `.db` 充当完整备份，也不自动清理历史备份。

```bash
systemctl start powercontext-backup.service
systemctl show powercontext-backup.service -p Result -p ExecMainStatus
```

恢复时先校验 SHA-256，将同一备份的 HOME 解到隔离目录，用同一固定版本、独立 env / 回环端口启动，核验原 Artifact 固定 revision 和 FTS 读回；不能直接覆盖正式数据或更改正式 Scope 绑定。本机备份和隔离恢复不等于异地容灾。正式恢复、升级和凭据轮换要另做当前状态核验与维护窗口；保留旧 release、旧配置和原数据库，不用空库或重新生成身份掩盖失败。

本次实际隔离恢复来源是 `/var/backups/powercontext/20261022T082635Z`，恢复目录为 `/var/lib/powercontext-restore-check/20261022T082635Z/powercontext`，临时服务已停止且材料保留。最新冷备 checkpoint 为 `/var/backups/powercontext/20261022T083626Z`，保存当时的原子证书代理 / hook / timer 配置和两件合成记录；双 SHA-256 已核验，没有冒称该目录又做过一次隔离恢复。此后补记的 provenance 与实际 renewal config `deploy_hook` 不在该 checkpoint，另有受保护读回记录；checkpoint 内 timer unit 已显式指定新的 Python hook。恢复时仍须对照这些后续配置登记，不把 checkpoint 称为所有最终配置的快照。

出现 OOM / 重启风暴、鉴权或 TLS 失效、续期失败时先停用独立入口，保留数据和证据：

```bash
systemctl stop powercontext-proxy.service
systemctl stop powercontext.service
```

需要长期停用时仅 disable 这两个服务及本服务的两个 timer，再经受保护部署 profile 删除本轮精确新增的 80 / 8443 规则。保留原 SSH / Xray / 443 / VPN 规则、私有数据、备份和证书记录。不以开放明文 HTTP 或匿名管理员模式替代故障入口。

## 官方依据

- [PowerContext 1.4.0 官方 release](https://github.com/oceanbase/powercontext/releases/tag/powercontext-v1.4.0)：固定发布来源。
- [固定版本的远程部署说明](https://github.com/oceanbase/powercontext/blob/cab054dbf6d86e2311b079388e5158178257def2/docs/en/docs/operate/deploy-server.md)：原生 HTTP、受保护远程部署与 TLS 边界。
- [固定版本的模型配置说明](https://github.com/oceanbase/powercontext/blob/cab054dbf6d86e2311b079388e5158178257def2/docs/en/docs/get-started/configure-models.md)：无模型的基本能力。
- [Let's Encrypt 的 Certbot IP 证书说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)：IP SAN、短期证书与续期要求；本次另有实际签发和 dry-run 证据。
