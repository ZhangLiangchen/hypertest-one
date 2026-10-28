# HyperTest CLI 授权与全局使用指南

更新：2026-10-27。**[cli-v0.1.1 已公开](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.1)，固定源 Git 为 `01b6d1ebcd64326808771ed06ac1166b98cceb6c`。公开下载摘要、Linux/Python 3.13 包安装与 Skill 安装已核验。stable_key 修复、发行与 Web 部署分别记录在[本轮交付](CLI_STABLE_KEY_FIX_DELIVERY_20261027.md)，本机升级与未决读回仍需在原机器完成。** 架构见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)，任务拆分见[开发计划](LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)。

## 1. 一次绑定，按需归档

Web 全局「CLI 授权」页位于 `/cli-authorizations`，提供安装与绑定指引、配对确认、客户端与项目折叠列表、添加项目和撤销入口。完成一次用户级绑定后，同一电脑、同一操作系统用户下的终端和 Agent 可从任意目录复用 profile，不按仓库或会话重复绑定。

profile 固定 server、client 和 uploader actor，只能访问网页明确批准的 Project。平台在首次批准时，为当前管理身份自动建立专用 CLI 上传身份；同一管理身份批准其他设备时复用该上传身份，各设备仍分别绑定并取得明确的项目授权。网页不再列出旧 Local 或验收身份供选择。每次上传仍须填写 Project ID、Task ID；Subtask ID 可选，不从 profile、当前目录或上次操作推导。

测试期间无需运行 CLI，也不要求提前创建平台任务。完成测试后，用户在 Web 选择项目并创建或选择归档 Task，需要分组时再创建 Subtask，然后显式调用 Skill 或 CLI。命令执行完毕即退出，没有 MCP、Hooks、daemon、localhost callback、后台同步或自动续签。

## 2. 把安装 Prompt 交给本地 Agent（推荐）

HyperTest CLI 面向 Agent 使用。用户无需手动下载文件或逐条拼装命令：打开 HyperTest One 的「CLI 授权」页，复制安装 Prompt，粘贴到本机 Agent 会话执行。页面 Prompt 带入本部署 CLI 可连接的 HTTPS 地址与公开 CA 证书：地址优先取 Web 配置 `HYPERTEST_CLI_SERVER_ORIGIN`；未配置时仅在页面本身经 HTTPS 打开时复用站点地址；两者都不可用时生成不含服务器地址的通用 Prompt（由 Agent 再询问实际地址与 CA），不会把普通 HTTP 页面地址当成 CLI 服务器，也不会因此报错。CA 证书来自 `HYPERTEST_CLI_CA_FILE`，只包含公开证书、不含私钥。从项目入口进入时同时带入 Project ID，用于预选授权项目。项目预选不授予权限，也不是后续上传的默认目标。

`HYPERTEST_CLI_SERVER_ORIGIN` 与 `HYPERTEST_CLI_CA_FILE` 是可选部署配置：前者必须是 CLI 实际连接的规范 HTTPS origin（`https://host[:port]`，不含用户信息、路径、查询或 fragment），后者必须是公开 CA 证书的绝对路径。它们不同于浏览器站点的 `HYPERTEST_ARCHIVE_WEB_ORIGIN`。当 Web 只经 WireGuard 以普通 HTTP 提供（例如本机测试部署 `http://10.66.66.3:3000`）而 CLI API 位于受限 HTTPS 入口时，必须配置这两项，页面才能生成包含服务器地址、绑定命令与 CA 的 Prompt。配置值只会作为公开地址与公开证书进入浏览器，不会泄露 Operator key、内部 socket 或其他配置；未配置或配置无效时只退化为通用 Prompt。

没有打开平台页面时，可从下列入口复制完整 Prompt：

- [中文安装 Prompt](cli-install-prompts/hypertest-cli-install-prompt.zh-CN.txt) · [English installation prompt](cli-install-prompts/hypertest-cli-install-prompt.en.txt)
- [cli-v0.1.1 GitHub Release](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.1)：发行说明提供完整中文 Prompt，附件提供中英文文本。

通用发行 Prompt 不绑定某台服务器。Agent 先完成 CLI 与适用 Skill 的安装，再询问实际 HyperTest One HTTPS 地址以发起绑定；已有明确地址或有效绑定时复用，不猜测域名或项目。若会话运行在远程服务器/容器，应先明确实际安装目标，不能把远端安装称为本机安装。

Agent 根据 Prompt 完成以下操作：

1. 检查操作系统、Python ≥3.12、现有命令与受管安装，使用固定 `cli-v0.1.1` 的下载地址；分别核对安装器和 CLI 包的 SHA256 后执行安装。不会跟随仓库 Latest 安装旧 `local-v*` 包。
2. 在当前用户目录安装 `hypertest` 并处理 PATH。保留旧版本、私有 profile、journal、未决请求、非受管命令和被修改的文件；冲突时报告具体位置，不强制覆盖。
3. 安装 `hypertest-archive` Skill。Codex 使用 `hypertest skill install --global --host codex`；其他宿主先核实其技能目录，再用显式 `--directory`，不猜测目录或声明已验证发现能力。
4. 读取安全元数据，复用 server/身份匹配的已绑定 profile；需要绑定时发起短时配对，显示授权地址与短码，由用户在网页核对短码、客户端、项目和期限并确认。上传身份由平台自动关联。Agent 不代替用户批准，也不要求复制 token 或 Operator key。
5. 检查版本、Skill 安装结果与绑定状态，报告已完成项和待用户处理项。安装过程不创建测试任务、不执行测试、不上传产物，也不安装 MCP、Hooks、bridge 或后台同步进程。

网页批准尚未完成时，Agent 应明确报告“已安装，待网页授权”，不能宣称已绑定。配对出现 SENT/UNKNOWN/失答时保留原 request ID，按第 4 节查询/恢复；不得换 key 重新绑定。已有旧 Local 配置的清理由用户单独发起，方法见第 8 节。

### 从 0.1.0 升级及历史请求

0.1.0 存在资产 `stable_key` 被时间字段循环覆盖为 `report_created_at` 的缺陷：多个同类型资产可能报 `DUPLICATE_ASSET_KEY`，单资产也可能以错误标识提交。请按当前安装 Prompt 或下方手动命令升级到 0.1.1；安装 Prompt 已不再描述旧版本升级特例，已经临时修补旧 pyz 的机器同样直接安装固定版本。

安装器将新版放入独立的 `releases/0.1.1/` 并更新收据匹配的受管启动命令；旧 `releases/0.1.0/`、临时修补包和 `before-stable-key-fix` 备份保留。非默认受管安装复用原安装目录与命令目录，不创建另一套不明确的启动入口。无需重新授权；已有 profile、CA、收据及 journal 继续使用。若启动命令或目标新版目录存在修改，保留冲突并报告，不强制覆盖。

升级不改写旧请求正文/key，不自动重传或重命名服务端历史资产。对已接受但完整读回中断的提交，后续在原 CLI 状态目录中执行 `hypertest reconcile --request-id 原请求ID --json`；保持原 profile 和可信 CA，需指定 CA 时每条命令显式设置 `SSL_CERT_FILE`。只有固定接受版本完整读回核对后才能确认成功；历史错误 key 的修正需单独核查，不能通过升级自动推定原始标识。

### 手动安装或固定版本升级

以下保留给需要自行操作或排查的用户；页面中的手动命令与 Prompt 使用同一份发行元数据。

发行包为无第三方 Python 依赖的 `hypertest-cli-0.1.1.pyz`，附 release manifest 与独立安装器 `install-cli-release.py`。运行要求为 **Linux 或 macOS、Python ≥3.12**。本轮已实测 Linux/Python 3.13 的合成包安装、命令执行与 Skill 安装；macOS 尚未实际验收，不据此宣称已通过。

从「CLI 授权」页或 [cli-v0.1.1 发行记录](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.1)下载 CLI 包和安装器到同一目录。
先核验安装器 SHA256 为 `20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95`，再运行下列命令（`python3` 需为 3.12 或更高版本）。网页的手动安装入口还提供先校验安装器、再执行安装的一条命令。

```sh
python3 install-cli-release.py \
  --artifact ./hypertest-cli-0.1.1.pyz \
  --sha256 6b258850b14ece41a5489f995e3ca832ea673b575b4859b2649b5992444ad735 --version 0.1.1
```

安装器核验实际包字节和版本，默认将版本文件保存在 `~/.local/share/hypertest-cli/releases/0.1.1/`，在 `~/.local/bin/hypertest` 创建使用当前 Python 的启动入口，并写入受管安装收据。如目录已有非本工具拥有或被修改的命令，保留原件并报冲突。可用 `--bin-dir PATH --install-dir PRIVATE_PATH` 选择位置；安装目录须由当前用户拥有且权限为 `0700`。

将 `~/.local/bin` 加入当前用户 PATH，使终端及其启动的 Agent 可使用：

```sh
export PATH="$HOME/.local/bin:$PATH"
hypertest --version
```

升级时下载新固定版本及对应摘要，重复安装命令并更换版本参数；原版本、授权配置、journal 和未决请求保留。安装器本身只安装 CLI，不配置宿主 MCP/Hooks，也不绑定或签发授权。安装 Prompt 会继续安装适用 Skill 并引导配对，授权仍由用户在网页确认。既有旧 Local 接入的显式退出见第 8 节。

## 3. 一条命令启动绑定，在 Web 确认一次

安装 Prompt 会在 CLI 就绪后发起这一步；已有匹配且可用的 profile 时直接复用。需要单独绑定时，从「CLI 授权」页的手动入口复制服务器专属命令，或将以下地址替换为实际 HTTPS 服务地址（本机测试部署为外部设备经 WireGuard 使用的 `https://10.66.66.3:18444`）：

```sh
hypertest auth bind --server https://YOUR_HYPERTEST_HOST --profile default
```

可选 `--project-id PROJECT_UUID` 只预选项目，不表示已获得权限。无浏览器的终端可加 `--no-browser`，手动打开终端显示的同一 URL；不要复制凭据。命令最多等待 600 秒，可用 `--wait-seconds 0` 仅发起配对并退出等待。

正常流程：

1. CLI 在用户私有目录预存请求 ID、原操作 key、credential secret 和独立 verifier，发起配对后显示短码和网页地址。
2. 用户通过既有 Web 访问控制进入授权页，核对短码和客户端，明确项目 allowlist 和 1–90 天有效期，确认 `archive:read`、`archive:write` 两项权限。无需选择历史上传身份；平台按当前管理身份建立或复用专用 CLI 上传身份。
3. 用户在网页确认一次；CLI 在命令存活期间查询批准结果，兑换固定授权，核对原 key 回执及当前授权状态，原子保存 profile 后退出。

默认用户数据目录为 `~/.hypertest-cli`；它保存私有 profile、配对记录、冻结请求和归档 journal，文件权限为 `0600`。`HYPERTEST_CLI_HOME` 可显式选择另一私有目录，但切换目录不会迁移原记录。不要让 Skill 读取这些文件，也不要把它们加入待上传目录。

绑定命令和网页 URL 不含长期 token、verifier 或 Operator key。短码仅用于核对，不是查询或兑换凭证。profile 可合并同 server/client/actor 下新获准的项目；不同身份的同名 profile 会被拒绝覆盖，应选用新 profile 名。绑定不会获得旧 `task:sync`、Cloud、Memory 或 Operator 权限。

已批准或已绑定的旧请求继续使用原上传身份恢复，不自动迁移 profile、grant 或任务 owner。历史身份从本页的选择入口退出，但其任务、报告和回执保留。新授权也不会自动接管旧身份拥有的任务；任务创建页仍只列出该项目具有有效归档授权的上传者，任务 owner 与客户端授权分别管理。专用上传身份或客户端被撤销时，新的批准会被拒绝，不自动换一个身份绕过撤销。

配对窗口为 10 分钟，与所批准 grant 的有效期分开。过期、拒绝、撤销或失答不会自动触发新的绑定或扩权。

CLI 使用 Python `ssl.create_default_context` 校验 HTTPS，只接受 `https://` 服务器地址，没有 HTTP 或 `--insecure` 选项。若服务使用私有 CA，应将该公开 CA 证书保存为仅当前用户可读的文件，并在每条 CLI 命令（含 `doctor`、`archive`、`reconcile`）前显式设置 `SSL_CERT_FILE=/absolute/path/trusted-ca.pem`，保持证书、主机名和有效期校验；文件只放公开 CA 证书，不放私钥。授权页的安装 Prompt 会带入本部署的 CLI 地址与公开 CA，外部设备按 Prompt 操作即可，无需手工拼装。

当前测试环境是本 Mac 上的 `hypertest-mac` 容器栈。CLI 入口 `https://10.66.66.3:18444` 绑定 WireGuard 地址，供外部设备经 WireGuard 访问；同一入口仍保留回环 `https://localhost:18444` 供历史本机 profile 使用。证书由本机私有 CA `~/.local/share/hypertest-mac/bff/ca.crt`（CN=`HyperTest Mac Local CA`）签发，SAN 同时含 `10.66.66.3` 与 `localhost`，叶子证书带 Subject/Authority Key Identifier 与 critical basicConstraints，可通过 Python 3.13+ 默认的严格 X.509 校验；证书与 CA 都不入库、不进入系统信任库。外部设备使用安装 Prompt 中保存的 CA 文件即可，手写命令示例（以 Prompt 实际生成的路径为准）：

```sh
SSL_CERT_FILE="$HOME/.hypertest-cli/ca/hypertest-one.crt" hypertest doctor --profile <profile> --json
```

安装 CLI 本身不会自动把该 CA 加入操作系统信任。2026-10-27 远端部署的 HyperTest One Connector CA 只保留在[历史记录](CLI_TLS_TRUST_20261027.md)，其主机和 CA 路径已不存在。

### 为已绑定的 CLI 添加项目

平台新增项目后，既有 CLI 不会自动获得该项目权限。在「CLI 授权」页找到目标客户端，点击「添加项目」，选择尚未拥有有效授权的项目，将生成的授权 Prompt 复制给该电脑上的 Agent。页面按客户端展开项目，同名但身份不同的客户端分开显示；同一项目的多次授权记录保留各自状态和撤销入口。

Agent 按以下顺序完成增量授权：

1. 用 `hypertest profile show --json` 读取安全元数据，按 Prompt 中的服务器、客户端 ID 和上传身份匹配既存 profile。CLI 输出的 `client_id` 对应网页的 `client_instance_id`。客户端名称仅用于辨认，不能代替身份匹配；没有匹配项或有多个匹配项时先说明情况，不猜测使用 `default` 或新建替代客户端。
2. 复用匹配的 profile、私有数据目录和既有 CA 信任配置，为此次明确新增项目发起新配对。`--project-id` 只预选本次项目，仍需网页批准：

   ```sh
   hypertest auth bind --server https://YOUR_HYPERTEST_HOST \
     --profile EXISTING_PROFILE --project-id NEW_PROJECT_UUID
   ```

3. 用户打开此次授权地址，核对短码、客户端与待新增项目，再批准权限和期限。复制 Prompt 或选择项目本身不会生效；Agent 不代替用户点击批准。
4. CLI 完成兑换后，将新项目 grant 追加到同一 profile，保留原有项目授权。如命令已退出，按此次原 request ID 执行 `hypertest auth bind --resume --request-id PAIRING_REQUEST_UUID`，不再创建替代配对；失答或 UNKNOWN 继续遵守第 4 节的原 key 恢复规则。
5. 用 `hypertest doctor --profile EXISTING_PROFILE --project-id NEW_PROJECT_UUID --json` 在线检查新增项目权限，报告结果。

这个流程无需重新安装 CLI、退出原 profile 或撤销已有授权。它创建独立的新项目授权，不修改此前批准单的项目范围或期限。已撤销或到期的项目可以在用户明确选择后重新配对授权；客户端或上传身份本身被撤销时，平台仍会拒绝，不能以换身份绕过。若旧 profile 的上传身份与当前平台自动关联身份不同，应报告 `PROFILE_IDENTITY_CONFLICT`，保留原 profile 和请求，不自动迁移。

完成配对后，页面以客户端名称及绿色「已绑定」状态显示结果，配对详情可折叠查看。该状态描述本次配对完成；项目的当前有效性仍以各项授权状态和期限为准。

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

Web「CLI 授权」页展开客户端与项目后，可撤销指定 grant，撤销后服务端拒绝继续使用该 grant，已接受历史保持。同一项目如有多条有效授权，撤销其中一条不代表其他授权同时撤销；完整停止该客户端对项目的访问，需要逐条撤销该项目的有效授权。`hypertest auth logout --profile default` 只停用本机 profile，不等同服务端撤销；它保留凭据记录、journal、冻结请求和其他 profile，并返回未决请求 ID。授权到期后由用户显式重新绑定，无后台续签。

## 5. 全局安装并显式调用 Skill

安装 Prompt 已包含适用宿主的 Skill 安装；以下命令可用于单独安装或检查。

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

### 从页面复制归档 Prompt

创建测试任务页选择「本地归档」后，下方提供「复制归档模板」和折叠全文。创建前模板说明任务尚未指定，Agent 只能使用用户已明确选择的已有任务；创建成功后跳转任务页，「上传目标」中可直接复制已填真实 Project ID、Task ID 的归档 Prompt。选择子任务时加入对应 Subtask ID，选择任务根空间时省略子任务。

直接将 Prompt 粘贴到执行本次测试的 Agent 会话。Prompt 明确授权 Agent 在本次测试上下文和相关输出目录内整理已生成的计划、用例与报告，自行解析绝对路径和有限文件清单；默认排除凭据、聊天/推理、缓存、依赖及无关文件。Agent 使用 CLI 安全元数据匹配服务器、项目与上传身份，复用既有 active profile 和受信 TLS/CA 配置，不要求用户手填路径、Profile 或 CA 占位。平台自动填写当前 HTTPS 地址，不固定个人 Mac 路径或假定 default profile。

Agent 列出解析后的目标和清单后直接执行已授权上传，无需二次批准。只有多项测试无法区分、多个身份匹配且用户未指定、缺少受信 CA、明确任务目标或权限时，才询问必要信息或报告阻塞；不能扫描整个用户目录、猜测最近任务、自动配对或扩大授权。当前输出目录检查不等于上传整仓，最终 manifest 必须是确定的有限清单。复制动作本身不调用 CLI、不创建任务或上传文件；剪贴板不可用时仍可展开全文手动复制。

模板固定要求先只读核权限、所有权与目标，保留原件、凭据、回执和 journal，UNKNOWN 只查原请求；报告服务端确认结果及失败/未确认项。上传成功不代表测试 PASS 或任务完成。模板由 `web/lib/archive.ts` 统一生成中英文内容。

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

## 8. 退出旧 MCP/Hooks 接入

新 CLI 可运行后，在旧接入实际所在的用户机器执行受管退出；`--directory` 是含 `installed-HOST.json` 的旧安装收据目录，不是测试产物目录：

```sh
hypertest legacy retire --directory /absolute/path/old-local-install --host codex --json
```

`--host` 支持 `codex`、`claude-code`、`deepseek-harness`（`deepseek` 为别名）。`legacy cleanup` 是 `legacy retire` 的命令别名。工具按旧收据核对自有 MCP、Hooks 和 bridge 配置，只移除匹配的受管片段；其他插件及用户修改保留。仅在私有 IPC 与运行身份匹配时停止已有本产品 runtime，不按进程名批量结束进程，不启动 daemon。旧安装事务未恢复、归属不明或片段被修改时明确报错并保留原件。成功后按返回的 `reload_required` 重载宿主配置。

按 [ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md)，旧 SessionTask 接口与数据将在对应迁移和部署后退出；旧 Web CREATE journal 和旧 SessionTask 原 key 查询不再是当前恢复路径。`cli-v0.1.1` 发行包仍含历史 `legacy reconcile` 命令；服务端退休后该命令不再能查询旧任务。本仓库后续 CLI 源码移除该命令，不代表已发布包已更新。保留当前归档请求的 `hypertest reconcile`：它与旧 SessionTask 恢复不同。无论旧记录是否可查，都不能推定未知外部操作未执行或自动重发。
