# DeepSeek Harness Local 接入验收

日期：2026-10-22（Asia/Singapore）。本记录只覆盖独立 Local 父会话，不涉及 Cloud commander、模型委派或 SUT 执行。

## 已核对的官方能力

本机 `dsh --version` 返回 `0.1.5-rc.1`。实际入口为 `~/.local/bin/dsh`，解析到 npm 包 `@deepseek-ai/dsh/lib/bin.js`；该 CLI 使用范围依赖，实际安装的 Hook / Agent / LLM 组件为 `0.1.5-rc.2`，不能从 CLI 版本推定其依赖版本。adapter 分别核验这个明确组合，未知版本拒绝自动触发。这与 Cloud 的 Python SDK / runtime `0.2.1rc2` 是不同的发行物，不能相互替代版本或验收结果。

本轮官方仓库只读核对的完整 commit 是 `687f282e8625c6b8d11ff58211a90524be2e4317`，其中组件已经是 `0.2.1-rc.2`，只作为新版本对照，不能证明旧安装行为。实际旧版本以 npm 对应固定版本 tarball、registry integrity 和已安装 entry SHA-256 比对登记。官方 compatibility bridge 是候选触发入口；动态来源最终使用 **HyperTest 自有、基于官方 Registry / lifecycle API 的版本化 adapter**，不宣称官方 bridge 本身已经修复父子来源与时序问题。[官方 bridge 说明](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/experimental/hooks-claude-code/README.md)。

| 项目 | 本 Local adapter 的边界 |
| --- | --- |
| 自动触发 | `SessionStart`、`PostToolUse`、`Stop` |
| 真实会话来源 | bridge 的 `session_id` 取自当前 `agent.session.header.id` |
| 工作区来源 | `cwd` 取自当前 `agent.session.header.cwd`；仍须与显式选择的工作区核对 |
| 子代理 | 自有 adapter 核验 Registry 中精确 live Agent 对象、`roots()` 关系及 session header 的亲缘信息，拒绝 child 自动绑定；父会话通过批准的文件 slot 汇总贡献 |
| 退出 | 不提供 `SessionEnd`；`Stop` 不表示业务完成或 PASS |
| 重载 | bridge 的 `configPath` 只在进程启动时读取；更改后重新启动所选 profile |
| 事件正文 | 只向共享协调器传允许元数据；丢弃 prompt、reasoning、transcript、工具输入和工具输出 |

实际安装的旧 compatibility bridge 将 SessionStart detached 执行，而且其他三个事件也可能属于 child；仅取消 Subagent Hooks 仍不足以防止子任务误建。新版本[官方实现](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/experimental/hooks-claude-code/src/index.ts)改为 awaited `agent/created`，再次说明版本必须分开。自有 adapter 仅从真实 `agent/session-start` 产生绑定，并在 awaited `agent/pre-step` 等待该观察完成、通过官方消息构造器提供允许的产物路径，不扫描聊天，也不创建全工作区 latest locator。协议单测中人工构造的 payload 不能证明真实宿主接入。

## 配置实现

`src/hypertest/local_sync/deepseek_bridge.py` 提供 compatibility `bridge_capability()` / `bridge_descriptor()`，以及正式动态来源的 `root_bridge_descriptor()`。它只读实际 npm 安装和所选现有 profile 的 package metadata，不执行 CLI、不读认证、不初始化 profile，也不改变用户配置。未知 CLI / bridge 版本或未识别布局不能启用自动触发，显式 MCP 独立保留。

安装器将 MCP row 和自有 root adapter row 放在同一个 package-owned patch block 内。`deepseek_root_bridge.mjs` 是统一 wheel 的固定 asset，使用实际 Registry 关系过滤根会话，以固定的 `python -I -m hypertest.local_sync hook --config <private path>` 传送允许元数据；不接收任意命令，不继承 `PYTHONPATH`，不向子进程传模型认证。动态来源不生成未被读取的 Hooks JSON。安装、升级、回退和卸载仍通过原配置事务，保留原 client、Project、journal 和用户 profile。metadata 校验只表示支持的布局和版本，不证明 npm 来源、宿主身份或验收通过。receipt 维持 `CONFIGURED_UNACCEPTED`，直到取得真实事件及完整接受版本读回。

`tests/test_local_deepseek_bridge.py` 覆盖版本不匹配、缺失 bridge、错误 profile、路径逃逸、symlink profile 和来源边界等配置契约；这些 fixture 测试不计为真实宿主验收。

## 真实接入验收流程

主控提供本轮专用、限时的 `task:sync` client config 和明确受权的管理验收 Project。验收工作区只含本轮批准的 Markdown 产物；不接触现有业务项目，不运行 SUT，不使用 Cloud 授权或模型委派。

1. 创建私有且独立的 Harness home / profile，使用官方 base + SDK app bundles；安装本轮统一客户端、MCP 和三事件 root adapter。个人 profile 不变。
2. 由官方 credentials provider 只引用已有本机 owner-only credential 文件；不复制登录或 token，不将认证值放入配置、命令、日志或模型上下文。验收不开放凭据写工具。
3. 显式限制工作区和产物 slot。真实 `SessionStart` 提供父会话 ID，并结合所选 workspace 绑定来源；不能在启动前编造 headless 随机创建的 session ID。
4. 在只启用所需文件工具、禁用 shell / web / delegation 工具 / workflow / skills / 外部指令扫描和额外标题模型调用的 profile 中，通过官方 `JsonRpcLineTransport` 驱动同一真实 Agent：第一 turn 仅初始化并回答 READY，等待真实父绑定，第二 turn 写指定 Markdown 文件。SDK API 正式允许调用方给新会话分配 ID，再由真实 registry 创建；这不是冒用历史会话或注入 Hook payload。通过官方 registry 另外创建一个无 prompt / 无模型请求的 child，仅验证真实亲缘及过滤。设置请求输出上限、总超时；不保留 raw stdout / stderr。
5. 检查由真实 `PostToolUse` / `Stop` 自动触发的 checkpoint：只有相同父会话的一项 SessionTask、稳定 Project / owner、允许的产物正文和原始 reported result。以真实 ACCEPTED 回执及该固定版本的完整分页读回确认同步；MCP 工具列表或宿主退出码不够。
6. 再次无变化触发、禁用 Hooks 后显式 MCP、原 key 恢复等结果分别登记；不把重复通知制造的新版本或 default PASS 视为成功。

真实模型有效性、MCP 连接、自动事件、ACK 和完整读回各自记录。未取得本轮事件及读回前状态为 `NOT_OBSERVED`；模型认证缺失、事件缺失或同步受阻须保留真实原因，不能用 fixture 替代。

## 当前验收状态

已完成本机版本 / 安装布局、官方事件语义和固定版本 npm entry 比对；已实现受版本约束的 bridge / root adapter 与配置契约测试源码。早期源码快照的独立 SDK profile 无模型初始化已真实返回 protocol `0.0.1`、`initialized=true`、runtime exit `0`；它没有创建会话或管理任务，且不能代替正式 wheel 的来源与真实同步验收。正式 wheel 下的真实模型运行、父子过滤、平台 ACK / 固定版本完整读回尚待执行。本文件不表示已发布 release 或已启用个人全局 Hooks。
