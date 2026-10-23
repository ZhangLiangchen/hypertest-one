# Local caller 适配后续研究（2026-10-23）

本轮只读核对官方源码与协议，未运行真实模型或宿主业务，未签发授权、修改宿主安装或发行新 Local 包。现有 ADR-024 的 caller fence 保持：新 BIND、手动已绑定任务的显式新 sync，以及新 memory 调用，仅接受已实现的 Codex CLI `0.144.6` 路径；授权 GET、已确认 legacy auto-task resume、原 key 只读恢复分别保留。

## 已固定的来源与结论

| 宿主 | 本轮核对来源 | 结论与限制 |
| --- | --- | --- |
| Codex CLI `0.144.6` | 官方 tag `rust-v0.144.6` 是 annotated tag；tag object 为 `1e66aaa95b5ab39d3ef3057cd50bdecd576a8356`，解引用源码 commit 为 `5d1fbf26c43abc65a203928b2e31561cb039e06d`。[调用处](https://github.com/openai/codex/blob/5d1fbf26c43abc65a203928b2e31561cb039e06d/codex-rs/core/src/mcp_tool_call.rs#L577)、[metadata 覆盖实现](https://github.com/openai/codex/blob/5d1fbf26c43abc65a203928b2e31561cb039e06d/codex-rs/core/src/mcp_tool_call.rs#L1127) | 每次工具调用从当前 `sess.thread_id` 写入 `threadId`，覆盖同名旧值；现有 MCP request context → 私有 IPC → SessionStart root 核对与该来源一致。本轮没有发现需要放宽身份规则的兼容缺陷。 |
| Codex 当前源码 | 2026-10-23 查询的 `main` 为 `1c0c45bfc372fb7d7d581508fdef5eef8235eab7`。[当前 metadata 实现](https://github.com/openai/codex/blob/1c0c45bfc372fb7d7d581508fdef5eef8235eab7/codex-rs/core/src/mcp_tool_call.rs#L1424) | 仍使用 `threadId`，还携带其他调用 metadata。源码相似不构成对任意 CLI、Desktop、OS 或版本的宿主支持资格；本轮没有扩大现有版本白名单。 |
| DeepSeek Harness | 既存固定源码 `687f282e8625c6b8d11ff58211a90524be2e4317` 的 [MCP 调用闭包](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/mcp/mcp-client/src/tools.ts#L138)，及本轮 `master` `22ddee3792402c3e70ec5f86a63c3e3e895a2f60` 的 [同一实现](https://github.com/deepseek-ai/deepseek-harness/blob/22ddee3792402c3e70ec5f86a63c3e3e895a2f60/packages/mcp/mcp-client/src/tools.ts#L138) | 两个固定版本都只把 tool name 和 arguments 送给 MCP；闭包收到的 `execution.agent` 没有作为 caller 身份转发。已确认的官方 root Registry / 生命周期来源不能凭空成为这次 MCP 的调用者；缺少 per-call 传输关联时继续 `NATIVE_CALLER_CONTEXT_UNSUPPORTED`。 |
| Claude Code | 官方 [MCP 文档](https://code.claude.com/docs/en/mcp)、[Hooks common input](https://code.claude.com/docs/en/hooks#common-input-fields) 与 [PreToolUse](https://code.claude.com/docs/en/hooks#pretooluse)，查阅日期 2026-10-23 | Hooks 提供 session、tool-use 与子代理相关字段，但本轮没有找到保证 MCP server 在每次 `tools/call` 收到真实父/子 caller 的官方合同。Hook 事件中的父 session 或一次 tool ID 不能独立证明同时到达 MCP 的请求是谁发起。该结论只描述已核实来源，不宣称所有其他版本都不存在该能力；当前新写入继续明确拒绝。 |

上述上游文件只用于研究，未把其代码或上游运行目录打包进现有发行。官方文档会更新；表中 Git 链接固定具体 commit，在线 Claude 文档只代表本轮查阅内容。

## 后续适配需要满足的条件

Codex 新版本需单独固定其真实版本、官方 caller 注入和 Hooks/root 语义，再验证当前 invocation 的 thread 与私有 root 一致；不能从 nested metadata、模型参数或环境自报回退取得父身份。未携原生 metadata 的 CLI `bind-task` 仍不能以自报 session 代替 MCP caller。

DeepSeek 的可研究实现位置是官方工具闭包实际收到的 `execution.agent`。要形成 HyperTest 自有可选 adapter，需将其当前真实 Agent/Session 与官方 root Registry 关系通过独立私有通道传递，明确区分 child，再与批准 Project、workspace 和 root 校验；必须另行核验配置、重连、并发及完整发行来源。现有兼容 Hook bridge 或 `agent.id` 字符串参数不自动满足该条件。本轮未安装自定义插件，也未启用这条新写入路径。

Claude 若使用 Hook/MCP 关联，需要先找到可验证的逐调用共同标识及真正的 parent/child 字段，解决乱序、并发、失答、重连和旧事件重放；不能采用“最近一次 PreToolUse 属于父会话”作为来源。实现不得读取聊天、推理、transcript 或 raw tool body 来补身份。

这些研究不改变平台授权、Task owner 或幂等语义。任何后续宿主适配仍须保证：错误/缺失 caller 零新 POST；子代理只向真实父任务贡献；原 key UNKNOWN 只读恢复可用；旧 `local-v0.1.0` 的包、tag、摘要和历史三宿主结果保持原身份。真实宿主 E2E 与新发行继续是独立交付项。
