# HyperTest Local 固定版本发行、下载与校验

## 2026-10-26 接入 Skill 打包增量

新版候选将仓库 `skills/hypertest-local-task-onboarding/` 的五份文件原样放入 `hypertest/local_sync/assets/skills/hypertest-local-task-onboarding/`，并纳入 Local source digest、wheel RECORD 和 manifest。显式 `install-skill` 可安装/升级到所选 Agent 技能目录，不默认修改用户全局技能。候选 tag 的构建不携带旧 `local-v0.1.0` 验收文件，Linux/Mac 均保留 CANDIDATE；稳定版的精确源码验收要求继续生效。精确版本、发布状态与检查见[本轮交付](LOCAL_ONBOARDING_SKILL_DELIVERY_20261026.md)。后文早期“只含代码与 JSON”描述是原包范围，不覆盖此增量。

## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。

## 已公开发行（2026-10-22）

[local-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.0) 已于 `2026-10-22T12:08:14Z` 正式公开，固定源码 `874569fa566a137eba77ac4852caa6052cb04a17`；本轮只发布 `darwin-arm64-py313`。三项可信摘要、三宿主六条安装命令和限制见[正式安装入口](LOCAL_MODE_RELEASE_AND_INSTALLATION.md#已公开的-local-v010)。[公开发行记录](local-acceptance/local-v0.1.0-publication.json)保留四个资产匿名 HTTP 200 与完整字节摘要核验；公开一键 bootstrap 已在 Mac 新隔离目录完成下载、校验、安装与 Codex 配置复验；新安装的真实 MCP / 自动同步仍未观察，详见该记录。R6 原始宿主证据保持不变。

## R6 固定源码验收与发行资格（2026-10-22）

三宿主的真实 Local 接入均已完成，本提交固定 Darwin arm64 / CPython 3.13 的正式构建资格。[资格记录](local-acceptance/darwin-arm64-py313.json)绑定 R6 源码 `7aefe2878ffad4149d7e01bc18df69a6f090b0a6`、Local source digest `a5db7a7cc5058bd5fc9162c056f2b8d93c41bf18d6975879a334bbc611d56d8a` 和实装候选 wheel SHA-256 `dd88a810e43eea70bf669f7c3fde2929d77e7035b6cdf87a48c735951e47ac40`。验收与公开资产发布分别记载；实际下载命令由固定资产生成并通过受信任的 [GitHub Release](https://github.com/ZhangLiangchen/hypertest-one/releases) 分发，资产尚未出现时不使用占位 URL。

| 精确目标上的宿主 | 实际通过范围 | 限制 |
| --- | --- | --- |
| Claude Code `2.1.218` | [原生证据](local-acceptance/claude-code-native-20261022.json)：真实 SessionStart、批准 analysis.md → TEST_PLAN、原生 Hooks 自动同步、实际 MCP GET、Agent child 无独立 Task | 官方 DeepSeek Anthropic-compatible backend；DRAFT / NOT_RUN |
| Codex CLI `0.144.6` / `gpt-5.6-sol` | [原生证据](local-acceptance/codex-native-20261022.json)：同一最终父会话自动产物同步与实际 MCP GET completed；固定版本读回和 SHA 一致 | 子代理生命周期 / 404 / 无 child binding 来自另一真实 R6 父会话的独立 probe；最终父会话 3 次 spawn PreToolUse 未产生 child，不宣称这些尝试成功；DRAFT / NOT_RUN |
| DeepSeek harness CLI `0.1.5-rc.1`，组件 `0.1.5-rc.2` | [R6 SDK-profile 证据](local-acceptance/deepseek-native-20261022.json)：官方 JsonRpcLineTransport 双 turn、真实 SessionStart / PostToolUse、自动 ACK 与固定版本全页读回、实际 MCP GET、native registry child 404 | 显式批准策略 IN_PROGRESS / NOT_RUN；Stop 独立 handler 次数、headless / resume 未验收 |

本次实机为 macOS 26.5.1 / arm64 / Python 3.13.3。Linux x86_64 / CPython 3.12 仅有源码回归、固定依赖构建与离线安装证明，保留 CANDIDATE，稳定 tag 不发布该目标；其他 OS / 架构 / Python / 宿主版本未接受。`local-v*` 使用独立发行线，旧 `mcp-v*` 内容与适用范围保留。

真实产物范围仅为批准的 analysis.md → TEST_PLAN，另有实际 MCP GET；case / raw report 为 0。用例、报告与 FAIL 保全已有 ASGI / 单元回归，不能扩大为三宿主全部产物类型的原生 E2E。状态来自批准策略；Stop、上传或 ACK 不推导 COMPLETED / PASS。R5 DSH 证明保留为[独立历史](local-acceptance/deepseek-native-20261022-r5.json)，当前资格来自新的 R6 运行。

[CI #118](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39770913859) 已通过：后端 1180 passed / 21 skipped，Web 137 passed、typecheck 与 production build。R6 候选另通过隔离远端 168 项 Local / MCP / 旧客户端回归、focused Ruff、固定 29 依赖离线安装与 pip check。最终 evidence / target / 文档提交保持同一 Local source digest，另行执行发行专项与 CI。

以下第一阶段接口 / fixture 记录保留为历史，不能代替实际源码候选或真实父会话验收。当前固定下载及信任入口见后续“统一发行增量”。


日期：2026-10-22（Asia/Singapore）。本页记录实际源码接口；新增 HTTPS／正式发行能力见末尾“统一发行增量”。前面的首轮离线候选记录保留历史范围，新增接口以增量段为准。源码不表示已创建 `local-v*` tag、上传 release 或完成三个真实宿主验收。发行产品契约见[统一安装设计](LOCAL_MODE_RELEASE_AND_INSTALLATION.md)。

## 构建输入

在受权远端构建环境使用 Python 3.12+、Git、venv / pip；不在用户电脑运行构建、安装测试或模型。构建器不访问包索引、不解析浮动依赖、不调用 Git 网络操作、不创建 tag、不修改源码 checkout。

1. 准备完整源码 commit 的干净 checkout，包含 Local 的 MCP、私有客户端、TaskSyncCore、协调器、三个宿主适配、安装器和 bootstrap。tracked 和 untracked 改动都会阻止构建。
2. 独立 Local 标签形如 `local-v0.1.0-beta.1`；`--ref` 必须是完整 40 位 commit，不能是 `main` / `latest`。已存在的同名标签必须指向该 commit；正式发布前使用 `--require-tag` 强制验证。没有标签的固定 commit 只能构造 `PLANNED` 候选，构建器不会创建标签。
3. 在构建目标 OS / 架构 / Python 版本下准备离线 wheelhouse，以及完整传递依赖锁。Local 直接依赖为 `pydantic`、`httpx`、`jsonschema`、`mcp`，锁定版本必须满足该固定源码中的兼容范围。首次准备依赖可以在受控环境解析索引，但解析结果的 wheel 名称、确切版本、原始 HTTPS URL 和 SHA-256 必须固定、复核后作为输入；发行构建本身不再解析或下载。

依赖锁为 UTF-8 JSON，精确结构如下。每行必须恰好包含这五个字段，示例占位内容须替换为实际审计值：

```json
{
  "schema_version": "hypertest.local-dependency-lock/v1",
  "wheels": [
    {
      "filename": "DISTRIBUTION-EXACT_VERSION-py3-none-any.whl",
      "name": "DISTRIBUTION",
      "version": "EXACT_VERSION",
      "sha256": "LOWERCASE_SHA256_OF_THAT_WHEEL",
      "origin_url": "https://TRUSTED_PACKAGE_HOST/FIXED_WHEEL_PATH.whl"
    }
  ]
}
```

wheelhouse 只提供每个 distribution 的一个确切版本及当前目标适用的 wheel，不接受 sdist、路径穿越、秘密 URL、Cloud SDK / runtime 或平台 wheel。来源 URL 必须为没有 userinfo、query、fragment 的固定 HTTPS 地址。构建器核对每个 wheel 的实际 METADATA 身份、摘要及大小，并以隔离 venv 进行 `--no-index --no-deps` 安装、`pip check` 与 Local 模块导入；缺传递依赖或 ABI 不兼容即失败，不输出可用包。

构建命令中的变量由发布负责人预先选定：

```sh
python3.12 scripts/build-local-release.py \
  --root "$CLEAN_SOURCE_CHECKOUT" \
  --tag "$LOCAL_RELEASE_TAG" \
  --ref "$SOURCE_COMMIT" \
  --wheelhouse "$AUDITED_WHEELHOUSE" \
  --dependency-lock "$AUDITED_DEPENDENCY_LOCK" \
  --output "$EMPTY_OUTPUT_DIRECTORY"
```

有真实标签时添加 `--require-tag`。输出目录必须不存在或为空。构建与依赖验证发生在临时目录，产物只来自 `git archive` 的固定 commit；当前未提交文件不会进入 wheel。

## 发行资产与身份

产物包括独立 `hypertest_local-<version>-py3-none-any.whl`、全部锁定依赖 wheel、`install-local-release.py`、`dependencies.lock.json`、`requirements.lock`、`local-release-manifest.json`、`INSTALL.md` 与 `SHA256SUMS`。

Local wheel 仅包含 `interactive_client`、`sync_core`、`local_sync`、原 SessionTask wire schema 和允许的配置模板；不打包 Cloud SDK / runtime、API 服务、数据库模型或 Worker。wheel 自带 `hypertest/local_sync/release.json`，记录 Local 版本、源码 commit 和核心契约。Local 发行版本独立于后端 `pyproject.toml` 版本；旧 `mcp-v0.1.0` 及其 wheel / 验收记录保持原义。

manifest 固定代码组件、bootstrap / payload 大小和 SHA-256、所有依赖原始来源及版本、MCP / Task / journal / snapshot 兼容契约，以及实际构建 OS / 架构 / Python。早期 fixture 固定为 `distribution_state=CANDIDATE`、`publication=NOT_ASSERTED`，其宿主行均为 `NOT_ACCEPTED`。当前真实资格见文首 R6 记录：正式构建仅接受精确目标的三宿主已验收证据，并继续以 `publication=NOT_ASSERTED` 表示构建器不自行证明公开发布。构建成功不产生 READY、SessionTask 或测试 PASS。

## 离线验证与显式候选安装

先通过独立可信渠道取得该确切版本的 bootstrap SHA-256 和 manifest SHA-256。**在执行 bootstrap 之前核对脚本本身**；同一下载目录里的 `SHA256SUMS` 仅用于完整性自检，不能建立来源信任。此构建器不虚构公开下载地址、不自动下载 `latest`，也不声称已经提供签名发布。

`--verify-only` 只读核对可信 manifest 摘要、预选 commit / tag、全部资产、wheel 内版本与源码 provenance、依赖身份与来源：

```sh
python3.12 -I install-local-release.py \
  --manifest "$ASSET_DIRECTORY/local-release-manifest.json" \
  --trusted-manifest-sha256 "$TRUSTED_MANIFEST_SHA256" \
  --source-commit "$SOURCE_COMMIT" \
  --release-tag "$LOCAL_RELEASE_TAG" \
  --verify-only
```

受控候选试点可以去掉 `--verify-only`，显式添加 `--allow-candidate`，并提供以下参数：

```sh
--install-root "$PRIVATE_ISOLATED_INSTALL_ROOT" \
--harness codex \
--host-config "$EXISTING_HOST_CONFIGURATION" \
--client-config "$EXISTING_PRIVATE_AUTHORIZED_CLIENT_CONFIGURATION"
```

安装目标还可选 `claude-code` 或 `deepseek-harness`，每次只处理一个目标，每宿主使用独立私有 client 配置和来源 manifest。Hooks 默认关闭；`--hook-config`、`--enable-hooks`、`--harness-version`、`--dsh-home`、`--profile` 仅按明确选项传给本包安装器，不代表 DeepSeek 自动触发已支持。

bootstrap 首先检查既有私有配置、私有授权文件与 HTTPS URL；缺少授权明确 BLOCKED，不签发 grant、不索取 Operator key、不运行旧 `setup`、不复制模型登录。凭据只读取验证权限和存在性，不写入参数、普通回执或日志。私有授权文件存在不表示服务端已验证 scope。

payload 先校验并复制到隔离私有目录，再离线安装到带 tag / manifest 摘要的独立 venv，完成 `pip check` 后才修改指定宿主配置。安装目录与既有 client state 必须分开，不清空、迁移或重放 pending / SENT / UNKNOWN journal。不启动 Agent、模型、SUT、CI、测试或历史上传；不修改用户默认技能。

配置写入后按实际宿主要求重载，再运行安装器 `doctor`；它默认只读。必须另外证明真实父会话身份、有效 ACK 和固定接受版本的完整读回，才能称该宿主同步验收通过。

## 中断、升级与卸载

bootstrap 未完成的隔离 venv 保留用于人工核对，不自动删除或复用未知半成品。宿主配置多文件事务由本包安装器管理：`recover-install --directory <install-root>/host-installation` 仅在目标文件仍匹配事务已知字节时回滚；用户后续变更会阻止覆盖并保留材料。

升级、回退和卸载继续通过安装器处理本包拥有的片段；保留原 client 身份、私有 state、冻结请求、旧 key、用户会话和其他 MCP / Hooks。未知平台写仅查询原 key，不能通过升级、删除目录或另建身份绕过。回退前必须评审 journal / snapshot 兼容性，不能仅凭较旧标签就承诺安全降级。

隔离 Git fixture 的构建 / 安装 smoke 只证明脚本与依赖闭包，不证明用户当前未提交代码已成为正式 release，也不代替三个宿主的真实会话验收。

## 固定下载与正式验收 gate（2026-10-22）

本节记录构建机制与发布约束，保留初始开发时序；`local-v0.1.0` 的实际公开状态、摘要与安装入口见文首。流程保留离线路径，并提供固定版本 HTTPS 下载与正式验收 gate。先按[Local 独立源码冻结](LOCAL_RELEASE_SOURCE_FREEZE.md)准备隔离分支 `codex/local-mode-release-v0.1.0`，不从整个 dirty tree 直接发布、不捎带 Cloud 实现。准备器不 commit／tag／push，后续由主控审阅后串行执行。

### Python／目标与固定依赖

构建器及 bootstrap 精确识别 CPython **3.12／3.13**、macOS／Linux、x86_64／arm64；wheelhouse 不跨 Python minor 复用。`scripts/local-release-targets.json` 固定精确目标及发布资格，初始登记 `linux-x86_64-py312`（`ubuntu-24.04`）和 `darwin-arm64-py313`（`macos-15`），执行时核对实际 OS／架构。标签依据 [GitHub 官方 runner 列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)，其他可表达组合未因此获得支持或验收。现有 Mac Python 3.13 可使用其精确目标包，无需更改系统 Python。

`scripts/local-release-dependencies.json` 固定 29 个闭包版本和 63 个 CPython／平台 wheel 的来源 URL／SHA-256，按上一轮验证的 Linux 闭包及各确切版本的官方 PyPI JSON 核对。准备器不查 latest、不解析传递依赖或构建 sdist：

```sh
python scripts/prepare-local-dependencies.py --output "$EMPTY_DEPENDENCY_DIRECTORY"
```

它使用 `pip download --no-deps --only-binary=:all: --require-hashes`，逐字节核对后产生 `wheelhouse/` 和 `dependencies.lock.json`。构建器继续按前述接口使用这些固定输入离线安装、`pip check` 和 lean imports；未知文件、缺 closure、ABI／摘要／身份冲突均受阻。

Local wheel 除 `.py` 外也包含固定 `.mjs/.js/.cjs` 包内代码。DeepSeek `deepseek_root_bridge.mjs` 为必需资产，在 manifest `source_assets` 独立固定 SHA-256；不从运行时临时下载未固定桥代码。Cloud SDK／Worker／平台服务不进入统一 Local 包。

### 真实验收与正式版本

默认仍是 `CANDIDATE`／`NOT_ACCEPTED`。正式构建增加 `--release --acceptance-file docs/local-acceptance/TARGET_ID.json`；文件必须在固定源码 commit 内，使用 `hypertest.local-host-acceptance/v1`，绑定 `release_tag`、确切 `target.system/machine/python` 和 `local_source_sha256`。

`local_source_sha256` 对实际分发的 Local 源码、模板、JS 桥、bootstrap、pyproject 兼容约束、固定依赖 catalog、build／prepare／command／sourcefreeze／target-plan 入口及独立 workflow 的路径／字节形成稳定摘要。它不含 acceptance 文件和 target publication／evidence 配置，避免写入真实证据时出现自引用；更换依赖或入口代码则必须重新验收。三个 host 分别记录真实 `versions`、`mcp`／`automatic_trigger`／`native_acceptance`、非秘密 `evidence_refs`。标为 `ACCEPTED` 时必须同时有实际 MCP／自动事件，及 `sync_proof=ACK_AND_FIXED_VERSION_FULL_READBACK`。正式 `RELEASE` 必须已有匹配的真实 tag、且三个 host 全部接受；每个目标分别验收。缺证据可继续构建明确的 prerelease 候选，不能升级正式支持。

### 目标包与可信一键命令

每个目标输出 `hypertest-local-vVERSION-TARGET_ID.zip`，包含原离线资产。`scripts/local-release-commands.py --bundles "$BUNDLE_DIRECTORY" --output "$NOTES_DIRECTORY"` 生成 `local-install-catalog.json` 和 `LOCAL_INSTALL.md`；所有目标必须同 commit／tag／bootstrap，目标互异。

生成的一键命令使用现有 Python 的 `-I -c` 隔离入口，避免 cwd／PYTHONPATH 影子模块绕过标准库摘要校验，经固定 release HTTPS URL 取得 bootstrap，限制响应大小并核对**预先可信的 bootstrap SHA-256 后才执行**；随后 bootstrap 固定 bundle SHA-256、manifest SHA-256、完整 commit 和 tag。网络参数为 `--bundle-url "$FIXED_TARGET_BUNDLE_URL" --trusted-bundle-sha256 "$TRUSTED_BUNDLE_SHA256"`，替代离线 `--manifest`。直接执行已验证脚本同样使用 `python -I install-local-release.py`。脚本拒绝其他仓库、latest、错误本机 target、不可信 HTTPS redirect channel、超大／非平坦／非常规 ZIP 资产，再共用逐资产验证。

命令及三个摘要须从独立可信渠道审阅／分发。同一下载目录的 SHA256SUMS 只证明内部完整性，不建立来源信任；当前使用明示的 HTTPS＋外部固定摘要方式，不宣称已有代码签名。公开命令只在真实资产发布后交付，不存在未校验 `curl | sh`。

### 一键显式 Hooks 策略

安装继续要求既有私有 Project 授权、每个宿主独立 client 配置与安装根，不签发 grant／索取 Operator key／复制模型登录。默认 Hooks 关闭；完整自动命令需 `--enable-hooks --harness-version EXACT_ACCEPTED_VERSION`，并互斥选择 `--workspace /absolute/approved/test-workspace` 或 `--artifact-source /absolute/private/approved-policy.json`。

workspace 策略选择其 `analysis.md`、初始 DRAFT／NOT_RUN，并由真实 SessionStart 创建独立父会话产物目录；私有 JSON 策略须 `0600`，一次性读入原私有 client config。缺策略时在安装变更前受阻；已有静态 manifest 转自动策略须明确迁移。Claude Code／Codex 明确选择 `--hook-config`；DeepSeek 自动模式使用 `--event-bridge native-root --dsh-home ... --profile ...`，不写无效 Hook JSON 配置。该桥校验官方 registry 的真实根／子会话关系，只让根会话写父任务。

命令生成器仅对已接受的精确宿主版本生成自动命令；正式 bootstrap 再核对所选版本。安装完成仍是当前机器需 reload／真实同步未观察；须另外验证真实父来源、实际事件、ACK 与固定接受版本完整读回。Stop／上传／工具成功不代表 COMPLETED 或 PASS，不扫描聊天／推理／raw tool payload。

安装器对实际选定宿主执行有界 `--version` 探测并核对版本，可用 `--harness-binary /absolute/existing/host-cli` 明确已有 binary；不安装或替换模型 CLI。正式 MCP／Hook／daemon 均使用 `python -I -m`，隔离 cwd／PYTHONPATH／PYTHONHOME，不继承模型秘密给私有同步进程。

动态 source 队列满、断网或未知请求可通过包内 `drain-source --config PRIVATE_CONFIG --session-id EXISTING_REAL_BOUND_PARENT_ID` 显式恢复，只处理已真实绑定来源，不伪造 Hook／新 Task／新 key。配置中的原 journal、冻结请求和未知 key 必须保留；不能通过重装绕过。

### Draft 与串行公开

独立 `.github/workflows/local-release.yml` 仅响应 `local-v*` tag。`plan-local-release.py` 在稳定 tag 只选择目标清单中明确为 RELEASE、且存在同 tag／target 三宿主证据的目标；没有任何此类目标则失败。已验 Mac 可独立正式发布，只有单元／离线验证的 Linux 不会混入正式矩阵，也不阻塞已验目标；候选目标只进入明确 prerelease 构建。

选定目标下载固定依赖并离线构建后，只创建 GitHub **draft**；正式构建再次绑定 source SHA／MCP／实际事件／ACK 全量读回 gate，不只相信清单标记。所有资产不覆盖，不改变旧 MCP latest。

发布负责人核对 draft 的 commit、目标、三宿主证据、摘要与来源后串行公开。没有业务服务部署／数据库迁移。bootstrap 半成品与未知账本保留；配置事务恢复、升级／回退／卸载仍遵循前述保全规则，UNKNOWN 只 GET 原 key。

Codex 的项目 Hook trust、MCP 读工具许可和宿主重载由其标准权限流程分别处理。安装器合并配置后，需让实际项目重新加载配置并确认受信任 Hook；`hypertest_get_task` 还须具有标准读工具许可。验收中的读许可通过该工具专属 `approval_mode=approve` 的单次 CLI overlay 显式给予；沙箱与持久用户配置保持原值，其他全局 MCP 仅在本次 CLI 运行中停用。安装成功、一次独立 GET 成功或诊断调用通过均不替代同一真实父会话的自动产物 ACK / 固定版本完整读回及 child 边界证明。此前缺少原始错误的失败运行保留为失败记录，不追认根因。
