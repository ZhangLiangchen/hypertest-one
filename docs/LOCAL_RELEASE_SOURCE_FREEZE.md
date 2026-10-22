# Local 独立源码冻结

## 正式发行追加记录（2026-10-22）

独立分支最终资格提交 `874569fa566a137eba77ac4852caa6052cb04a17` 已钉 `local-v0.1.0`，[local-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.0) 于 `2026-10-22T12:08:14Z` 正式公开，仅包含 `darwin-arm64-py313`。完整三项摘要与公开下载验证见[发行记录](local-acceptance/local-v0.1.0-publication.json)；Local source digest 保持 `a5db7a7cc5058bd5fc9162c056f2b8d93c41bf18d6975879a334bbc611d56d8a`。本次后续文档与 Web 描述符提交不移动 tag、不替换已发资产、不改原始资格证据；以下 R6 冻结过程作为历史保留。

## 已执行的独立候选冻结

已从固定 base 形成独立 Local-only 分支并 nonforce 推送 [draft PR #23](https://github.com/ZhangLiangchen/hypertest-one/pull/23)，原共享 workspace / index 和 Cloud 改动保全。当前 R6 commit 为 `7aefe2878ffad4149d7e01bc18df69a6f090b0a6`；[CI #118](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/39770913859) 已全通过。源摘要 `a5db7a7cc5058bd5fc9162c056f2b8d93c41bf18d6975879a334bbc611d56d8a` 固定 runtime、依赖 catalog、pyproject 与构建 / 安装入口。Claude Code、Codex 与 DSH 的 R6 精确目标实机均已通过；当时提交登记正式 Darwin 构建资格，后续 tag / 公开结果见文首追加记录。

脚本只负责准备 checkout；授权后执行者显式形成 commit / bundle，每轮分别记录源码、wheel 和回归身份。验收、target publication 配置及文档随后单独提交，不改变 Local source digest；最终重新核对摘要后才接受正式目标。Darwin arm64 / CPython 3.13 已登记 RELEASE；Linux 仍 CANDIDATE。公开命令 / Web 描述符在资产发布后单独追加，避免 URL / 哈希自引用。

日期：2026-10-22（Asia/Singapore）。此流程保护当前共享 checkout 中尚未提交的 Cloud／Local 改动；不把整份 dirty tree 作为 Local release 来源。

`scripts/freeze-local-release-source.py` 只准备另一个可审查 checkout，固定基线为 `5c03e4d90bed69b6420238849cbb3a8bae2f4c42`、分支名为 `codex/local-mode-release-v0.1.0`。脚本不 commit、tag、push、构建或发布，不修改当前 checkout、index、配置及其他会话状态。主控确认冻结时机后才执行：

```sh
python3 scripts/freeze-local-release-source.py \
  --source "$SHARED_CHECKOUT" --output "$NEW_ISOLATED_CHECKOUT"
```

准备过程从该基线创建隔离 Git 对象及 index，仅复制以下白名单：

- `src/hypertest/local_sync/**`、`sync_core/**` 的代码及明确模板；`interactive_client/{__main__,config,ipc,mcp_server,service}.py`。
- `scripts/{build-local-release,install-local-release,prepare-local-dependencies,local-release-commands,freeze-local-release-source,plan-local-release}.py`、`scripts/local-release-dependencies.json` 和 `scripts/local-release-targets.json`。
- `.github/workflows/local-release.yml`；`tests/test_task_sync_core.py`、`tests/test_session_task_mcp.py`、`tests/test_local*.py`（含 DeepSeek bridge、真实事件 adapter 和后续来源测试）。
- Local guide／helper／测试与 SessionTask 区域挂载、测试 require 映射；项目主页面不复制 Cloud 导航。
- Local 发行／实现／计划文档、ADR-020／021、`docs/LOCAL_*ACCEPTANCE*.md` 和 `docs/local-acceptance/*.json` 的非秘密验收材料。

`pyproject.toml` 取基线，只增加 `hypertest-local` console entry；不复制 Cloud extras／命令。四份基础规范、`AGENTS.md`、`README.md`、`MVP_STATUS.md` 取基线文本，追加 Local 专属实现与契约说明；`CODEX_SESSION_TASK_SYNC.md` 原操作正文不动，仅追加 Local 链接。ADR-018 全文、TMP §45 和领域 §50 仍是基线字节；新客户端不修改既有服务端字段、scope 或表结构。

明确排除新的 `cloud/`、`deepseek_harness/`、Cloud API／application／domain／0023 migration、config／main／models、原 CI，以及当前混入 Cloud 实施状态的基础文档。共享核心的 Local 消费方可以发布，Cloud reporter／Worker 不进入 Local 包。

完整逐文件 SHA-256、白名单和未提交状态保存在隔离 checkout 的 `.git/local-release-freeze.json`。审查时同时查看 tracked diff 和 untracked 文件，核对根目录没有凭据、主机配置、私有验收原件或 `.env`。源目录仍有并发 writer 时不得宣布冻结。

原 ADR 文本中的 Cloud／Memory 设计引用只是独立设计背景；此 Local 分支不将这些未包含的实现声称为已交付。发布负责人应在提交前审阅链接与状态，保留“Cloud／Local 分别实现、分别验收”的含义。

主控审阅通过后，才在隔离 checkout 提交所选文件、记录完整源码 commit、补齐与精确 Local 文件摘要绑定的各目标宿主证据，然后创建独立 `local-v*` tag。正式发布构建必须使用 clean checkout、完整 commit、匹配标签及相应验收文件。旧 `mcp-v0.1.0`、`mcp-v0.2.0`、当前共享工作区与 Cloud 工作进度不变。
