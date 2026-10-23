# HyperTest Local 实现与发行状态

## ADR-024预创建/绑定增量的状态边界

项目负责人已接受[ADR-024](architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md)：统一Cloud/Local创建入口，Local预创建同UUID的UNBOUND任务，真实root按intended actor一次绑定；新Local客户端首次产物前必须绑定明确TaskID，缺失时TASK_BINDING_REQUIRED且不POST。CREATE/BIND使用独立原key回执，旧auto根可resume但不与新草稿合并。

这是本次新增契约，不能由下面local-v0.1.0固定包、安装成功或旧三宿主矩阵推导已交付。新服务端/客户端源码、远端相关验证、真实宿主接入和发行版本分别记录；旧tag、资产摘要、原失败/FAIL保全与原生证明不重写。具体使用和兼容规则见[同步说明](CODEX_SESSION_TASK_SYNC.md#先创建任务再绑定本地父会话)。

## 2026-10-23 生产 Web 上线补记

PR #23 已合并，项目页 → 本地会话任务 → 接入本地模式已上线。实际 Web 源码为 `b27c8c14c80dce46bc21a02c83daba7070cf8292`；内部真实浏览器六条命令及已有用例 / 原始报告、外部严格 CA HTTPS 已验证。文中“待合并 / 待最终 gate”属于下方验收冻结时点；精确 image、保全、补证顺序和临时授权清理见[生产部署记录](LOCAL_WEB_PRODUCTION_DEPLOYMENT_20261023.md)。原 `local-v0.1.0` 包 / tag / 三摘要与三宿主证明保持不变；本次后续纯文档提交不代表部署新 Web 源码。


## 2026-10-23 新增真实矩阵（已通过）

`local-v0.1.0` 已公开，协调器、三宿主 Hooks/MCP、TaskSyncCore Local adapter 与固定摘要安装器已交付；首发仅 `darwin-arm64-py313`。本次直接使用原公开包，无产品 runtime 修改。Claude Code、Codex、DeepSeek harness 的用例、原始报告、真实 headless 与同源跨进程恢复必需矩阵均已独立复核通过。**DeepSeek 恢复仅指新进程的官方持久 Registry API，不是 CLI / SDK wire resume 参数，也未新增通用恢复命令。**

本次 `FAIL` 是管理同步保全 fixture，业务 SUT 为 `NOT_RUN`。Claude / Codex 原始证明中的生成时 `PENDING_INDEPENDENT_REVIEW` 保持不变，后续资格单独记录。精确流程、后端、版本与限制见[新增验收记录](LOCAL_CASE_REPORT_RESUME_ACCEPTANCE_20261023.md)及[矩阵](local-acceptance/local-matrix-20261023.json)。原 2026-10-22 R5/R6 证据、0.1.0 tag / 四资产 / manifest 和旧 MCP 发行保持历史身份；PR 合并与生产 Web 部署仍待最终 gate。

## 已公开发行（2026-10-22）

[local-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.0) 已于 `2026-10-22T12:08:14Z` 正式公开，固定源码 `874569fa566a137eba77ac4852caa6052cb04a17`；本轮只发布 `darwin-arm64-py313`。三项可信摘要、三宿主六条安装命令和限制见[正式安装入口](LOCAL_MODE_RELEASE_AND_INSTALLATION.md#已公开的-local-v010)。[公开发行记录](local-acceptance/local-v0.1.0-publication.json)保留四个资产匿名 HTTP 200 与完整字节摘要核验；公开一键 bootstrap 已在 Mac 新隔离目录完成下载、校验、安装与 Codex 配置复验；新安装的真实 MCP / 自动同步仍未观察，详见该记录。R6 原始宿主证据保持不变。

## 历史：R6 固定源码验收与发行资格（2026-10-22）

三宿主的真实 Local 接入均已完成，本提交固定 Darwin arm64 / CPython 3.13 的正式构建资格。[资格记录](local-acceptance/darwin-arm64-py313.json)绑定 R6 源码 `7aefe2878ffad4149d7e01bc18df69a6f090b0a6`、Local source digest `a5db7a7cc5058bd5fc9162c056f2b8d93c41bf18d6975879a334bbc611d56d8a` 和实装候选 wheel SHA-256 `dd88a810e43eea70bf669f7c3fde2929d77e7035b6cdf87a48c735951e47ac40`。验收与公开资产发布分别记载；实际下载命令由固定资产生成并通过受信任的 [GitHub Release](https://github.com/ZhangLiangchen/hypertest-one/releases) 分发，资产尚未出现时不使用占位 URL。

| 精确目标上的宿主 | 实际通过范围 | 限制 |
| --- | --- | --- |
| Claude Code `2.1.218` | [原生证据](local-acceptance/claude-code-native-20261022.json)：真实 SessionStart、批准 analysis.md → TEST_PLAN、原生 Hooks 自动同步、实际 MCP GET、Agent child 无独立 Task | 官方 DeepSeek Anthropic-compatible backend；DRAFT / NOT_RUN |
| Codex CLI `0.144.6` / `gpt-5.6-sol` | [原生证据](local-acceptance/codex-native-20261022.json)：同一最终父会话自动产物同步与实际 MCP GET completed；固定版本读回和 SHA 一致 | 子代理生命周期 / 404 / 无 child binding 来自另一真实 R6 父会话的独立 probe；最终父会话 3 次 spawn PreToolUse 未产生 child，不宣称这些尝试成功；DRAFT / NOT_RUN |
| DeepSeek harness CLI `0.1.5-rc.1`，组件 `0.1.5-rc.2` | [R6 SDK-profile 证据](local-acceptance/deepseek-native-20261022.json)：官方 JsonRpcLineTransport 双 turn、真实 SessionStart / PostToolUse、自动 ACK 与固定版本全页读回、实际 MCP GET、native registry child 404 | 显式批准策略 IN_PROGRESS / NOT_RUN；Stop 独立 handler 次数、headless / resume 未验收 |

本次实机为 macOS 26.5.1 / arm64 / Python 3.13.3。Linux x86_64 / CPython 3.12 仅有源码回归、固定依赖构建与离线安装证明，保留 CANDIDATE，稳定 tag 不发布该目标；其他 OS / 架构 / Python / 宿主版本未接受。`local-v*` 使用独立发行线，旧 `mcp-v*` 内容与适用范围保留。

该次 R6 历史轮次的真实产物范围仅为批准的 analysis.md → TEST_PLAN，另有实际 MCP GET；case / raw report 为 0。用例、报告与 FAIL 保全已有 ASGI / 单元回归，不能扩大为三宿主全部产物类型的原生 E2E。状态来自批准策略；Stop、上传或 ACK 不推导 COMPLETED / PASS。R5 DSH 证明保留为[独立历史](local-acceptance/deepseek-native-20261022-r5.json)，当前资格来自新的 R6 运行。

[CI #118](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39770913859) 已通过：后端 1180 passed / 21 skipped，Web 137 passed、typecheck 与 production build。R6 候选另通过隔离远端 168 项 Local / MCP / 旧客户端回归、focused Ruff、固定 29 依赖离线安装与 pip check。最终 evidence / target / 文档提交保持同一 Local source digest，另行执行发行专项与 CI。

## 历史：实现范围与初期验证记录

| 能力 | 本轮源码 | 尚未证明的范围 |
| --- | --- | --- |
| TaskSyncCore | 固定请求 / key / version、单次发送、原 key 对账、回执及固定版本完整读回；通过领域 adapter 接入 | Cloud adapter 与真实云端运行由独立接管会话负责，本地结果不代替云端验收 |
| LocalSyncCoordinator | 显式 MCP 全量请求与新 manifest 局部意图进入同一来源 writer；保留旧空值语义、原 FAIL 与精简 journal，正式冻结快照另存私有目录 | 跨终端全局排他性不由本机锁保证；服务端 owner / expected-version 检查继续有效 |
| 正式产物 manifest | 明确 Project / provider / 父会话、基线版本、set / clear、选定根目录内的计划和报告文件及 SHA-256 | 不是聊天扫描器或任意附件上传；调用者仍须审阅内容与真实来源，过滤不能保证识别所有秘密 |
| 显式提交 | `python -m hypertest.local_sync submit-manifest --config …`，仅使用私有配置选定的 manifest，同私有 IPC / coordinator | 配置与命令不证明原生宿主身份；需真实父会话、有效授权与原件读回 |
| 候选安装器 | `install`、`upgrade`、`doctor`、`rollback`、`uninstall`、`recover-install`；显式文件目标、私有备份、本包所有权合并与可恢复的多文件事务 | 不签发 grant，不安装模型 CLI / 登录；源码配置安装与独立发行 bootstrap 分开，完整发行与 OS / 宿主矩阵待验收 |
| 统一发行工具 | 固定源码 lean wheel、离线 closure、HTTPS 固定目标下载、独立 bootstrap、三摘要一键命令生成器及 draft workflow 源码已加入；接口见[发行构建说明](LOCAL_MODE_RELEASE_BUILD.md) | 本轮新增接口待冻结专项；真实公开资产、宿主验收与源码准备分别记录，不生成不存在的一键发布入口 |
| Project Web 引导 | 项目 SessionTask 区域的“接入本地模式”，中英双语，三宿主选择、私有路径、候选命令、模板与接受版本核验 | 页面不读本机配置或秘密、不验证 Project grant、不执行命令；真实交互 / 宿主配置需独立验收 |

## 安全的源码候选路径

以下保留第一阶段未发布源码路径。第二阶段新增固定摘要 HTTPS 下载、明确 workspace／artifact-source 策略、精确目标资格、独立源码冻结和正式 release gate，见[发行构建说明](LOCAL_MODE_RELEASE_BUILD.md)。下列命令保留第一阶段历史；当前三宿主 R6 实测及正式发行状态以文首记录为准。

前提：目标 Harness 已安装；操作者持有正确 Project 的既有私有 `task:sync` 配置及 token 文件。配置 / token 文件保持 `0600`，私有目录 `0700`。真实远端 API 使用 HTTPS 并校验证书，私有 CA 用已有 `ca_file`。管理员通过现有受控注册流程单独安排授权；不要运行旧 Operator-key `setup` 配对来取得 Local 管理权限，也不要把 token 放入聊天、命令参数或普通宿主配置。

在含本轮模块的已审阅源码目录创建私有 Python 3.12+ 环境，记录准确源码版本；这不是已发布安装资产：

```sh
python3 -m venv .venv-local
.venv-local/bin/python -m pip install -e '.[interactive]'
```

以下绝对路径由操作者替换为实际私有路径，`local-v0.1.0-candidate` 只作为配置收据标识，不代表 tag / release 已存在或已通过来源验证：

```sh
.venv-local/bin/python -I -m hypertest.local_sync install \
  --directory /absolute/private/hypertest-local/install \
  --harness codex \
  --host-config /absolute/path/to/.codex/config.toml \
  --client-config /absolute/private/hypertest-local/config.json \
  --version local-v0.1.0-candidate

.venv-local/bin/python -I -m hypertest.local_sync doctor \
  --directory /absolute/private/hypertest-local/install --harness codex
```

以下历史示例是显式 MCP-only 路径，不传 `--enable-hooks`；当前自动策略和正式命令接口见[发行构建说明](LOCAL_MODE_RELEASE_BUILD.md)。安装可保全合并宿主 MCP 配置，结果中的 `configuration=WRITTEN` 只说明配置写入；`reload_required=true`、`native_acceptance=NOT_OBSERVED`、`real_sync=NOT_OBSERVED` 保持独立。doctor 检查私有凭据文件存在性，不在线验证 grant，不伪造示例 Task，不以安装完成表示同步成功。

Claude Code 使用 `--harness claude-code` 和明确作用域的 MCP JSON 文件。DeepSeek 使用 `--harness deepseek-harness --dsh-home /absolute/private/dsh --profile ACTUAL_EXISTING_PROFILE`，且 `--host-config` 必须准确指向该 home 的 `profiles/ACTUAL_EXISTING_PROFILE/cordis.patch.yml`；要求该 profile 已存在。每个 host 使用自己的私有客户端配置；已有 `local_sync.host` 绑定的配置不能切换复用为另一 host，安装器会明确拒绝，不能为绕过冲突擅自签发或替换身份。DeepSeek 自动 bridge 未验收时明确拒绝启用 Hooks，MCP patch 写入也不代表原生加载或同步已经通过。以上为初期 MCP-only 示例；当前三宿主 R6 已真实通过，正式下载入口由实际 Release 分发。

安装的宿主文件、私有配置及安装收据通过带备份与提交标记的事务更新。中断后出现 `INSTALL_RECOVERY_REQUIRED` 时，保留原目录并显式恢复，不直接重复覆盖；恢复仅接受与原 before / after 摘要相符的配置，用户后续修改产生冲突时保留并停止：

```sh
.venv-local/bin/python -I -m hypertest.local_sync recover-install \
  --directory /absolute/private/hypertest-local/install
```

## 私有选择、父会话与显式同步

在既有私有配置中追加 `local_sync`，不要复制 token 内容或覆盖 actor / client / API / state_dir。项目页显示对应 Project / host 的待填写模板：

```json
{
  "local_sync": {
    "enabled": true,
    "host": "codex",
    "hooks_enabled": false,
    "project_id": "ACTUAL_AUTHORIZED_PROJECT_UUID",
    "manifest_file": "/absolute/private/hypertest-local/manifest.json",
    "allowed_roots": ["/absolute/private/approved-artifacts"]
  }
}
```

私有 manifest 使用 `hypertest.local-manifest/v1alpha1`，包含 `identity.project_id/provider/parent_session_id`、整数 `base_version`、明确 `set` / `clear` 与 `artifacts`。provider 映射为 Codex `codex`、Claude Code `claude_code`、DeepSeek `deepseek_harness`；这是本候选 adapter 的来源约定，不是宿主真实性证明。父 ID 来自真实主会话，不能使用占位 ID、child ID 或 CloudAttempt。首次创建须明确提供 title / objective / status / plan_markdown / reported_result；`TEST_PLAN` 选定文件可提供 plan_markdown。后续局部意图保留未指定字段，清除只允许显式 `clear`；既有 MCP 完整请求仍保持原语义。

使用 `hypertest_get_task` 完整读回当前版本作为基线；真正新来源才用 0。`TEST_PLAN` / `TEST_REPORT` 仅引用允许根目录内明确选择的 `.md` / `.markdown` 文件绝对路径与内容摘要；报告还需明确 key / title / reported_result。读取检查路径分量、符号链接、文件类型 / 所有者 / 大小，并经目录 FD 打开；这些保护不能替代内容及授权审阅。选取内容前人工审阅，不包含整聊天、推理、认证目录或秘密。子代理只向父会话交付正式产物。

保存配置后启动同 profile 的私有 daemon。既有 MCP 的 `stdio --autostart` 只在尚无 daemon 时启动；已有 daemon 不会因宿主重载自动重读配置。需要重载时先完成在途处理、保留未决 key 与原 journal，再显式停止该私有 daemon 并重新启动；不强退模型或用户会话。

```sh
# 仅在确认无在途请求且原 daemon 需要重载时运行 stop。
.venv-local/bin/python -I -m hypertest.interactive_client stop \
  --config /absolute/private/hypertest-local/config.json

# 在独立终端显式运行；若 MCP 已启动正确配置的 daemon，无需另起。
.venv-local/bin/python -I -m hypertest.interactive_client daemon \
  --config /absolute/private/hypertest-local/config.json
```

完成真实 manifest 后，在另一终端显式提交。该命令不依赖 Hooks，也不会偷偷启动 daemon、模型或测试：

```sh
.venv-local/bin/python -I -m hypertest.local_sync submit-manifest \
  --config /absolute/private/hypertest-local/config.json
```

原有 MCP 两工具继续可用。只有有效 ACK 与固定接受版本的全部分页原文读回完成才算本次同步确认；读取失败保留已接受状态并继续同版本读回。SENT / UNKNOWN / 失答沿原 key GET；NOT_FOUND 不允许重 POST、换 key 或另建 Task。同 checkpoint 完整确认后重复提交可返回 UNCHANGED；实质新意图先核对当前基线，不修改已经冻结的旧请求。同步状态不重写 reported PASS / FAIL，Stop / 上传成功也不推导 COMPLETED。

旧精简 journal 可能只有查询身份与原 digest，没有本轮新增的完整批准快照。兼容处理仅以原 key GET 验证回执并完整读回固定接受版本，内部记为 `LEGACY_ACCEPTED_READBACK`；不会重 POST、重建缺失原请求或将这种历史读回冒充原批准字节已比对的新 checkpoint。新格式快照丢失则明确受阻并保留原 key。

## Web 入口与验证接口

入口为 `Project → Codex 测试任务 → 接入本地模式`，既有任务表与错误重试不受影响。向导源码现按固定公开 descriptor 展示 `local-v0.1.0` 的 Mac arm64 / Python 3.13 目标与三宿主精确版本；填写已有私有授权路径后生成带可信摘要的安装命令。Hooks 默认关闭，须明确选择工作区策略；本机真实会话仍待核验，MCP 保留，首次同步需原件读回。未发布目标仍无可安装入口；页面没有无校验 `curl | sh`、Operator-key 输入或 PowerContext admin token。安装字段只含私有路径等非秘密引用；页面不持久保存这些输入，也不调用写 API；线上页面部署单独记录。

新增 `web/tests/local-mode-guide.test.cjs` 覆盖命令与私有路径构造、注入边界、三宿主 / DeepSeek 目标、未完成模板、默认关闭 Hooks、无凭据输入，以及双语 SSR 状态和现有项目入口。既有 `session-tasks.test.cjs` 仅补新组件的测试 require 映射，原断言保留。

本子任务未在本机运行 npm / 测试 / typecheck / build / browser 或真实 Agent。主控在隔离远端执行本轮验证，当前已返回的结果如下：

| 验证范围 | 实际结果 | 证明范围 |
| --- | --- | --- |
| Local / 共享核心及既有同步回归 | **102 passed，31.41s**；54 条已有 SQLAlchemy deprecation warnings | 包含 `test_task_sync_core.py`、`test_local_sync.py`、`test_local_installation.py`、`test_session_task_mcp.py`、`test_interactive_client.py`、`test_interactive_setup.py`、`test_interactive_scope.py`、`test_session_tasks.py`、`test_session_task_pages.py`；含三宿主配置 / 卸载及本轮修复回归 |
| Local manifest 跨层集成 | **1 passed，6.37s**；32 条已有 SQLAlchemy warnings | `test_local_sync_integration.py` 使用隔离 ASGI + DB + 实际 Local manifest / typed API adapter 和合成管理身份；验证多页固定版本读回、原 FAIL / 计划 / 用例 / 报告保留、partial 不丢资产及 no-op 不 POST，不调用真实 Harness 或公网 HTTPS 服务 |
| Web 单元 / SSR 测试 | **135 tests，135 passed，0 failed，0 skipped**；135,322.7 ms | 隔离 Web 基线加本轮 Local 引导与单一 Cloud 导航，不含其他会话后续新增的 Cloud 页面 |
| Web typecheck | 通过 | 上述冻结 Web 范围的类型检查 |
| Web production build | **通过，整条验证命令 exit 0**；compile 2.3 min，静态生成 5/5，优化与 traces 完成 | 同一冻结 Local overlay 与既有 Web 范围；不证明后续 Cloud 页面已构建通过 |
| 候选发行 / 离线 bootstrap 单元专项 | **10 passed，0.64s** | `test_local_release.py` 验证独立来源、固定锁与拒绝边界，不计入前述 102 项，不代替真实依赖闭包安装 |
| 真实离线依赖闭包 / fixture 安装 smoke | **通过，exit 0，`PASS_SYNTHETIC_RELEASE_MECHANICS`**；29 个 wheel，共 9,572,071 B | 实际构建器在隔离 venv 完成离线 `--no-index --no-deps` 安装、`pip check` 与 lean imports；只读 verify-only、候选 bootstrap 安装与 doctor 通过，第三方 MCP / model / comment 和私有 pending 哨兵保留，Hooks 关闭。仅使用合成 Git fixture，无平台 HTTP 请求、模型或 SUT，不证明用户仓库已有 tag / release 或真实宿主接入 |
| 本轮静态差异检查 | `git diff --check` 通过 | 无空白差异错误；不证明行为或宿主验收 |

SSR / 单元 / 类型 / 构建通过均不代表真实宿主、自动事件、在线授权、首次真实同步或完整 Cloud UI 验收通过。真实浏览器视觉 / 交互尚未验证；Impeccable 读取到 DESIGN sidecar 过期提示，本轮未扩大范围修复。

上述隔离远端验证证据保留在 `hypertest-one:/var/tmp/ht-impl-mvjb1zvp`：`local-final.log`、`release-unit.log`、`local-integration.log`、`web-final.log`、`release-smoke.log` 与 `release-smoke/result.json`。发行 smoke 的 fixture commit / tag 仅是隔离测试输入，不能作为用户仓库或公开发行身份；不在本文重标为正式版本。

验证完成后，主控核对 `hypertest.validation=ht-impl-mvjb1zvp` 标签并移除了本轮 Node、Python、PostgreSQL 三个隔离容器及专用网络；证据目录继续保留，未清理其他会话或生产资源。

## 未交付或未观察范围

三宿主 R6 原生接入与 Mac 精确目标公开发行已经分别留证；完整矩阵见文首，不能推广到其他 OS、Python 或宿主版本。公开 bootstrap 新隔离安装、Codex 配置与状态保全已通过，新安装尚未运行模型或观察真实同步；新用户机器仍需已有授权、重载与真实父会话 ACK / 固定版全读回。Windows、Linux 正式目标、全量 case / raw report 原生 E2E、DeepSeek headless / resume 与独立 Stop handler 次数仍未验收。未自动改全局技能；未实现 Memory Gateway、自动聊天 capture 或产品经验访问。Cloud 实现、共享应用注册入口与正式部署由独立所有者推进，不在本文冒称交付。

Codex 的项目 Hook trust、MCP 读工具许可和宿主重载由其标准权限流程分别处理。安装器合并配置后，需让实际项目重新加载配置并确认受信任 Hook；`hypertest_get_task` 还须具有标准读工具许可。验收中的读许可通过该工具专属 `approval_mode=approve` 的单次 CLI overlay 显式给予；沙箱与持久用户配置保持原值，其他全局 MCP 仅在本次 CLI 运行中停用。安装成功、一次独立 GET 成功或诊断调用通过均不替代同一真实父会话的自动产物 ACK / 固定版本完整读回及 child 边界证明。此前缺少原始错误的失败运行保留为失败记录，不追认根因。
