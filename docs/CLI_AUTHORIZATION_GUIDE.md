# HyperTest CLI 授权与全局使用指南（规划版）

更新：2026-10-27（Asia/Singapore）。**功能尚未实现，以下页面、命令与操作均为待实现设计，本轮未真实执行。** 架构与任务拆分见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)及[开发计划](LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)。

## 1. 一次绑定，按需归档

Web 提供全局「CLI 授权」入口，集中展示安装/升级指导、发起配对的方法、当前授权及撤销入口。它不属于某个项目工作目录，也不要求先安装 Hooks 或注册 MCP。

完成一次用户级绑定后，同一电脑、同一操作系统用户下的终端和 Agent 可以复用全局 profile；无需在每个仓库或每个会话重复授权。profile 固定 server、client 和 uploader actor，可用于多个**明确获准**的 Project；全局可用不等于全平台权限。其他电脑、用户或服务身份须分别授权，不复制模型登录。

测试期间无需运行 CLI。仅在用户明确要求归档或查看/恢复既有请求时启动一个短命进程；操作结束即退出，无 daemon、localhost callback、后台监听、自动续签或常驻同步。

## 2. 安装或升级官方 CLI

1. 打开 Web 全局「CLI 授权」页，按实际操作系统选择官方 CLI 发行目标。
2. 使用该页提供并可核验版本/来源/摘要的安装或升级方式；本指南不预编下载 URL，也不执行浮动脚本。
3. 将官方 `hypertest` 命令加入当前用户的 PATH，使终端及其启动的 Agent 可调用；不往每个项目复制一份运行时。
4. 执行未来提供的 `hypertest doctor`，检查命令版本、配置及 TLS。尚未绑定应提示下一步，不自动申请授权、创建任务或执行测试。

新安装不修改宿主 MCP/Hooks 配置。旧安装升级按受管收据精确处理自有配置，保留凭据、journal、未决请求、其他配置和用户产物；不覆盖旧发行资产。

## 3. 复制绑定命令并在 Web 确认一次

「CLI 授权」页复制的命令只含服务器地址和 profile 名，不含 token、短码兑换秘密或 Operator key。示例中的地址必须替换为用户自己的服务地址：

```sh
hypertest auth bind --server https://YOUR_HYPERTEST_HOST --profile default
```

可选 `--project-id PROJECT_UUID` 只预选 Web 授权页中的项目，不创建 grant、不表示已经允许上传；用户仍需在页面确认实际项目 allowlist。

配对流程如下：

1. CLI 在任何联网前，于用户私有目录持久保存非秘密 `request_id`、高熵 credential secret、独立 verifier、原 CREATE key 和固定请求；秘密不打印、不交给 Skill 或模型正文。
2. CLI 用 CREATE 发起一次有界配对，只提交 `credential_hash`、verifier challenge、非秘密 client 信息及可选预选项目，冻结配对上下文；随后打开或显示 Web 授权 URL、请求 ID 和短码。无法自动打开浏览器时，用户可手动打开同一 URL。
3. 用户通过现有 Web 登录/访问控制认证，选择**既有上传 actor**，明确项目 allowlist、`archive:read` / `archive:write` 和授权期限；不借此取得 `task:sync`、Cloud、Memory 或 Operator 权限。
4. 用户核对 CLI 与网页短码一致，并一次确认页面列出的 server、client 指纹、actor、项目、scope 和期限。Web APPROVE 使用独立稳定 key，冻结实际 actor、项目 allowlist、scope、授权期限及原 credential/challenge 指纹；批准后不可改写或扩权。
5. CLI 以私有 verifier proof 和独立 REDEEM key 对固定批准结果兑换一次；该 key 绑定批准结果，不接收扩权字段。随后使用私有 proof 按原 key 只读确认 grant、client/credential 指纹、actor、项目、scope 和期限是否匹配，不取回明文 token。
6. 核验通过后，CLI 原子保存用户级 profile，显示绑定结果并退出。已有同名 profile 的 server/client/actor 不匹配时不得覆盖，须选择新 profile；同身份下明确已批准的项目可原子合并。正常流程无需复制 token、第二次确认或额外绑定步骤。

CREATE、APPROVE、REDEEM 各自冻结正文/key并保存独立回执，同 key 异输入拒绝。短码只用于核对本次配对，**不是兑换或查询凭据**；request ID、短码、Task ID 或公开 URL 均不能替代 REDEEM/status 所需的私有 proof。长期 secret/verifier 仅由 CLI 私存，服务端保存必要验证材料；Web、命令参数、日志和返回 JSON 不显示秘密。

配对请求有独立的短时有效期，例如 10 分钟；grant 的有效期由页面明确选择，不能把配对窗口误作授权期限。配对过期、明确拒绝与兑换失答分别记录；不自动重新配对、延长期限或扩大授权。

## 4. 超时或 UNKNOWN 的处理

CLI 显示非秘密 request ID 及恢复命令。计划命令示例：

```sh
hypertest auth status --request-id PAIRING_REQUEST_ID --json
hypertest auth reconcile --request-id PAIRING_REQUEST_ID --json
```

这两条命令使用私有 proof，只按各阶段原 key 查询并核对非秘密回执、grant 和指纹，不显示 secret、不发送新写。任一已发送或可能已发送操作的 SENT、UNKNOWN、失答或 NOT_FOUND 均只查询原 key，不能作为“没有执行”的证明；不重 POST、不换 key 兑换、不新建 actor、不重新签发更大权限。已 BOUND 时可核对原固定授权并恢复 profile 保存，同时检查 grant 当前是否撤销/到期。

只有确认前一阶段后，**明确从未发送的下一阶段**才允许使用以下命令首次推进；它不重放已发送或可能已发送的 CREATE/REDEEM，也不把只读 status/reconcile 变成隐式写入：

```sh
hypertest auth bind --resume --request-id PAIRING_REQUEST_ID
```

明确过期/拒绝的请求保留原记录；确需重新绑定时，由用户发起新的明确意图。未决请求尚未查清前不删 journal、配置或私有 credential 来“恢复干净”。

## 5. 全局安装归档 Skill

CLI 与 `hypertest-archive` Skill 使用同一受控发行版本。拟议的 Codex 安装命令：

```sh
hypertest skill install --global --host codex
```

它只向当前用户的宿主标准技能目录安装受管文件，不在每个项目复制 Skill，不安装 MCP/Hook，不把 token 写进技能文件。遇到同名自定义或已修改文件时保留原件并报告冲突。其他宿主只按已验证的支持方式提供安装与显式调用，不从 Codex 支持推定全部宿主可用。

Skill 只在用户明确调用时整理目标与产物、生成 manifest、调用 CLI、解释结果；CLI 负责凭据读取、HTTPS、冻结账本、回执与原 key 恢复。用户无需在测试开始前调用 Skill。

## 6. 每次归档明确提供目标

每次 `archive` 都必须显式传 `--project-id` 和 `--task-id`；`--subtask-id` 可选。profile 不按 cwd、目录名、上次上传或预选项目补齐目标。CLI 核对 Project 授权、Task 归属，以及指定 Subtask 是否属于该 Task。

归档到 Task 根空间的示例：

```sh
hypertest archive --profile default --project-id PROJECT_UUID --task-id TASK_UUID \
  --manifest /absolute/path/archive-manifest.json --json
```

归档到指定子任务的示例：

```sh
hypertest archive --profile default --project-id PROJECT_UUID --task-id TASK_UUID \
  --subtask-id SUBTASK_UUID --manifest /absolute/path/archive-manifest.json --json
```

省略 Subtask 表示 Task 根空间，不创建默认子任务。指定了错误、无权访问或不属于该 Task 的 Subtask 时明确拒绝，不能回退根空间、其他子任务或另建目标。多个获准项目复用同一 profile，仍须逐次填写准确目标。

拟议的显式 Skill 调用可由 Web 复制；子任务 ID 仅在选择子任务时加入：

```text
$hypertest-archive
请将本轮正式测试产物归档，使用 profile default。
目标：--project-id PROJECT_UUID --task-id TASK_UUID
可选子任务：--subtask-id SUBTASK_UUID（归档到根空间时删除本行）
产物范围：/absolute/path/test-results
```

CLI 不接收关键词作为鉴权参数。上传成功只表示资产接受与固定版本完整读回，不推导测试 PASS 或整体完成；UNKNOWN 时继续查询原归档 request ID，不重复上传。

## 7. 查看授权、撤销与本机退出

「CLI 授权」页显示非秘密 client 指纹、actor、项目 allowlist、scope、期限与状态，可明确撤销对应 grant。页面撤销在服务端终止后续授权使用；不删除已接受的测试资产、历史或回执，也不处理其他 grant。

`hypertest auth status` 只显示非秘密授权/配对状态。拟议的 `hypertest auth logout --profile default` 是本机退出：停用该 profile 的本机登录使用，不等同服务端撤销，不影响其他 profile。两种操作均保留 journal、冻结请求与未决 key，不清除 UNKNOWN；退出前提示尚未完成的恢复事项。

授权过期后由用户显式重新绑定，不后台续签。私有文件权限不被宣称为对同 UID 任意代码的隔离；正常使用中，Agent 仅调用 CLI 并读取非秘密结果，不读取或转述凭据文件。
