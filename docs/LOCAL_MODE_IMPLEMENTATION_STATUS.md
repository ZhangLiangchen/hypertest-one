# HyperTest Local 源码候选实现

日期：2026-10-22，Asia/Singapore。本文记录本轮 Local / 共享同步源码的范围，不将设计、源码、发行、部署与真实宿主验收合并成一个完成状态。现有 [ADR-018 会话同步操作](CODEX_SESSION_TASK_SYNC.md)继续保留。[统一发行设计](LOCAL_MODE_RELEASE_AND_INSTALLATION.md)、[L0–L4 计划](LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md)与 [ADR-020](architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md) / [ADR-021](architecture/ADR-021_SHARED_TASK_SYNC_CORE.md)中的全量交付承诺仍需分项验收。

## 当前范围

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

以下保留第一阶段未发布源码路径。第二阶段新增固定摘要 HTTPS 下载、明确 workspace／artifact-source 策略、精确目标资格、独立源码冻结和正式 release gate，见[发行构建说明](LOCAL_MODE_RELEASE_BUILD.md)。当前并未据此预写三个真实宿主的验收状态；各宿主最终证据由主控完成并读回后记录。

前提：目标 Harness 已安装；操作者持有正确 Project 的既有私有 `task:sync` 配置及 token 文件。配置 / token 文件保持 `0600`，私有目录 `0700`。真实远端 API 使用 HTTPS 并校验证书，私有 CA 用已有 `ca_file`。管理员通过现有受控注册流程单独安排授权；不要运行旧 Operator-key `setup` 配对来取得 Local 管理权限，也不要把 token 放入聊天、命令参数或普通宿主配置。

在含本轮模块的已审阅源码目录创建私有 Python 3.12+ 环境，记录准确源码版本；这不是已发布安装资产：

```sh
python3 -m venv .venv-local
.venv-local/bin/python -m pip install -e '.[interactive]'
```

以下绝对路径由操作者替换为实际私有路径，`local-v0.1.0-candidate` 只作为配置收据标识，不代表 tag / release 已存在或已通过来源验证：

```sh
.venv-local/bin/python -m hypertest.local_sync install \
  --directory /absolute/private/hypertest-local/install \
  --harness codex \
  --host-config /absolute/path/to/.codex/config.toml \
  --client-config /absolute/private/hypertest-local/config.json \
  --version local-v0.1.0-candidate

.venv-local/bin/python -m hypertest.local_sync doctor \
  --directory /absolute/private/hypertest-local/install --harness codex
```

当前不传 `--enable-hooks`。安装可保全合并宿主 MCP 配置，结果中的 `configuration=WRITTEN` 只说明配置写入；`reload_required=true`、`native_acceptance=NOT_OBSERVED`、`real_sync=NOT_OBSERVED` 保持独立。doctor 检查私有凭据文件存在性，不在线验证 grant，不伪造示例 Task，不以安装完成表示同步成功。

Claude Code 使用 `--harness claude-code` 和明确作用域的 MCP JSON 文件。DeepSeek 使用 `--harness deepseek-harness --dsh-home /absolute/private/dsh --profile ACTUAL_EXISTING_PROFILE`，且 `--host-config` 必须准确指向该 home 的 `profiles/ACTUAL_EXISTING_PROFILE/cordis.patch.yml`；要求该 profile 已存在。每个 host 使用自己的私有客户端配置；已有 `local_sync.host` 绑定的配置不能切换复用为另一 host，安装器会明确拒绝，不能为绕过冲突擅自签发或替换身份。DeepSeek 自动 bridge 未验收时明确拒绝启用 Hooks，MCP patch 写入也不代表原生加载或同步已经通过。三宿主均没有本轮真实父会话验收结果，不显示 READY。

安装的宿主文件、私有配置及安装收据通过带备份与提交标记的事务更新。中断后出现 `INSTALL_RECOVERY_REQUIRED` 时，保留原目录并显式恢复，不直接重复覆盖；恢复仅接受与原 before / after 摘要相符的配置，用户后续修改产生冲突时保留并停止：

```sh
.venv-local/bin/python -m hypertest.local_sync recover-install \
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
.venv-local/bin/python -m hypertest.interactive_client stop \
  --config /absolute/private/hypertest-local/config.json

# 在独立终端显式运行；若 MCP 已启动正确配置的 daemon，无需另起。
.venv-local/bin/python -m hypertest.interactive_client daemon \
  --config /absolute/private/hypertest-local/config.json
```

完成真实 manifest 后，在另一终端显式提交。该命令不依赖 Hooks，也不会偷偷启动 daemon、模型或测试：

```sh
.venv-local/bin/python -m hypertest.local_sync submit-manifest \
  --config /absolute/private/hypertest-local/config.json
```

原有 MCP 两工具继续可用。只有有效 ACK 与固定接受版本的全部分页原文读回完成才算本次同步确认；读取失败保留已接受状态并继续同版本读回。SENT / UNKNOWN / 失答沿原 key GET；NOT_FOUND 不允许重 POST、换 key 或另建 Task。同 checkpoint 完整确认后重复提交可返回 UNCHANGED；实质新意图先核对当前基线，不修改已经冻结的旧请求。同步状态不重写 reported PASS / FAIL，Stop / 上传成功也不推导 COMPLETED。

旧精简 journal 可能只有查询身份与原 digest，没有本轮新增的完整批准快照。兼容处理仅以原 key GET 验证回执并完整读回固定接受版本，内部记为 `LEGACY_ACCEPTED_READBACK`；不会重 POST、重建缺失原请求或将这种历史读回冒充原批准字节已比对的新 checkpoint。新格式快照丢失则明确受阻并保留原 key。

## Web 入口与验证接口

入口为 `Project → Codex 测试任务 → 接入本地模式`，既有任务表与错误重试不受影响。向导按以下状态展示：发行未发布、等待既有项目授权、路径未完整、三宿主真实会话未验收、Hooks 关闭、MCP 保留、首次同步需原件读回。没有 release URL、无校验 `curl | sh`、Operator-key 输入或 PowerContext admin token。安装字段只含私有路径等非秘密引用；页面不持久保存这些输入，也不调用写 API。

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

## 未交付能力

已有独立离线 bootstrap、候选构建工具源码及隔离专项结果，真实离线依赖闭包与合成 fixture 安装已通过；真实宿主会话仍待独立验收。尚未发布 `local-v*` 发行、线上可下载 bootstrap 或公开可信发行 manifest，也没有项目页可用的线上一键下载命令，不能将源码、单元通过或合成配置安装与正式发布混同。未自动安装当前机器或改全局技能；未承诺 Windows、三宿主自动事件、真实父会话接入与在线授权已通过；未实现 Memory Gateway、自动聊天 capture 或产品经验访问。Cloud 实现、共享应用注册入口与正式部署由独立所有者推进，不在本文冒称交付。
