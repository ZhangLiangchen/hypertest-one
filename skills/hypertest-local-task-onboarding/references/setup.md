# 安装与宿主核验

在首次接入、升级或工具能力不符时读本文件。以下变量均须换成用户实际选择的绝对路径或已核实版本；不把占位内容直接执行。

## 1. 选兼容版本，保留既有身份

先读[现行发行与安装说明](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/LOCAL_MODE_RELEASE_AND_INSTALLATION.md#adr-024绑定能力与发行兼容)，核对服务端、Local 客户端、Python、OS/架构及宿主能力。已有兼容安装时复用，不重复安装。需要安装时优先使用含所需能力的不可变正式发行，验证可信渠道与预先确认的摘要。旧 `local-v0.1.0` 的固定资产没有 ADR-024 新绑定工具；服务端升级不会改变旧包。

新版 `local-v0.1.1-rc.1` 是明确的候选发行，内置本指南和当前绑定客户端；两个目标的包与固定摘要安装命令见[本轮交付](https://github.com/ZhangLiangchen/hypertest-one/blob/main/docs/LOCAL_ONBOARDING_SKILL_DELIVERY_20261026.md)。候选下载或安装不代表新宿主已验收，不沿用旧三宿主证明。已有 runtime 安装后，可显式把包内指南安装到所选 Agent 技能目录：

```sh
"$local_python" -m hypertest.local_sync install-skill \
  --directory "$local_install_directory" \
  --skills-directory "$local_agent_skills_directory"
```

`local_agent_skills_directory` 是用户选择的绝对技能父目录；Codex 常用 `~/.codex/skills`。命令创建其中的 `hypertest-local-task-onboarding/` 并保存私有所有权收据；升级时通过新 runtime 对同一收据和目录执行相同命令。已有自定义同名技能或已改动的受管文件发生冲突时保留原件，不强制覆盖。不默认修改技能目录、Hook 信任、平台绑定或授权。

正式兼容包尚未发布、且用户已授权源码安装时，可按该说明固定**完整 Git SHA**安装匹配源码。记录它是源码安装，不称为新公开 release，不使用浮动 main 或移动旧 tag。复用兼容依赖环境；确需独立依赖目录时才创建新的 venv，不覆盖旧运行时。

```sh
"$local_python" -m pip install \
  "hypertest-one[interactive] @ git+https://github.com/ZhangLiangchen/hypertest-one.git@$local_source_sha"
```

`local_python` 是选定运行时解释器，`local_source_sha` 来自当前兼容性核验。不要把某次接入的 SHA 当成永久推荐版本。安装器读取既有私有 client config，不调用旧 setup、设备配对或授权签发入口。

## 2. 安装或升级所有权配置

已有安装收据时优先 `upgrade-owned`，保留所选 host/client/hook 配置、Hooks 状态和产物策略：

```sh
"$local_python" -m hypertest.local_sync upgrade-owned \
  --directory "$local_install_directory" --harness codex \
  --version "$local_install_version" --python "$local_python"
```

首次安装使用官方 `install`，先检查其 `--help` 与当前 CLI 一致。下面仅演示当前 Codex Hooks + 原生 MCP 路径：

```sh
"$local_python" -m hypertest.local_sync install \
  --directory "$local_install_directory" --harness codex \
  --host-config "$local_host_config" --client-config "$local_client_config" \
  --version "$local_install_version" --python "$local_python" \
  --hook-config "$local_hook_config" --enable-hooks \
  --harness-version "$local_harness_version" --workspace "$local_workspace"
```

- 当前源码的新 BIND caller 只实现 Codex CLI `0.144.6`；`local_harness_version` 必须来自真实宿主探测和兼容表，不是为通过检查而伪填的值。未来版本以实际实现和 capabilities 为准。
- `local_host_config` 是选定宿主的 MCP 配置；`local_hook_config` 必须核对宿主实际发现的 Hook 源，不能仅由 cwd 拼路径。`local_workspace` 是 policy 与真实生命周期 cwd 一致的工作区。
- `--workspace` 默认只批准 `analysis.md` → TEST_PLAN，DRAFT/NOT_RUN。需要其他槽时改用互斥的 `--artifact-source "$local_artifact_policy"`，不要把两者同时传入。
- 私有 policy 格式由 [`ArtifactSource`](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/sources.py) 定义：`workspace`、完整 `initial` Task 标量、`artifacts`。每个槽只选一个非隐藏 Markdown 文件名；至多一个 TEST_PLAN，每个 TEST_REPORT 明确 `key/title/reported_result`。不要把 cases 或 Task ID 当成 policy 槽字段。
- 新安装保留原有 MCP 与 BUGate 等 Hook 组。遇到已拥有片段冲突，保留并排查，不覆盖其他会话修改；回退也保留凭据、源产物及账本。

## 3. 诊断实际 runtime

```sh
"$local_python" -m hypertest.local_sync doctor \
  --directory "$local_install_directory" --harness codex
"$local_python" -m hypertest.local_sync capabilities --config "$local_client_config"
```

升级配置后，只有确认该 profile 没有其他有效 writer 使用，才通过官方入口停止旧解释器的 transport，再按宿主标准流程重载：

```sh
"$local_python" -m hypertest.interactive_client stop --config "$local_client_config"
```

这个 stop 不删除配置、state 或 journal，也不等于停止 SUT 或关闭聊天。不为强制装载而中断其他 writer。重载后同时核对实际宿主工具目录与 daemon capabilities：

| 检查 | 必要内容 |
| --- | --- |
| 工具 | `hypertest_bind_task`、`hypertest_get_task_binding`、`hypertest_sync_task`、`hypertest_get_task` |
| GET schema | 支持独立的 `task_id` 选择器 |
| Local 能力 | `local_capabilities.explicit_task_binding` 及 `task_binding_callers` 与当前宿主匹配 |
| 配置 | profile 的 Project、host、workspace/policy、运行时解释器及私有 state 一致 |

只按需使用这四个管理工具；列出 legacy 工具不表示 `task:sync` 授权执行。`doctor` 的 `CONFIGURED_UNACCEPTED`、`RELOAD_AND_NATIVE_PROBE_REQUIRED`、`NOT_OBSERVED` 是实际边界，不手动改成 READY。

## 4. Hooks 与真实 root

核对 SessionStart、PostToolUse、Stop、SubagentStop 的配置、实际发现源、启用和信任。Codex 的标准 `/hooks` 可检查和信任当前定义；定义变化后需重新审阅，不能手改 trusted hash。信任流程及 compact 后 SessionStart 见[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)。

MCP 已加载不等于 SessionStart 已发生。按[故障恢复](troubleshooting.md)让**同一正确主会话**经过真实宿主生命周期，随后只读核验其私有 root 的 identity、workspace、policy digest 与 artifact directory。MCP-only 可见工具不能代替这一步。SessionStart 入口内部返回 `BOUND` 只表示本地 source 登记，不能当作平台 Task BIND 回执。

在所选私有 config 的 `state_dir/local-sync/native-sources/<source_key>.json` 中定位宿主实际生成的登记；读取它给出的 artifact directory，不自行计算 key 或创建替代路径。按[私有文件实现](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/interactive_client/security.py)核对：登记是当前 OS 用户拥有的普通文件、非 symlink，目录亦由该用户拥有且非 symlink，文件/目录均无 group/other 权限；实现新建时分别使用 0600/0700，已有项的检查不是要求模式逐位恰好相等。随后将登记的 Project/provider/session、workspace、policy digest 和 artifact directory 与当前真实父会话及已选 policy 全部核对；异常时保留现场，不手改登记“修复”。

新 BIND 及手动绑定 Task 的显式新 SYNC 需要实际 MCP 调用 `_meta.threadId`，它由宿主注入，经私有 IPC 与 root 核对；不能放进 arguments。当前 CLI `bind-task` 没有该原生 context，不能作为替代绑定通道。Claude Code/DeepSeek 当前未实现此新 caller 路径；旧 auto 任务 resume、授权 GET 和原 key 恢复是另一个兼容范围，不能用旧三宿主矩阵推导新绑定支持。

源码入口：[`local_sync` CLI](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/__main__.py)、[安装器](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/installer.py)、[MCP caller 适配](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/interactive_client/mcp_server.py)。
