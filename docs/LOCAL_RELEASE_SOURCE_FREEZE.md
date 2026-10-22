# Local 独立源码冻结

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
