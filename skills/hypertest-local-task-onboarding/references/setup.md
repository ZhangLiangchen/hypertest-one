# 安装与宿主核验

在首次接入、升级或工具能力不符时读本文件。以下变量均须换成用户实际选择的绝对路径或已核实版本；不把占位内容直接执行。

## 1. 一个入口完成安装和升级

优先使用平台项目页「接入本地模式」或任务页提供的**一条安装/升级 Prompt**。该 Prompt 固定官方 `update-local.py` 的发布地址及 SHA-256；执行前验证摘要，再由 updater 从指定 `stable` / `candidate` 通道选择已公开、匹配本机 Python / OS / 架构且支持更新协议的目标。不要把下载脚本旁边临时取得的同源摘要当作预先可信的摘要，也不要执行浮动 main 上的未固定脚本。

默认私有根目录为 `~/.local/share/hypertest-local/<宿主>`，安装收据位于其 `host-installation`。先只读这个已知受管位置；原安装位于其他位置时，给 updater 的 `--directory` 传入真实收据目录，不全盘扫描，也不读聊天或认证目录。已有收据中的 client / host / Hook 配置、工作区策略、私有身份、state、journal、未决 key 全部保留。不要用首次 `install` 代替已有安装的 `upgrade-owned`，也不要因未传 `--enable-hooks` 而关闭原 Hooks。

首次安装复用目标 Project 已有的私有 `task:sync` profile，以 `--client-config` 和 `--host-config` 传入实际绝对路径；DeepSeek 还需要已有的 `--dsh-home` / `--profile`。只在授权配置或旧安装位置实际缺失时向用户索取该信息，不申请 Operator key、签发 grant、复制模型登录或新建凭据。缺兼容 Python 时先复用已有环境或工具管理器；只在已授权范围内进行用户级安装，不改系统 Python。

平台可复制的命令同时适用于首次安装和升级；`--check` 只检查远端发行元数据和本地收据，不修改安装。`candidate` 必须明确选择，不能因稳定通道没有目标而悄悄切换。当前 `local-v0.1.1-rc.2` 是新增 updater 与 ADR-026 的候选发行；安装成功不升级真实宿主资格。旧 `local-v0.1.0` / `local-v0.1.1-rc.1` 的 tag、摘要及历史证明保持原样。

通过 updater 的 `--skills-directory` 选择宿主标准技能父目录，例如 Codex 的 `~/.codex/skills`，在同一次操作中安装或升级包内指南。它仅更新私有收据拥有的未改动文件；同名自定义技能或受管文件已改动时保留原件并报告冲突。不要把更换 runtime 当作指南已更新。已有 runtime 也可用 `hypertest.local_sync install-skill --directory <收据目录> --skills-directory <已选技能目录>` 单独管理指南。

仅在没有满足需求的公开目标且用户已授权源码安装时，使用完整不可变 Git SHA 的源码路径；记录为源码安装，不把某次 SHA 写成永久推荐值，不移动旧 tag。复用兼容依赖环境，不覆盖原运行时。

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

官方 updater 会检查运行时身份并通过受控停止流程切换旧 transport；无法安全停止时明确阻塞，保留收据与账本。不要只凭 socket 可连接或配置里的版本推断已升级。手动排障需要停止 transport 时使用官方入口，再按宿主标准流程重载：

```sh
"$local_python" -m hypertest.interactive_client stop --config "$local_client_config"
```

这个 stop 不删除配置、state 或 journal，也不等于停止 SUT 或关闭聊天。不为强制装载而中断其他 writer。重载后同时核对实际宿主工具目录与 daemon capabilities：

| 检查 | 必要内容 |
| --- | --- |
| 工具 | 绑定/同步四个工具，以及协作所需 `hypertest_join_task`、`hypertest_contribute_task`、`hypertest_publish_task`、`hypertest_get_task_collaboration` |
| GET schema | 支持独立的 `task_id` 选择器 |
| Local 能力 | `local_capabilities.explicit_task_binding` 及 `task_binding_callers` 与当前宿主匹配 |
| 配置 | profile 的 Project、host、workspace/policy、运行时解释器及私有 state 一致 |

只按实际任务合同使用上述管理工具；列出 legacy 工具不表示 `task:sync` 授权执行。`doctor` 的 `CONFIGURED_UNACCEPTED`、`RELOAD_AND_NATIVE_PROBE_REQUIRED`、`NOT_OBSERVED` 是实际边界，不手动改成 READY。

## 4. Hooks 与真实 root

核对 SessionStart、PostToolUse、Stop、SubagentStop 的配置、实际发现源、启用和信任。Codex 的标准 `/hooks` 可检查和信任当前定义；定义变化后需重新审阅，不能手改 trusted hash。信任流程及 compact 后 SessionStart 见[官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)。

MCP 已加载不等于 SessionStart 已发生。按[故障恢复](troubleshooting.md)让**同一正确主会话**经过真实宿主生命周期，随后只读核验其私有 root 的 identity、workspace、policy digest 与 artifact directory。MCP-only 可见工具不能代替这一步。SessionStart 入口内部返回 `BOUND` 只表示本地 source 登记，不能当作平台 Task BIND 回执。

在所选私有 config 的 `state_dir/local-sync/native-sources/<source_key>.json` 中定位宿主实际生成的登记；读取它给出的 artifact directory，不自行计算 key 或创建替代路径。按[私有文件实现](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/interactive_client/security.py)核对：登记是当前 OS 用户拥有的普通文件、非 symlink，目录亦由该用户拥有且非 symlink，文件/目录均无 group/other 权限；实现新建时分别使用 0600/0700，已有项的检查不是要求模式逐位恰好相等。随后将登记的 Project/provider/session、workspace、policy digest 和 artifact directory 与当前真实父会话及已选 policy 全部核对；异常时保留现场，不手改登记“修复”。

新 BIND 及手动绑定 Task 的显式新 SYNC 需要实际 MCP 调用 `_meta.threadId`，它由宿主注入，经私有 IPC 与 root 核对；不能放进 arguments。当前 CLI `bind-task` 没有该原生 context，不能作为替代绑定通道。Claude Code/DeepSeek 当前未实现此新 caller 路径；旧 auto 任务 resume、授权 GET 和原 key 恢复是另一个兼容范围，不能用旧三宿主矩阵推导新绑定支持。

ADR-026 协作同样只支持上述 Codex `0.144.6` 逐调用来源路径，新 JOIN/CONTRIBUTE/PUBLISH 不扩展 Claude/DeepSeek 资格。服务端能力需明确包含 `local-task-collaboration/v1alpha1`；实际客户端需可见 `hypertest_join_task`、`hypertest_contribute_task`、`hypertest_publish_task`、`hypertest_get_task_collaboration`，且报告相应 Local 能力。旧 `local-v0.1.0` / `local-v0.1.1-rc.1` 资产不包含本轮新增协作代码，不修改原 tag、digest 或三宿主验收记录。源码客户端、独立发行和真实宿主验收分别记录，不能仅凭远端工具目录宣称本机具备新能力。

源码入口：[`local_sync` CLI](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/__main__.py)、[安装器](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/local_sync/installer.py)、[MCP caller 适配](https://github.com/ZhangLiangchen/hypertest-one/blob/main/src/hypertest/interactive_client/mcp_server.py)。
