# 远端测试服务器残留清理（2026-10-28）

承接同日前一轮：当时把历史远端运维说明误当成当前测试服务器，用户随后确认本 Mac 即测试环境，并追问“测试服务器”概念的来源。本轮核对来源、处理仍把远端环境写成现行的材料，并按 [ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 移除已无对应主机的巡检入口。

## 来源核对

- 该概念来自旧 `AGENTS.md` 和运维文档，不是业务数据库字段。Git 历史：SSH 规则写入于 `248b45d`（2026-10-18），远端测试服务器交付流程写入于 `d691f7e`（2026-10-23）；两者均已被本机容器规则取代。
- 数据库为 schema `0035_retire_legacy_test_runs`、122 张表，**没有远端主机、IP 或部署模式列**。名称接近的字段各有现行语义：
  - `cli_authorization_requests.server_url`：CLI 连接的平台地址，实际值为 `https://localhost:18444`，属现行字段。
  - `interactive_execution_*` 与 `run_execution_bindings` 的 `harness_host_id` / `host_proof*`、`source_bundle_transfers.server_workspace`：各自 profile 的宿主归因和工作区字段，不编码“测试服务器”；旧 Run 专属表当前为空。
  - `projects.*_url` 与 `local_archive_tasks.*_url`：项目及测试框架仓库地址。
- 结论：不存在旧云服务器部署遗留的地址字段；误导来自文档和脚本。

## 本轮变更

- `docs/CONTAINERIZED_DEPLOYMENT.md`：标题与首节改为远端历史，明确 systemd、宿主 nginx、SSH 别名、`/opt/hypertest` 路径和远端构建/验证步骤不再适用，并指向现行[服务器操作](SERVER_OPERATIONS.md)。
- 删除 `ops/check-remote.sh`（SSH 到已不存在的 `hypertest-one`）及 `tests/test_remote_checks.py`；同步修正历史文档中的链接和说明。
- `docs/CLI_TLS_TRUST_20261027.md` 标为远端历史；[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)与 [TODO](TODO.md)改为本机 CA `~/.local/share/hypertest-mac/bff/ca.crt`（CN=`HyperTest Mac Local CA`）。仓库内旧 Connector CA 公共证书仅作历史保留。
- `README.md` 与[文档索引](README.md)中的“测试服务器/SSH”措辞改为本机容器测试环境。

## 验证与范围

- 改动为文档及已退役的脚本/测试；`Dockerfile` 不复制 `ops/check-remote.sh`，无需重建镜像或重启容器。现有 `hypertest-mac` API、WireGuard Web 与 PostgreSQL 容器仍为 `cdc70d3` / `postgres:17` 并保持 healthy，本轮未改动运行服务。
- 相对 Markdown 文件链接检查 0 处失效（排除 `node_modules`、`.venv`）；`pytest --collect-only` 收集 2221 项，无导入错误。
- 未删除数据库记录：核对时旧 SessionTask/TestRun 专属表已为空，`server_url` 是现行 CLI 地址。未运行完整后端或 Web 回归，未执行用户功能验收。
- 仍保留的远端或旧 profile 脚本（如 `ops/activate-vpn-allowlist.sh`、`scripts/adr015_*.py`）是 ADR-015 历史验收材料，本轮不做无差别删除；如确认不再需要，可另行按 ADR-028 定向清退。

改动提交：`adfa2ad`。
