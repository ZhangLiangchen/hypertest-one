# 本地 Harness Connector 操作指南

本指南面向单 Operator 部署的管理员和本地设备使用者。`LOCAL_CONNECTOR` 让本机 Codex CLI、受控 Git 采集器及可选 GitLab 适配器复用本机实际可用的授权；平台 API、Worker、数据库、Verifier、Gate 和可信 Runner 保留原职责。服务器 `SERVER_HOST` / UDS Bridge 模式继续使用，已有 Run 不迁移、不回填；本地离线不会自动切换到服务器。

实现依据为 [ADR-015](architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md)。本指南描述当前接口及运维方式，不表示已部署到生产，也不以配置成功替代真实 Provider、私有 Git 或 GitLab 验收。GitLab 的策略和操作账本另见 [本地受控 GitLab 提单](LOCAL_CONNECTOR_GITLAB.md)。

## 1. 部署前提与信任边界

- 平台与 Worker 使用同一版本代码，数据库已完成 `0015_connector_nodes` 至 `0018_harness_selection` additive migrations；在平台正常备份流程后执行 `python -m alembic upgrade head`。不要修改 `0013` / `0014` 或回填旧 Run。
- 平台使用 PostgreSQL durable jobs，保持 `HYPERTEST_EXECUTION_MODE=queued`；保留现有服务器 Harness 所需的 `HYPERTEST_HARNESS_MODE=bridge`、Bridge socket、独立执行/管理 key 与服务器原生认证。
- 平台设置非空、随机的 `HYPERTEST_CONNECTOR_OPERATOR_KEY`，可设置 `HYPERTEST_CONNECTOR_OPERATOR_IDENTITY=local-operator`。未配置管理 key 时，设备管理接口返回 503。当前是单 Operator 管理入口，不具备用户登录、RBAC 或多租户隔离承诺。
- Connector 只需 Python 3.12+、本仓库依赖、本机 `git` 和受支持的 Codex CLI。启动前在同一本机身份及环境中确认 Provider 登录和批准仓库访问实际可用；浏览器登录不代表这些进程已授权。
- 设备仅主动连接平台 `WSS`；源码通过独立 `HTTPS` 发送。电脑不开放入站端口，Connector 不需要数据库 URL、平台管理 key 或 Docker 权限。
- 第三方 token、SSH 私钥、Provider 认证目录和 cookie 留在本机。平台单独保存设备 token 的 hash，项目能力授权不携带第三方凭据。源码会上传到平台并用于可信 Runner，不能把“认证留本地”理解为“源码不出本机”。

生产连接及网络变更先读 [服务器操作](SERVER_OPERATIONS.md#当前访问与巡检规则2026-10-19-更新)。继续使用现有 VPN / 来源白名单与严格 SSH 公钥巡检，保留密码恢复登录和 host-key 校验，不恢复 SSH Web 隧道、不开放额外公网入站口。

## 2. HTTPS、WSS 与反向代理

`api_url` 必须是完整 API 基址，例如 `https://hypertest.example.com/api/v1`。Connector 从它派生 `wss://hypertest.example.com/api/v1/harness-connectors/ws`，并向同一基址上传源码。不要填 Web 前端页面 URL、UDS 路径或 URI 内认证信息。

平台入口必须配置有效服务器证书并转发 WebSocket Upgrade；代理的正文上限须覆盖 48 MiB 的源码包，读取超时须覆盖有界上传与校验。API 和 Worker 继续共享原受控 Artifact 存储，不能只更新 Git checkout 而保留旧容器运行时。

API 与 Worker 也必须以相同的绝对路径共享既有 Workspace 存储。源码上传 staging 与不可变包留在 Artifact Root 的 `sources/`，接受后的只读 checkout 位于 Workspace Root 的 `.hypertest-source-checkouts/<bundle SHA-256>`；原生会话副本继续在同一 Workspace Root 下。Artifact 与 Workspace 可以是独立的 sibling 挂载，不能为兼容错误目录而放宽 Workspace 边界。既有接受记录中的路径不原地改写。

可在既有受保护 HTTPS server 中加入或核对以下转发语义；保留原 ACL、来源白名单及其他路由，不原样替换生产配置：

```nginx
# http 层，已有同类 map 时复用。
map $http_upgrade $hypertest_connection_upgrade {
    default upgrade;
    '' close;
}

# 既有 HTTPS server 中；api:8000 是示例内部 upstream。
location /api/v1/harness-connectors/ws {
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $hypertest_connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 150s;
}

location /api/v1/source-transfers/ {
    proxy_pass http://api:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 50m;
    proxy_request_buffering off;
    proxy_read_timeout 150s;
    proxy_send_timeout 150s;
}
```

由可信代理终止 TLS 时，ASGI 只信任该代理的转发头来源，使 `Request.url.scheme` / `WebSocket.url.scheme` 正确反映 HTTPS / WSS。不要无条件信任不受控客户端的 `X-Forwarded-Proto`。正文上限与超时只是传输配置，不能放宽平台对真实长度、hash、scope 和 expiry 的验收。

使用私有 CA 时，把 CA 公共证书放到本机可信目录，在 Connector JSON 中设置 `ca_file`。这个 CA 同时用于 WSS 和 HTTPS，仍验证主机名及证书链；证书 SAN 必须匹配 `api_url` 的主机。正常公有 CA 证书可省略 `ca_file`。不要关闭证书校验，HTTP 与 WSS 重定向均被禁止。

`allow_insecure_loopback: true` 只供隔离开发测试的 `localhost` / `127.0.0.1` / `::1`；API 端还须显式设置 `HYPERTEST_CONNECTOR_ALLOW_INSECURE_LOOPBACK=true`。它不允许远程 HTTP 部署。

## 3. 配对并保存设备凭据

也可使用 Web 项目页的本地 Harness 配对与授权表单。管理 key 由操作者输入，不打入前端 bundle。下面给出等价 API 操作。

以下 shell 变量只含入口和路径，UUID、域名、项目 ID 均为占位值：

```bash
umask 077
export HT_API='https://hypertest.example.com/api/v1'
export HT_CONFIG_DIR="$HOME/.config/hypertest"
export HT_ADMIN="$HT_CONFIG_DIR/operator.curl"
mkdir -p "$HT_CONFIG_DIR"
```

管理员在 `operator.curl` 中配置管理 header，文件权限为 `0600`；私有 CA 环境再加入 `cacert`。管理 key 不应作为 shell 命令参数、提交文件或 Connector 配置的一部分：

```text
header = "X-Hypertest-Operator-Key: <平台配置的管理 key>"
header = "Content-Type: application/json"
cacert = "/absolute/path/to/hypertest-ca.pem"
fail-with-body
silent
show-error
```

首次设备配对固定稳定 `node_key`，例如 `my-mac`。显示名可读即可，节点身份不使用 IP、当前连接 ID 或 Provider session ID：

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/harness-nodes/pair" \
  --data '{"node_key":"my-mac","display_name":"我的 Mac","expires_in_days":30}' \
  > "$HT_CONFIG_DIR/pairing.json"
```

返回体包含 `node.id`、`node.node_key`、`grant_id`、`expires_at`，以及**只在该次响应返回的 `device_token`**。立即写入私有设备文件，只保留非秘密元数据：

```bash
python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ['HT_CONFIG_DIR'])
path = root / 'pairing.json'
paired = json.loads(path.read_text())
token = root / 'device.token'
token.write_text(paired.pop('device_token'))
token.chmod(0o600)
(root / 'node.json').write_text(json.dumps(paired, ensure_ascii=False, indent=2))
path.unlink()
print('node_id:', paired['node']['id'])
print('node_key:', paired['node']['node_key'])
PY
```

同一个稳定 node key 不能重新配对。需要更换设备 token 时使用轮换；已永久撤销的节点不能重新激活，应配对新节点，旧 Run 也不会换绑到它。

## 4. 分别批准项目能力

设备配对后默认没有任何 Project 的 Harness、源码或提单权限。先取得已有 HyperTest Project UUID，并设置：

```bash
export HT_NODE='<node.id UUID>'
export HT_PROJECT='<HyperTest Project UUID>'
```

批准此节点参与该 Project 的 Harness：

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/harness-nodes/$HT_NODE/capabilities" \
  --data "{\"project_id\":\"$HT_PROJECT\",\"capability\":\"harness\",\"constraints\":{},\"policy_version\":\"operator-v1\"}"
```

单独批准受控采集器访问精确的 credential-free origin。本地 Connector 配置中的 allowlist 也必须包含相同 origin：

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/harness-nodes/$HT_NODE/capabilities" \
  --data "{\"project_id\":\"$HT_PROJECT\",\"capability\":\"source_acquisition\",\"constraints\":{\"allowed_origins\":[\"git@gitlab.example.com:team/service.git\"]},\"policy_version\":\"operator-v1\"}"
```

origin 的 SSH / HTTPS 写法不自动互换；设备授权、传输请求和本地 allowlist 使用同一个批准引用。禁止 HTTP userinfo、密码、query token、任意 Git 协议及本地 `file:` 源作为正式 API 输入。源码来源信任明确授予受控采集器及其主机，平台仍独立验证 Git 对象闭包。

若需要 GitLab 提单，再单独授予 `issue_executor`，固定 integration、GitLab 数值 Project ID 和负责人 ID；完整 JSON 及服务器/本地策略见 [GitLab 配置](LOCAL_CONNECTOR_GITLAB.md#配置)。Harness capability 不隐含提单权限。

检查项目授权：

```bash
curl --config "$HT_ADMIN" "$HT_API/harness-nodes/$HT_NODE/capabilities"
```

同节点、Project、capability 同时只能有一个 ACTIVE 授权。变更 origin、项目或负责人范围时先撤销旧 capability，再建立新的授权记录；不能原地改写历史 scope。

## 5. 配置并启动本地 daemon

安装当前版本并使用本机原生登录身份启动：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

本机 `connector.json` 示例；将全部路径改成真实绝对路径，替换真实节点 ID。不要把平台数据库 URL、Operator key 或任何第三方 token 写进去：

```json
{
  "api_url": "https://hypertest.example.com/api/v1",
  "node_id": "00000000-0000-0000-0000-000000000001",
  "node_key": "my-mac",
  "device_token_file": "/Users/you/.config/hypertest/device.token",
  "state_dir": "/Users/you/.local/share/hypertest/node",
  "ca_file": "/Users/you/.config/hypertest/hypertest-ca.pem",
  "codex_binary": "/absolute/path/to/codex",
  "max_concurrent": 2,
  "source": {
    "allowed_origins": ["git@gitlab.example.com:team/service.git"]
  }
}
```

`ca_file` 可省略以使用系统默认 CA。`state_dir` 必须是规范绝对路径，不能经过符号链接；设备 token 是本机普通文件，权限 `0600`。daemon 建立私有状态目录、本机独立 Bridge key、UDS/MCP relay、原生会话与操作 journal。Provider 使用既有原生登录，但仍限制 native shell、native filesystem 和通用外部工具，不加载个人全部 MCP 权限。

```bash
chmod 600 "$HT_CONFIG_DIR/connector.json" "$HT_CONFIG_DIR/device.token"
.venv/bin/python -m hypertest.connector --config "$HT_CONFIG_DIR/connector.json"
```

启动成功后查询节点：

```bash
curl --config "$HT_ADMIN" "$HT_API/harness-nodes"
```

确认所选节点 `presence=ONLINE`、`node_key` 与配置相同，并具有协商后的协议、Provider 和受控源码能力。presence 只是最近心跳观察；在线不代表任务已恢复、拥有当前执行 grant 或测试通过。

可由本机 launchd / systemd / 进程管理器托管同一条命令。配置绝对 Python、Codex 和 JSON 路径，以实际授权的用户运行，把工作目录设为私有状态目录，确保 Git helper / `SSH_AUTH_SOCK` 在该服务环境中实际可用；日志目录和文件分别使用 `0700` / `0600`。不要以 root 运行、复制整份 Provider 认证目录或同时启动两个 daemon 使用同一状态目录。守护进程重启只恢复连接，不能自动开始新 Provider turn。

macOS 可使用如下 `~/Library/LaunchAgents/com.hypertest.connector.plist` 模板，先替换绝对路径并建立私有日志/工作目录，再停止前台 daemon：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.hypertest.connector</string>
  <key>ProgramArguments</key><array>
    <string>/absolute/path/to/venv/bin/python</string>
    <string>-m</string><string>hypertest.connector</string>
    <string>--config</string><string>/Users/you/.config/hypertest/connector.json</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/you/.local/share/hypertest/node</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>/Users/you/.local/share/hypertest/connector.log</string>
  <key>StandardErrorPath</key><string>/Users/you/.local/share/hypertest/connector-error.log</string>
</dict></plist>
```

```bash
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.hypertest.connector.plist"
launchctl print "gui/$(id -u)/com.hypertest.connector"
```

停止服务使用 `launchctl bootout` 对应 plist；重启前先确认原服务已停止。launchd 不继承交互 shell 的全部 PATH、agent 或环境变量，须在实际服务身份下验证授权可用；不要把 token 直接塞入 plist 或命令参数。

## 6. 创建一个本地模式 Run

Web 正常流程为：选择“本地 Harness”与已配对节点 → 批准项目和 origin → 固定完整 SHA → 接收并校验源码 → 提交 PRD、环境和配置 → 开始测试。源码准备不占 Mission 阶段预算。

API 使用以下顺序。各 JSON 文件只填写获准 origin 和真实完整 SHA，不填写本机任意 checkout 路径。

### 6.1 固定源码请求

`source-request.json`：

```json
{
  "request_id": "00000000-0000-0000-0000-000000000010",
  "node_id": "00000000-0000-0000-0000-000000000001",
  "idempotency_key": "source-service-revision-1",
  "origin": "git@gitlab.example.com:team/service.git",
  "commit_sha": "<40 或 64 位完整十六进制 SHA>",
  "ref": "feature/example",
  "policy_version": "operator-v1"
}
```

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/projects/$HT_PROJECT/source-transfers" \
  --data-binary @source-request.json
```

保存响应的 transfer `id` 为 `HT_TRANSFER`，显式派发采集：

```bash
export HT_TRANSFER='<transfer.id UUID>'
curl --config "$HT_ADMIN" --request POST "$HT_API/source-transfers/$HT_TRANSFER/dispatch" --data '{}'
curl --config "$HT_ADMIN" "$HT_API/source-transfers/$HT_TRANSFER"
```

本机采集器在任务专用目录使用本地 Git 认证获取固定 SHA，通过 HTTPS 申请限对象上传 grant，再上传 Git 对象包。平台独立验证来源 receipt、对象链、模式、路径和大小，只有 `ACCEPTED` 才能用于 bootstrap。节点未在线、授权缺失、源包被拒绝或结果未知时不能进入 Agent 阶段。网络超时后先 GET 原 transfer；已接受则复用，明确失败后的新采集使用新的 request / 幂等键，不覆盖原记录。

### 6.2 冻结输入和节点选择

`bootstrap.json`：

```json
{
  "repository_url": "git@gitlab.example.com:team/service.git",
  "commit_sha": "<与 accepted transfer 相同的完整 SHA>",
  "branch": "feature/example",
  "prd_text": "本轮真实 PRD 内容",
  "configuration_text": "{}",
  "environment": {"profile_id": "python-pytest-v1"},
  "harness_mode": "LOCAL_CONNECTOR",
  "harness_node_id": "00000000-0000-0000-0000-000000000001",
  "source_bundle_transfer_id": "00000000-0000-0000-0000-000000000020",
  "idempotency_key": "local-run-service-revision-1"
}
```

环境必须选择实际受支持且通过可信 Runner 预检的 profile，不能把此占位环境直接用于任意 SUT；受控 HTTP 服务环境的具体输入见现有 [执行环境](architecture/ADR-012_CONTROLLED_API_ENVIRONMENTS.md)。

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/projects/$HT_PROJECT/runs/bootstrap" \
  --data-binary @bootstrap.json
```

保存返回 Run `id` 为 `HT_RUN`。同幂等键的 mode、node、source transfer 或其他输入不同会冲突。Run 首次准入与 Binding 之后均不能静默更换节点、Provider、workspace 或模式。

### 6.3 开始完整周期并读取结果

```bash
export HT_RUN='<Run UUID>'
curl --config "$HT_ADMIN" --request POST "$HT_API/test-runs/$HT_RUN/jobs" \
  --data '{"operation":"ADVANCE_RUN","idempotency_key":"advance-service-revision-1","payload":{"execution_profile":"run-persistent-harness/v1","prepare_workspace":true,"backend":"docker","max_steps":32,"timeout_seconds":300}}'
```

`prepare_workspace:true` 满足现有请求 schema，但本地模式的服务器工作副本来自已接受的源码包；平台不需要重新向私有 origin 授权，也不采用用户电脑绝对路径。设备侧另行验证/物化同一源身份，创建 workspace 需要当前有效 Binding/epoch/Job claim；恢复只验证原目录，目录丢失不会自动重建成新会话。

```bash
curl --config "$HT_ADMIN" "$HT_API/test-runs/$HT_RUN/jobs"
curl --config "$HT_ADMIN" "$HT_API/test-runs/$HT_RUN/harness"
curl --config "$HT_ADMIN" "$HT_API/test-runs/$HT_RUN/executions"
curl --config "$HT_ADMIN" "$HT_API/test-runs/$HT_RUN/evidence"
curl --config "$HT_ADMIN" "$HT_API/test-runs/$HT_RUN/verdicts"
curl --config "$HT_ADMIN" "$HT_API/test-runs/$HT_RUN/reports"
```

设备 Agent 产生 Proposal，平台验证接受后建立 Canonical 链；服务器可信 Runner 独立核对输入并产生正式 Execution / Evidence，Gate 决定质量结论。报告成功生成与 `RELEASE_READY` 是不同结论，存在有效失败证据时可以正常得到阻断报告。

## 7. 断线、显式恢复与取消

连接与执行授权分开治理。平台先持久化 `SENT` 再发送请求；`SENT` 不重投。执行性排队请求固定连接 generation，不能在新连接上补发。旧请求到期或连接丢失后结果可能为 `UNKNOWN`，必须查询原 call / operation，不能靠重发 execute/resume 解决。

短执行 grant 不超过当前 Job lease 和 120 秒上限；当前 Worker 通常按较短请求期限派发并续约。Connector 用单调时钟 watchdog 到期中断受控调用。断线不是进程停止证明，重连、心跳和 Web 页面刷新都不自动恢复推理。

恢复步骤：

1. 恢复 VPN / TLS / 本机授权及**原节点、原 state_dir**，启动 daemon，确认 ONLINE。
2. 读取 Run 的 Harness 和 Job，等待当前有效服务器 Runner Execution 完成、收集或受控取消。它可以在本地离线时继续，不能提前换 epoch 使有效结果失去归属，也不能发第二个 Execution 冒充对账。
3. 在 Web 显式恢复，或按刚读取的 `binding.id`、`binding_epoch`、`row_version` 提交：

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/bindings/<binding UUID>/recover" \
  --data '{"expected_epoch":1,"expected_row_version":3}'
```

4. 平台以精确管理授权查询/中断旧 call、核对耗时、原生 Session、固定源码和原 workspace，确认旧 owner 已 fenced 后才推进原 Binding 的 epoch。收到状态冲突先刷新，不猜测或手改 epoch。
5. 恢复成功后再提交新的 `ADVANCE_RUN` Job / 幂等键，沿用原 Session。存在活跃 Job 时拒绝并发；`WAITING_INPUT` 应通过原持久问题回答，不能靠重连重复消费答案。

`CLOSED` / `FAILED` / `CANCELLED` 是终态。原 Session 或 workspace 确定丢失/篡改时保留历史并新建关联 Run，不复制其他聊天或新目录冒充恢复。

取消采用正常 Job 接口：

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/jobs/<Job UUID>/cancel" --data '{}'
```

平台先取消并 fencing 新工作；设备离线时清理仍可能待确认。设备回连只接收精确旧调用的受限查询/中断/关闭。保留状态目录和原生会话，直到平台确认清理完成；不要把 socket 关闭视为调用已停止。

## 8. 轮换与撤销

### 轮换设备 token

轮换保留稳定节点，立即撤销旧设备 grant 与相关执行授权；运行中的调用需按恢复流程治理，不保证无缝继续。先安排任务停稳或等待当前 Runner 收尾：

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/harness-nodes/$HT_NODE/rotate" \
  --data '{"expires_in_days":30}' > "$HT_CONFIG_DIR/rotation.json"
```

将新响应的 `device_token` 以 `0600` 原子替换原 token 文件，移除包含明文 token 的临时响应，再重启原 daemon：

```bash
python - <<'PYROTATE'
import json
import os
from pathlib import Path

root = Path(os.environ['HT_CONFIG_DIR'])
response = root / 'rotation.json'
rotated = json.loads(response.read_text())
temporary = root / 'device.token.new'
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write(rotated.pop('device_token'))
    output.flush()
    os.fsync(output.fileno())
os.replace(temporary, root / 'device.token')
(root / 'node.json').write_text(json.dumps(rotated, ensure_ascii=False, indent=2))
response.unlink()
PYROTATE
```

`node_id`、`node_key`、state_dir、workspace 和原生 Session 保留。旧 token 只可识别原设备以完成精确管理查询/清理，不能发起新的执行或源码验收。

### 撤销项目能力

先 GET 项目 capabilities，找到对应 `capability_id`：

```bash
curl --config "$HT_ADMIN" --request POST \
  "$HT_API/harness-nodes/$HT_NODE/capabilities/<capability UUID>/revoke" --data '{}'
```

撤销 Harness、source acquisition 和 Issue 权限分别生效。授权范围变更需要新记录；已经接受的 Evidence / Verdict 保留。Issue 结果未知时仍只查询原 operation，不能再 POST 或改用服务器 executor。

### 永久撤销节点

```bash
curl --config "$HT_ADMIN" --request POST "$HT_API/harness-nodes/$HT_NODE/revoke" --data '{}'
```

平台立即拒绝新工作；可达设备接收撤销并停止调用，离线设备最迟受现有 grant/watchdog 限制。节点 `REVOKED` 不重新激活，不删除节点、绑定、operation 或审计历史。将来使用新设备需要重新配对和新 Run。

## 9. 保留、排障与回退

| 现象 | 检查与处理 |
|---|---|
| 管理 API 503 / 401 | 平台是否显式配置管理 key；私有 curl 配置是否为当前 key；不要把 Operator key 传给设备 |
| `DEVICE_AUTHORIZATION_REVOKED` | 设备 grant 是否过期/撤销，是否已轮换但 daemon 仍读取旧 token；使用轮换流程，不能重新激活旧 grant |
| `NODE_OFFLINE` / 非 ONLINE | 原 daemon 是否运行、同一身份能否访问 VPN / TLS、节点 key 是否匹配；检查私有日志，不启动替代节点 |
| TLS / WSS 握手失败 | URL 必须以 HTTPS 开头、CA/SAN/有效期正确、反向代理允许 Upgrade 且只信任受控转发来源；不关闭证书验证 |
| `PROJECT_CAPABILITY_REJECTED` / source scope 拒绝 | Project、节点、capability、origin、policy_version 是否逐项匹配且 ACTIVE；本机 allowlist 也需匹配 |
| Git 认证失败 | 检查 daemon 实际用户的 Git helper / SSH agent / 私钥权限与原 host-key 验证；不复制凭据到服务器、不开放交互密码提示 |
| 源包被拒绝 | 核对固定 commit、tracked 秘密、对象/总大小、文件数量、LFS/submodule/symlink；选择合规的新 commit，不过滤 tracked 文件后冒称原 SHA |
| `OUTCOME_UNKNOWN` / `UNKNOWN` | 查询原 transfer/call/Issue operation；保留 ledger，按显式恢复治理，不重发外部副作用 |
| `EVENT_CURSOR_GAP` / 非法 wire 结果 | 当前有界事件窗口最多 256 条，缺口/未知字段会明确拒绝；保留原 call，先中断和对账，不创建替代调用掩盖缺失 |
| workspace/native session unavailable | 确认原磁盘、路径权限和认证身份；确定丢失或篡改须新 Run，网络暂时不可用则保持恢复待处理 |
| 可信 Runner 慢或失败 | 分别检查服务器 owner/lease、Docker、镜像及受控 source copy；本地 Harness 在线不证明 Runner 正常，不重复启动正式执行 |

当前控制消息最大 4,000,000 bytes、单节点未完成 mailbox 上限 256；源码包上限 48 MiB、展开对象总量 32 MiB、最多 50,000 个对象 / 25,000 个文件。单对象上限以 `connector/source.py` 的 `MAX_OBJECT_BYTES` 为准。首版拒绝 submodule、LFS 和全部 symlink，tracked 秘密明确拒绝而不静默过滤。服务器 staging 和本机 acquisition cache 也有独立配额；不要靠提高代理上限绕过这些检查。

必须保留本机 `state_dir/bridge`、`issues.sqlite3`、受控 workspace、设备 token 和原生 Provider 会话目录。Issue ledger 丢失后仍只能查询；保留既有平台 operation / Audit / Outbox。临时未接受包可按受控保留策略处理，Canonical Artifact、已接受 source 对象和活跃/待恢复 Run 的 workspace 不属于随意清理范围；当前不提供通用删除 journal / 重置 operation 的恢复命令。

停用本地能力时，先处理当前 Run / 不确定外部操作，撤销相应项目授权或设备，再停止 daemon。以后**新建** Run 可以显式选择 `SERVER_HOST`；已有本地 Run 不迁移到服务器。数据库有相关历史时迁移拒绝破坏性降级，应向前修复并保留配对备份，不删表或强行改 Alembic revision。

真实端到端验收应分别记录本地 Provider 原生会话、WSS/HTTPS、私有源来源及包摘要、远端 Runner Execution/Evidence、Gate/报告、真实 Issue，以及断线、撤权和原会话恢复。自动化 fixture、能力声明与在线状态不能替代这些证据。

## 10. 既有线上平台完整周期验收

`scripts/adr015_online_cycle.py` 只连接已部署的 HTTPS API，只在本机启动 Connector，不启动另一套 API、数据库、Worker 或 Docker Runner。它为公开 Sum API fixture 建立独立 Project / node，分别授予 Harness 和 source acquisition，上传完整 SHA 对应源码和该提交的实际 PRD，再由本机原生 Codex、平台 Worker 与服务器可信 Runner 完成测试及报告。它不配置、授权或创建 GitLab Issue。

平台 Operator key 须放在操作者拥有的 `0600` 普通文件；设备 token 和私有配置另存新建 `0700` 状态目录。使用部署对应的本地虚拟环境及已发布完整提交，先验证本机参数：

```bash
.venv/bin/python scripts/adr015_online_cycle.py \
  --api-url 'https://hypertest.example.com/api/v1' \
  --operator-key-file /absolute/private/operator.key \
  --ca-file /absolute/private/hypertest-ca.pem \
  --commit-sha '<published full lowercase SHA>' \
  --state-dir /absolute/private/new-online-acceptance \
  --dry-run
```

确认线上部署与测试写入已获授权后，移除 `--dry-run` 运行。私有 CA 只通过本次 API / Connector 的 `ca_file` 使用，不修改系统 trust store；公有受信证书可省略该参数。脚本不打印入口、管理 key、设备 token、Provider 输出或工作区路径，摘要只保存受控身份、摘要及正式状态。

成功须同时满足 Job `SUCCEEDED`、固定本地 Binding `CLOSED`、Docker Execution `COMPLETED / PASS`、可信 `VERIFIED` Runner Evidence、原 FINAL `RELEASE_READY` Verdict 和报告正文 SHA-256 一致。默认保留本机 Connector 供后续使用；`--stop-connector-on-success` 只在上述终态确认后停止该进程。超时或结果未知时保留原 Run / Job / transfer 和本机进程，不自动重发 POST、不新建第二轮绕过失败，也不自行恢复；按前述恢复流程处理原身份。
