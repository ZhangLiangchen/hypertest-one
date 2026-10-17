# Web 工作台操作指南 / Web workbench guide

## 界面语言

在右上角选择 **中文** 或 **English**。默认中文，语言选择保存在当前浏览器的 Cookie 中，刷新与页面跳转后继续生效。切换不会清空当前表单或正在查看的页签，Ant Design 的表单、分页、确认框和日期显示也随语言更新。

界面语言不改写 PRD、项目名称、Agent 生成的需求/用例/诊断、测试源码或证据原文。质量门禁的固定系统理由提供中文展示，并保留可展开查看的判定记录原文；原始记录、ID 和 Hash 不变。

Choose **中文** or **English** in the upper-right corner. The browser remembers the language across navigation and reloads. Switching preserves the open form and selected result tab. Requirements, Agent output, generated code and evidence retain their original content.

## 从项目到结果

1. **创建项目**：填写项目名称、唯一标识及默认分支。仓库地址可预填后续运行。项目名会建议一个可编辑的标识；标识已存在时可以直接打开原项目。
2. **创建测试运行 → 源码**：填写仓库的 origin 源地址。GitHub HTTPS 来源可输入分支/标签并选择“解析并固定提交”，也可手工填写完整 40/64 位提交 SHA。解析不创建 Run，也不修改仓库；同名分支/标签需明确 `refs/heads/...` 或 `refs/tags/...`。修改源地址或参考版本后必须重新解析。正式测试始终使用固定 SHA，分支后续移动不会改变已有输入。
3. **需求**：粘贴 PRD，或导入 UTF-8 `.md` / `.txt` 文件并编辑正文。导入限 8 MiB，需求限 2,000,000 字符，配置限 100,000 字符；最终序列化请求须不超过 10 MiB。配置可使用纯文本或 JSON，留空保存 `{}`。
4. **策略**：选择全局和按风险类别的设计维度，以及阻止发布的缺陷级别。功能维度与阻断级缺陷的底线规则由平台保留。
5. **确认**：检查源码 SHA、PRD 原文和策略。创建后形成不可变输入；新的需求或代码版本应创建新 Run。关闭向导会在当前页面保留草稿和步骤；离开页面或刷新不提供草稿恢复。
6. **运行测试周期**：GitHub HTTPS 来源可选择“自动准备固定源码并运行”，一次持久任务完成检出、Agent Mission、Docker 执行及 Gate。其他来源选择 Worker 主机上的匹配 Git 检出；其 HEAD 和 `git remote get-url origin` 必须与本次输入一致。Worker 独立处理任务，关闭浏览器不会取消工作。默认镜像只包含 Python 标准库与 pytest；其他应用依赖需运维准备可信镜像，正式执行不联网安装依赖。
7. **查看结果**：后台任务显示状态、错误、周期步骤和重试历史。被拒绝的 Mission 也保留已完成步骤与关联身份；展开尝试记录可查看 Agent 摘要、未决事项和完整原始结果，不能将其当作正式事实。检出失败会在操作窗口显示错误与任务入口。通过任务详情可直达阶段、执行、证据、发现或质量判定。页面自动刷新数据，暂时读取失败会保留已加载内容和页签。
8. **查看判定依据**：在“最新质量判定”中打开详情，再沿关联查看证据和问题发现。证据详情展示实际内容、采集来源与 SHA-256；失败运行可查看诊断结果。确认或解决 Finding 属于受控操作，需要填写原因，不能用“任务完成”代替质量结论。

**仓库源地址与检出目录不同。** 创建 Run 时的 repository 应等于已有检出的 `git remote get-url origin`；不能将任意 checkout 目录冒充 origin。本地 Git 路径只有本身就是 origin 值时才适用。运行时填写的 workspace 则是 Worker 主机上干净且匹配固定提交的检出目录。浏览器本机路径不会上传源码。自动检出仅支持 URL 中不包含凭据的 GitHub HTTPS 仓库；私有仓库授权需预先配置在 Worker 主机。

仓库地址不能嵌入密码或 HTTPS 用户信息；使用主机上预先配置的 Git 认证。平台会在创建输入和启动 Agent 前检查，校验错误不返回提交的原始字段值。完整周期还会先检查实际 Runner 和可信镜像是否可用；这一步失败时不会调用模型或检出仓库。运行前检查不代表已经产生测试执行事实，最终以 Execution、Evidence 和 Verdict 为准。

Create a project, pin repository/commit inputs, provide the PRD, choose policy and review the immutable snapshot. Then submit a **Run test cycle** task using a matching checkout on the Worker host. Follow Tasks → Executions → Evidence → Findings → Verdicts. Local paths refer to the Worker host; entering a laptop path does not upload a repository.

GitHub HTTPS origins can resolve a branch/tag to an immutable SHA and prepare that source within the same durable test-cycle task. Other origins use a manual full SHA and an existing matching checkout. Attempt details show the original Agent summary and unresolved items separately from accepted proposals and trusted execution evidence. The default Runner image supports standard-library Python and pytest; application dependencies require a trusted image prepared by the operator.

Repository addresses must not embed credentials. Configure Git authentication on the host. The complete cycle checks the actual Runner before model calls or source preparation; a successful preflight is readiness information, while formal execution facts still come from the Runner.

## 任务状态与质量结论

| 展示 | 含义 |
|---|---|
| 任务已完成 / Task completed | Worker 完成了该次操作；测试是否通过以正式执行和质量判定为准 |
| 通过 / Pass | 对应正式执行或用例通过 |
| 可发布 / Ready for release | 当前规则所需设计覆盖、正式执行和可信证据齐全，且没有策略阻断的已确认缺陷 |
| 阻止发布 / Release blocked | 已观察到失败或存在策略阻断的已确认缺陷 |
| 受阻 / Blocked | 当前流程或判定受阻；展开原因检查缺失事实、覆盖或运行状态 |
| 已中断 / Interrupted | 先查看已保存的状态和外部资源，再显式重试；旧历史保留 |

后台任务提交具有幂等身份。响应丢失时，Web 先查询相同请求是否已保存；无法确认时保留同一请求标识供重试。创建 Run 的同一标识不能绑定不同的实质输入，平台返回 409 并保留原记录；分支参考标签不改变 SourceSnapshot 的身份。

**Task completion is not a passing quality verdict.** Inspect official execution facts and the final verdict. Requests preserve identity across uncertain submissions; retries retain prior history.

## SSH 隧道访问

已部署环境继续通过 [http://127.0.0.1:8080](http://127.0.0.1:8080) 访问，应用和数据库回环绑定。需要重新建立隧道时，在本机终端执行并保持连接：

```bash
ssh -p 22 -N -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8080:127.0.0.1:8080 root@155.138.206.106
```

This deployment keeps SSH as the access boundary. Web, API and PostgreSQL remain loopback-bound; no public application port is required.
