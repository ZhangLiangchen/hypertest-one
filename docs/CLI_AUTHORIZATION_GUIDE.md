# HyperTest CLI 授权与全局使用指南

更新：2026-10-27。**[cli-v0.1.0 已公开](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0)，固定源 Git 为 `d02ab1dd893200eb2eee398d795f9b96a41ab768`。公开下载摘要、Linux/Python 3.13 包安装与 Skill 安装已核验。部署与 USER_OWNED 验收仍分别记录在[本轮交付](LOCAL_ARCHIVE_DELIVERY_20261027.md)。** 架构见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)，任务拆分见[开发计划](LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)。

## 1. 一次绑定，按需归档

Web 全局「CLI 授权」页位于 `/cli-authorizations`，提供安装与绑定指引、配对确认、授权列表和撤销入口。完成一次用户级绑定后，同一电脑、同一操作系统用户下的终端和 Agent 可从任意目录复用 profile，不按仓库或会话重复绑定。

profile 固定 server、client 和 uploader actor，只能访问网页明确批准的 Project。其他电脑、操作系统用户或服务身份须分别授权。每次上传仍须填写 Project ID、Task ID；Subtask ID 可选，不从 profile、当前目录或上次操作推导。

测试期间无需运行 CLI，也不要求提前创建平台任务。完成测试后，用户在 Web 选择项目并创建或选择归档 Task，需要分组时再创建 Subtask，然后显式调用 Skill 或 CLI。命令执行完毕即退出，没有 MCP、Hooks、daemon、localhost callback、后台同步或自动续签。

## 2. 安装与升级

发行包为无第三方 Python 依赖的 `hypertest-cli-0.1.0.pyz`，附 release manifest 与独立安装器 `install-cli-release.py`。运行要求为 **Linux 或 macOS、Python ≥3.12**。本轮已实测 Linux/Python 3.13 的合成包安装、命令执行与 Skill 安装；macOS 尚未实际验收，不据此宣称已通过。

从「CLI 授权」页或 [cli-v0.1.0 发行记录](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0)下载 CLI 包和安装器到同一目录。
先核验安装器 SHA256 为 `20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95`，再运行下列命令（`python3` 需为 3.12 或更高版本）。网页还提供先校验安装器、再执行安装的一条命令。

```sh
python3 install-cli-release.py \
  --artifact ./hypertest-cli-0.1.0.pyz \
  --sha256 c96c8bb0380658d9eee2efd890eee6de95e9fbec11ec6d3255ba49448334713e --version 0.1.0
```

安装器核验实际包字节和版本，默认将版本文件保存在 `~/.local/share/hypertest-cli/releases/0.1.0/`，在 `~/.local/bin/hypertest` 创建使用当前 Python 的启动入口，并写入受管安装收据。如目录已有非本工具拥有或被修改的命令，保留原件并报冲突。可用 `--bin-dir PATH --install-dir PRIVATE_PATH` 选择位置；安装目录须由当前用户拥有且权限为 `0700`。

将 `~/.local/bin` 加入当前用户 PATH，使终端及其启动的 Agent 可使用：

```sh
export PATH="$HOME/.local/bin:$PATH"
hypertest --version
```

升级时下载新固定版本及对应摘要，重复安装命令并更换版本参数；原版本、授权配置、journal 和未决请求保留。新安装或升级不会配置宿主 MCP/Hooks，也不会自动绑定或签发授权。既有旧 Local 接入的显式退出见第 8 节。

## 3. 一条命令启动绑定，在 Web 确认一次

从「CLI 授权」页复制服务器专属命令，或将以下地址替换为实际 HTTPS 服务地址：

```sh
hypertest auth bind --server https://YOUR_HYPERTEST_HOST --profile default
```

可选 `--project-id PROJECT_UUID` 只预选项目，不表示已获得权限。无浏览器的终端可加 `--no-browser`，手动打开终端显示的同一 URL；不要复制凭据。命令最多等待 600 秒，可用 `--wait-seconds 0` 仅发起配对并退出等待。

正常流程：

1. CLI 在用户私有目录预存请求 ID、原操作 key、credential secret 和独立 verifier，发起配对后显示短码和网页地址。
2. 用户通过既有 Web 访问控制进入授权页，核对短码，选择既有上传 actor、明确项目 allowlist 和 1–90 天有效期，确认 `archive:read`、`archive:write` 两项权限。
3. 用户在网页确认一次；CLI 在命令存活期间查询批准结果，兑换固定授权，核对原 key 回执及当前授权状态，原子保存 profile 后退出。

默认用户数据目录为 `~/.hypertest-cli`；它保存私有 profile、配对记录、冻结请求和归档 journal，文件权限为 `0600`。`HYPERTEST_CLI_HOME` 可显式选择另一私有目录，但切换目录不会迁移原记录。不要让 Skill 读取这些文件，也不要把它们加入待上传目录。

绑定命令和网页 URL 不含长期 token、verifier 或 Operator key。短码仅用于核对，不是查询或兑换凭证。profile 可合并同 server/client/actor 下新获准的项目；不同身份的同名 profile 会被拒绝覆盖，应选用新 profile 名。绑定不会获得旧 `task:sync`、Cloud、Memory 或 Operator 权限。

配对窗口为 10 分钟，与所批准 grant 的有效期分开。过期、拒绝、撤销或失答不会自动触发新的绑定或扩权。

CLI 使用 Python `ssl.create_default_context` 校验 HTTPS。若服务使用私有 CA，先将该公开 CA 证书加入本机 Python 信任，或在启动 CLI 的终端明确设置 `SSL_CERT_FILE=/absolute/path/trusted-ca.pem`。文件只应包含受信任的公开 CA 证书，不放任何私钥；不要关闭 TLS 校验，也没有 `--insecure` 选项。

## 4. 查看、恢复和撤销授权

```sh
hypertest profile show --profile default --json
hypertest auth status --profile default --json
hypertest auth status --request-id PAIRING_REQUEST_UUID --json
hypertest auth reconcile --request-id PAIRING_REQUEST_UUID --json
```

`profile show` 和 `auth status` 只读本机安全元数据；显示的是本地保存状态，不宣称已在线核验当前权限。`auth reconcile` 使用私有 proof，按原 CREATE/REDEEM key 查询固定回执，再检查当前状态；它不发送新的配对或兑换 POST。已 BOUND 且当前 grant 有效时，可恢复 profile 保存。

SENT、UNKNOWN、失答或 NOT_FOUND 均不证明先前写入没有执行。保留原请求，不能换 key 重发、删除 journal 或重新签发来绕过未决状态。确认上一阶段后，只有明确从未发送的下一阶段才可首次推进：

```sh
hypertest auth bind --resume --request-id PAIRING_REQUEST_UUID
```

完成绑定后，可在线检查现有配置、TLS 及指定项目的归档能力；此命令不会创建任务或执行测试：

```sh
hypertest doctor --profile default --project-id PROJECT_UUID --json
```

Web「CLI 授权」页可撤销指定项目 grant，撤销后服务端拒绝继续使用该权限，已接受历史保持。`hypertest auth logout --profile default` 只停用本机 profile，不等同服务端撤销；它保留凭据记录、journal、冻结请求和其他 profile，并返回未决请求 ID。授权到期后由用户显式重新绑定，无后台续签。

## 5. 全局安装并显式调用 Skill

```sh
hypertest skill install --global --host codex
```

它安装到 `${CODEX_HOME:-$HOME/.codex}/skills/hypertest-archive`，只管理归档 Skill 文件；不会修改项目 AGENTS、MCP 或 Hooks。已有自定义或被修改的同名文件会被保留并报告冲突。也可明确指定技能根目录：

```sh
hypertest skill install --directory /absolute/path/skills
```

首版自动全局安装只声明 Codex 目标；其他宿主的安装、发现和显式调用须按其实际支持情况核验。Codex Skill 元数据设置 `allow_implicit_invocation: false`；测试结束、Stop 或工具活动不会触发上传。

用户可从归档任务页复制指令，或显式输入：

```text
$hypertest-archive
请将本轮正式测试产物归档，使用 profile default。
项目ID：PROJECT_UUID
任务ID：TASK_UUID
产物范围：/absolute/path/test-results
```

需要子任务时另加 `子任务ID：SUBTASK_UUID`；省略即归档到 Task 本身。Skill 在用户批准的有限文件范围内整理 manifest，调用 CLI 并解释结果；不持有凭据、不监听聊天、不运行测试，也不自动创建任务。信息足够时直接完成已授权的上传，缺少必要目标或文件范围才询问。

## 6. Manifest 与支持的产物

manifest 是 UTF-8 JSON。`profile` 是协议标识，与 CLI 的本机连接 `--profile default` 含义不同。以下为格式示例，目标 UUID、文件路径和结果须替换为本次真实内容：

```json
{
  "profile": "local-artifact-archive/v1alpha1",
  "project_id": "00000000-0000-4000-8000-000000000001",
  "task_id": "00000000-0000-4000-8000-000000000002",
  "assets": [
    {"kind": "PLAN", "stable_key": "test-plan", "title": "测试计划", "path": "./test-plan.md"},
    {"kind": "CASE", "stable_key": "case-001", "title": "测试用例", "steps": ["本次实际设计的步骤"],
     "expected": "预期结果", "actual": "", "reported_result": "NOT_RUN"},
    {"kind": "REPORT", "stable_key": "test-report", "title": "原始测试报告", "path": "./report.txt",
     "reported_result": "UNKNOWN", "origin": {"producer": "local-agent"}}
  ]
}
```

PLAN、REPORT 读取明确文件路径的完整原始 UTF-8 正文；CASE 使用内联结构化字段。相对路径相对于 manifest 所在目录。支持文本后缀 `.md`、`.markdown`、`.txt`、`.log`、`.json`、`.xml`、`.csv`；不读取目录、通配符或远端 URL。符号链接、他人可写文件、认证/聊天目录、已识别秘密和二进制内容会被拒绝。截图、视频、压缩包尚不支持，不能静默转换或丢弃后宣称完整归档。

同一 kind/stable_key 标识持续修订的业务资产。上传为完整资产 upsert，省略已有资产不删除历史。逐资产 `origin` 可声明 provider、session、producer、引用及带时区时间；来源声明不升级为原生会话身份或独立执行证明。已知 FAIL、ERROR 等结果应如实保留；未知不补造 PASS。

每项计划/报告上限 262144 字符；每批最多 16 个 PLAN、200 个 CASE、16 个 REPORT，每用例最多 100 步；最终 JSON 正文最多 2 MiB。超限整批拒绝，不自动拆分或截断。完整字段、来源和子任务状态说明见[Skill manifest 参考](../skills/hypertest-archive/references/manifest.md)。

## 7. 上传及原请求恢复

归档到 Task 根空间：

```sh
hypertest archive --profile default --project-id PROJECT_UUID --task-id TASK_UUID \
  --manifest /absolute/path/archive-manifest.json --json
```

归档到指定子任务时，manifest 同时增加匹配的 `subtask_id`：

```sh
hypertest archive --profile default --project-id PROJECT_UUID --task-id TASK_UUID \
  --subtask-id SUBTASK_UUID --manifest /absolute/path/archive-manifest.json --json
```

Project/Task 必填；Subtask 可选。目标与 manifest 不一致会被拒绝；错误或越权 Subtask 不回退到根空间，不创建默认子任务。多个平台 profile 存在时必须明确选择；不能根据 Task ID 自动换平台。需要预览时显式增加 `--dry-run`，返回 `PREVIEW`，不创建业务提交。

CLI 先读取目标空间基线，冻结完整请求与原文，持久记录可能发送状态，再单次上传并完整读回固定接受版本。仅 `ARCHIVED` 或 `UNCHANGED` 且 `readback_complete: true` 表示本次归档已确认；返回包含 request ID、Submission ID、接受版本及任务链接。上传成功不推导整体 COMPLETED、测试 PASS、VERIFIED Evidence 或 RELEASE_READY。

```sh
hypertest status --request-id ARCHIVE_REQUEST_UUID --json
hypertest reconcile --request-id ARCHIVE_REQUEST_UUID --json
```

`status` 默认只查本地；`status --remote` 和 `reconcile` 查询原 key 并继续固定版本读回，SENT/UNKNOWN/NOT_FOUND 不重 POST。恢复时不重新读取已变化的源文件，也不创建替代任务或新 key。退出码为：0 成功或明确标注的预览，2 本地输入错误，3 明确拒绝，4 未决/读回未完成，5 配置或能力缺口。

## 8. 退出旧 MCP/Hooks 接入并保留恢复

新 CLI 可运行后，在旧接入实际所在的用户机器执行受管退出；`--directory` 是含 `installed-HOST.json` 的旧安装收据目录，不是测试产物目录：

```sh
hypertest legacy retire --directory /absolute/path/old-local-install --host codex --json
```

`--host` 支持 `codex`、`claude-code`、`deepseek-harness`（`deepseek` 为别名）。`legacy cleanup` 是 `legacy retire` 的命令别名。工具按旧收据核对自有 MCP、Hooks 和 bridge 配置，只移除匹配的受管片段；其他插件及用户修改保留。仅在私有 IPC 与运行身份匹配时停止已有本产品 runtime，不按进程名批量结束进程，不启动 daemon。旧安装事务未恢复、归属不明或片段被修改时明确报错并保留原件。成功后按返回的 `reload_required` 重载宿主配置。

旧凭据、源产物、完整快照、journal、未决 key、历史报告与安装收据均保留。需要恢复某个旧请求时，使用原私有客户端配置：

```sh
hypertest legacy reconcile --config /absolute/path/old-client.json \
  --request-id ORIGINAL_IDEMPOTENCY_KEY --json
```

这里的 request ID 是旧账本原 key，不要求新 UUID；同 key 命中多个旧 namespace 时使用 `NAMESPACE/ORIGINAL_IDEMPOTENCY_KEY` 明确选择。该入口只读取原账本、原 key 回执及固定版本，支持原 SYNC、BIND 和协作请求，不产生任何新旧 POST，不改写旧账本。旧 Web CREATE 由原 Web 管理 journal 恢复。材料不足时保留未决或不完整读回状态，不伪造完成；它不会把旧任务迁移成新的归档 Task。
