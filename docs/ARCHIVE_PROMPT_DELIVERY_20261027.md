# 页面归档 Prompt 交付（2026-10-27）

本地任务创建页新增「归档 Prompt 模板」，支持复制和折叠查看全文。任务创建成功后进入详情页，「上传目标」提供已填真实项目和任务 ID 的「复制归档 Prompt」，选中子任务时同步填写 Subtask ID，根空间不携带子任务。

## 实现

- 中英文模板以 `$hypertest-archive` 显式调用开头，自动填写当前 HTTPS origin；创建前保留明确的 Task ID 占位。
- 产物绝对路径及允许内容、排除项、既有 Profile、本机 CA 配置由用户补齐，不固化个人 Mac 路径或假设 default profile。未补齐时要求停止并询问，不能自行扫描上传。
- 指定 CA 时，每条 CLI 命令显式设置 `SSL_CERT_FILE`；保持 TLS、主机名和证书有效期验证。保留只读授权/目标核对、范围限定、原 key UNKNOWN 恢复、回执及接受版本读回要求。
- 复制动作不调用 CLI、不创建任务、不上传产物。剪贴板拒绝时自动展开只读全文，支持手动选择复制。
- `web/lib/archive.ts` 统一生成内容，`ArchivePrompt` 复用于创建与详情页；目标 UUID 和 HTTPS origin 不合法时不生成可复制指令。

操作说明已写入[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md#从页面复制归档-prompt)。本轮不改变 API、数据库、CLI 包或归档协议。

## 验证

- `archive-ui`、`archive-prompt`、`local-task-creation`：**29 passed**。覆盖创建/详情复制入口、中英文、根/子任务精确目标、占位约束、TLS 配置、非法目标拒绝及既有创建行为。
- TypeScript 检查、差异检查、组件设计静态扫描通过。
- 1600px PC 合成浏览器检查：创建页复制成功、任务根空间省略子任务、选择子任务更新目标、当前 HTTPS 地址、复制失败展开手动全文均通过。业务 API 全部使用 GET fixture，未创建真实任务或上传。截图保存在 `output/playwright/archive-prompt/`；临时浏览器与 loopback dev 已停止。
- 真实产物归档为 USER_OWNED，本轮未执行；上述结果是开发回归及 UI 检查。

## 部署

Web 已从推送 Git `40ec1e3ce250faea8039da4477f64b6b26573090` 的干净复用 checkout 构建并部署，正式构建通过。镜像为 `sha256:ae2ea53e1c0ac861ae11fdf737cb8b550aa4579d0f2c947ca81b75785a9122ee`。

五容器 healthy、网络守卫 protected；API health、任务创建路由及归档详情路由均 HTTP 200。API 保持0061007、schema保持0032、固定ops保持1512d11；其他容器镜像及CLI发行包不变，无数据库迁移。运行记录位于 `/opt/hypertest/container-builds/archive-prompt-20261027/`。
