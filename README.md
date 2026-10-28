# HyperTest One

> One Input. One Mission. One Complete Test Cycle.

HyperTest One 是面向测试工作的控制平面：管理项目、测试任务、用例和报告，让 Agent 使用被测项目已有的测试框架开展工作，并保留可追溯的结果与证据。Agent 的总结和上传成功不自动等于测试通过或正式质量判定。

## 本地 Agent 接入

当前 Local 接入采用 **显式 Skill → `hypertest` CLI → HTTPS 归档**。Agent 使用项目自己的工具完成测试；用户随后选择平台项目、任务，并显式归档本次产物。测试期间无需 HyperTest MCP、Hooks、native bridge 或后台同步。

1. 在 Web 全局「CLI 授权」页复制安装 Prompt，交给本机 Agent。页面提供平台地址；从项目进入时可预选项目。
2. Agent 安装固定版本的 CLI 和 `hypertest-archive` Skill，复用匹配的已有 profile 或发起配对。用户在网页核对短码、客户端、项目权限及期限并批准。
3. 测试完成后，在 Web 选择或创建本地任务，复制归档 Prompt 并显式交给 Agent。上传须明确 Project ID、Task ID 和产物范围；Subtask ID 可选，省略时归档到 Task 根空间。

没有打开平台页面时，可复制[中文安装 Prompt](docs/cli-install-prompts/hypertest-cli-install-prompt.zh-CN.txt)或 [English installation prompt](docs/cli-install-prompts/hypertest-cli-install-prompt.en.txt)。[CLI 授权与使用指南](docs/CLI_AUTHORIZATION_GUIDE.md)涵盖安装、授权、归档、排障和旧安装的受管退出。

当前发行是 [cli-v0.1.1](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.1)，要求 Linux/macOS 和 Python ≥3.12；实际宿主验收范围见指南及[发行记录](docs/CLI_STABLE_KEY_FIX_DELIVERY_20261027.md)。0.1.0 存在资产 `stable_key` 缺陷，应按受管流程升级。旧 `local-v*` 的 MCP/Hooks 接入已弃用，不用于新接入；被新归档替代且不兼容的旧任务、报告及兼容入口可按 [ADR-028](docs/architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 定向清理；未知外部操作不自动重发。无关凭据和用户源文件保留。

## Cloud 与兼容路径

Cloud 和 Local 共用 Project，但任务、权限与历史相互独立。Cloud 使用独立 Worker 和 DeepSeek Harness Python SDK，Codex 需显式启用，Claude 保持占位。能力开关、环境及功能验收以[当前 TODO](docs/TODO.md)和[Cloud 状态](docs/CLOUD_IMPLEMENTATION_STATUS.md)为准；代码默认配置与测试服务器实际配置可能不同。历史 Runner、Harness 和旧 Local 会话合同仍用于其各自的兼容与历史记录，不是新 Local 归档的前提。

正式事实需要相应合同要求的执行来源和证据；归档材料中的 PASS/FAIL 是保留的报告结果，不自动转换为 legacy VERIFIED Evidence 或 RELEASE_READY。关于各路径的边界和数据模型，参见下列基础规范与 [ADR-027](docs/architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)。

## 文档入口

结构性开发前阅读 [AGENTS.md](AGENTS.md) 和四份基础规范；规则冲突时按以下顺序处理：

1. [领域模型与状态机](docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md)：字段、关系、生命周期与持久化。
2. [Test Mission Protocol](docs/protocol/TEST_MISSION_PROTOCOL.md)：平台与 Agent 的协议合同。
3. [技术架构](docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md)：组件和运行边界。
4. [产品白皮书](docs/foundation/HYPERTEST_WHITEPAPER.md)：产品定位与原则。

- [文档索引](docs/README.md)：现行文档入口与历史资料的使用边界。
- [当前 TODO](docs/TODO.md)：实现、部署和用户验收分别记录。
- [服务器操作](docs/SERVER_OPERATIONS.md)：测试服务器、SSH、部署及数据和访问保护；旧部署记录仅反映当时状态。
- [CLI 授权与使用](docs/CLI_AUTHORIZATION_GUIDE.md)：当前本地接入。
- [产品设计](PRODUCT.md) 与 [界面设计](DESIGN.md)：PC 宽屏 Web 的设计依据。

按日期命名的交付、验收和部署记录是当时的证据，不是当前状态或操作指令；具体限制、版本和来源应回到对应记录核对。当前服务健康及实际部署身份需现场确认，不能由历史报告推断。

## 开发环境

本机开发辅助脚本需要 Python 3.12+、PostgreSQL、Node.js 22，以及 `.venv` 和 `web/node_modules`。已有兼容环境优先复用。以下用于新建本地开发环境；不要覆盖已有配置或把测试写入业务数据库：

```bash
docker compose up -d postgres
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,interactive]'
npm --prefix web ci
```

如没有 `.env`，以 `.env.example` 为参考建立配置，并按本机实际情况设置数据库、artifact 和 workspace 路径；不要将凭据提交到仓库。启动辅助脚本会执行 `alembic upgrade head` 并启动本机 API、legacy Worker 与 Web：

```bash
bash scripts/dev.sh
```

默认 Web 为 `http://localhost:3000`，API 为 `http://localhost:8000`，OpenAPI 为 `http://localhost:8000/docs`。`bash scripts/dev.sh --check` 只执行迁移及 API/Worker 导入检查。该脚本不是独立 Cloud Worker 的部署方式；执行相关任务仍需各自明确配置、授权和运行环境。测试服务器的 Docker 交付方式见[服务器操作](docs/SERVER_OPERATIONS.md)。

验证范围按改动风险确定。后端测试需要专用的可丢弃 PostgreSQL 测试库；`HYPERTEST_TEST_DATABASE_URL` 用于指定该库，测试前按需迁移。Web 可按需要执行 `npm --prefix web test`、`npm --prefix web run typecheck` 或 `npm --prefix web run build`。平台完整 CI 由 `workflow_dispatch` 手动触发；日常 push 和 PR 不自动触发平台回归，发行标签流程另行保留。

## API

API 默认前缀为 `/api/v1`，运行中的 OpenAPI 文档提供请求和响应结构。涉及领域、授权、幂等和版本控制时，以基础规范中的对应合同为准。

### Human input API

Legacy Run 的问题可通过 `GET /api/v1/test-runs/{run_id}/input-requests` 和 `GET /api/v1/input-requests/{id}` 查询；问题与回答属于任务上下文，不直接创建 Canonical Requirement 或 Evidence。回答使用 `POST /api/v1/input-requests/{id}/answer`，包含 `answer`、`expected_row_version` 和 `idempotency_key`。接受后返回原问题与 Job，恢复同一工作，不创建替代 Job。提交结果不确定时保留原答案、版本及 key，先查询状态并按原请求恢复；具体生命周期见 [Web 工作流](docs/WEB_PRODUCT_WORKFLOW.md)。
