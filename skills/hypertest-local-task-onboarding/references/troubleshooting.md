# 按观察排查，不循环重建

仅在发生对应症状时读本文件。先区分配置、宿主生命周期、caller、平台绑定和内容读回，不把它们统称为“未接入”。

| 症状 | 最小核验与下一步 |
| --- | --- |
| MCP 可读 Task，但没有 root | 检查实际 SessionStart Hook 源、启用/信任、工作区和生命周期；GET 成功不证明当前来源可写 |
| 用户看不到待信任项 | 先看实际 `hooks/list` 或标准 `/hooks` 的 `sourcePath`，别再次要求用户盲点信任 |
| 四项已信任，原聊天仍无 root | 信任不会补发历史启动；优先使用宿主可用且受支持的同聊天生命周期控制；没有该接口时，请用户在**已选正确主聊天**执行 `/compact`，或重启并恢复该聊天。之后核对实际登记，不凭操作回复推定成功 |
| 出现新 root，但 session 不同 | 它可能是另一个真实 CLI/聊天；不可借用。保持原目标，核验正确主会话的生命周期 |
| root 存在，BIND 仍报 caller 错 | 查看 `NATIVE_CALLER_CONTEXT_REQUIRED/MISMATCH/UNSUPPORTED`，核对真实宿主版本和原生 MCP；不在 arguments 添加 `_meta` 或 caller 字段 |
| 新工具缺失或 schema 没有 task_id | 对照 profile 运行时、旧 daemon、服务端和宿主工具目录；按 setup 的匹配版本升级，不能 fallback legacy 自动建 Task |
| UNBOUND 授权为空/actor 不符 | 由 Operator 在 UNBOUND 下核对 intended actor 及当前 grant；Agent 不自行签发 token 或变更 owner |
| Task 已 BOUND 到另一会话 | 回到原绑定 writer 接续，或报告不可改绑；不能冒用来源、转移资产或另建 Task 掩盖问题 |
| Hook 后额外版本/重复报告 | 停止新增写，完整读取新 head；比对实际 policy 槽、报告 key/title/result、接受版计划和本地投影。保留新旧版本，不清除记录“恢复干净” |

## worktree 与 Hook 源不同的排障路径

本次接入曾观察到：worktree 的 `.codex/config.toml` 层正常加载 MCP，但宿主发现的 project Hooks 来自主检出目录的 `.codex/hooks.json`。这是一次具体环境观察，**不推导所有 Codex/worktree 恒按此规则加载**。

1. 使用宿主已有标准 Hooks 检视入口。若已接通官方 app-server 的只读诊断，可调用 `hooks/list`，按实际 cwd 检查 `sourcePath`、`enabled`、`trustStatus`、errors/warnings。
2. 必要时对照同宿主 `config/read` 的 active layer 和 disabledReason，分辨 Hook 发现源与 MCP 配置源；不要因 Hook 缺失就宣称整个 project config 未加载。
3. 在用户授权的**实际发现源**通过官方安装器合并 HyperTest Hooks，保留 BUGate 等原条目；使该 profile 的 workspace/policy 与实际生命周期 cwd 一致。
4. 确认新增条目已被发现，再让用户在标准界面审阅具体定义。不要直接写 trust hash、禁用信任机制或用伪造 Hook 输入“验证”。

只使用可用的受支持连接；不要猜私有 socket 或 UI 接口，也不要为了触发事件另开 Provider/SDK/模型会话。独立进程的只读 hooks/config 诊断若可用，也不等于已经附着到当前聊天的生命周期。

## 给用户一个明确且必要的操作

需要人机信任或当前工具不能触发真实生命周期时，说明已完成的自动工作、唯一缺口、正确工作区/聊天和标准操作。例如：

> 已核实实际源中的四项 Hooks 都已启用、信任；当前绑定目标仍是原 Task。这个主聊天尚无匹配的真实 SessionStart，请在**本聊天**执行 `/compact` 后继续；不支持时重启并恢复本聊天。我会重新核对 root，再进行尚未发送的绑定。

仅在观察确实符合示例时使用。不要让用户反复信任已经受信任的项、反复新建接续聊天，或因 root 缺失就归责于用户。已绑定/已接受的操作不因重载而再次发送。

证书警告、项目权限和其他宿主安全提示遵守其标准人工流程；不能通过关闭校验、工具代填秘密或绕过限制来完成接入。

上游行为参考：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)、HyperTest 的[真实来源实现](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/sources.py)与[新绑定 caller 约束](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md#3-绑定授权不依赖知道-task-id)。
