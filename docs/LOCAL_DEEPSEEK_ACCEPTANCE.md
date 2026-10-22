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

**R6 的真实 SDK profile 接入已重新观察通过；最终资格选择 R6，R5 独立保留为历史。** 机器可核验的无秘密记录见 [DeepSeek R6 原生验收证据](local-acceptance/deepseek-native-20261022.json)；[R5 历史证据](local-acceptance/deepseek-native-20261022-r5.json)的原字节和摘要没有改变。后续候选必须按其精确源码与 wheel 重新验收，不能自动继承通过。这不表示正式 release 已发布，也未启用个人全局 Hooks。

| 项目 | R6 实测结果 |
| --- | --- |
| 固定候选 | commit `7aefe2878ffad4149d7e01bc18df69a6f090b0a6`；source digest `a5db7a7cc5058bd5fc9162c056f2b8d93c41bf18d6975879a334bbc611d56d8a`；wheel SHA-256 `dd88a810e43eea70bf669f7c3fde2929d77e7035b6cdf87a48c735951e47ac40` |
| 客户端来源 | 36 个安装成员逐字节匹配 wheel；28 个非生成运行源码成员匹配候选，无意外源码漂移；`hypertest/__init__.py` 按 lean wheel 构建规则生成 |
| 实际环境 | Darwin 26.5.1 / arm64，Python 3.13.3，Node 26.8.1；CLI `0.1.5-rc.1` / 组件 `0.1.5-rc.2` |
| 真实父会话 | `session-87323bb7-3ee3-4589-8f75-4fcd1d1d342c`；两个真实模型 turn 完成，runtime exit `0` |
| 自动同步 | 模型只写批准的 `analysis.md`；没有显式调用 sync；PostToolUse checkpoint 得到唯一 ACCEPTED / `READBACK_COMPLETE` |
| 平台结果 | Task `01a16360-d6ae-71fe-92d6-89d238c773aa`，接受版本 `1`；原 key `hook-ec92200712d94249bf334dae924f2d67`；文件和平台计划 SHA-256 相同 |
| 真实 MCP | 模型实际调用 `mcp__hypertest__hypertest_get_task`，原生 tool-result 无错误，来源参数匹配，返回上述 Task / version |
| 固定版全读回 | IPC 和独立 typed GET 均完整读取同一接受版本，各 2 页；两份完整 JSON 与 canonical document SHA-256 相同 |
| 真实 child | 官方 Registry 创建 child，真实 `agent/session-start` 已到达，Registry root=false / ownedByParent=true / 零模型请求；无 child binding，平台查询返回 404 |
| 收尾 | 0 pending、2 个父绑定、2 个 `READBACK_COMPLETE`（R5 历史与 R6 新会话各一项），private parent 为 `0700`；两个 child 均无绑定 |

R6 安装后没有换 actor / client / Project / grant，也没有重置原 journal。原 R5 key 再次 GET，固定版本仍为 `1`，完整文档 SHA 与 R5 历史证据相同；R5 私有证据文件的原摘要也全部保持一致。R6 使用真实新父会话建立独立 Task，不冒用或改写 R5 的身份。

平台 `IN_PROGRESS / NOT_RUN` 来自事先明确批准的验收策略；未运行 SUT、Shell、Web 或业务测试。Hook / MCP 成功不生成测试 PASS。记录只含允许元数据、refs 和 digest，没有聊天、推理、原始工具 payload 或凭据。

本次**自动触发接受范围是实际 PostToolUse 产物 checkpoint 至回执和完整读回**。父会话 Stop handler 未单独计数观察；两个 `turn/end completed` 和最终没有重复版本不能扩写为三个事件分别通过。`SessionEnd` 不可用；headless 单 turn、resume 和其他宿主不在本记录的接受范围。

验收曾使用过长的 macOS 私有 socket 路径；在没有 intent / pending / binding 的阶段，将整个专用 state 原子迁到更短 owner-only 目录，既有文件内容、actor / client / Project / token 全部保留。正式 daemon 来源以同 UID 的 peer PID、实际隔离参数、Darwin Framework 执行关系，以及候选 venv 内的 Pydantic native extension 映射共同核验。早期源码 / R4 无模型初始化记录独立保留，未被计作真实同步通过。
