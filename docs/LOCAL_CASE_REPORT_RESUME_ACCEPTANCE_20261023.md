# Local 用例、原始报告与 headless / resume 真实验收（2026-10-23）

**状态：三宿主必需矩阵独立复核通过（PASS_WITH_EXPLICIT_LIMITS）；产品 runtime 未修改。PR23 尚未因此合并，生产 Web 尚未部署。**

本次使用已经公开的 [local-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.0)，没有修改产品 runtime / adapter。发行源码为 `874569fa566a137eba77ac4852caa6052cb04a17`、Local source digest 为 `a5db7a7cc5058bd5fc9162c056f2b8d93c41bf18d6975879a334bbc611d56d8a`，正式 wheel SHA-256 为 `a226e64a64f9c93a705e0139c0218f61cd804a3a562225d5bdbdf44984bf41d3`。证据补充不改变旧 tag、四资产、manifest、R5/R6 日志或旧 MCP release / latest。

## 目标、流程与判定

目标仅为 macOS arm64 / CPython 3.13.3，首发稳定目标仍为 `darwin-arm64-py313`；Linux x86_64 / Python3.12 仍 CANDIDATE，其他宿主版本不扩承诺。使用新 Project 与三份独立 client 的 `task:sync` 临时授权，不复用上轮已撤销 grant。

这是 HyperTest 开发的管理链路 fixture，不是业务 SUT 测试。`BLOCKED / FAIL`、case actual / FAIL 与报告 FAIL 均为明确批准的保全数据，业务 SUT 执行为 `NOT_RUN`。Hooks 不从 Stop 推导完成或 PASS，source binding 不认证当前 MCP 调用者。

判定要求真实无交互宿主进程产生事件与正式产物，原生 MCP 接受完整 case/task 请求，进程关闭后通过精确已观察 native ID 再起新进程恢复同一会话，修改计划后保全 case/report/task FAIL，核对每个原 key 回执与每一固定接受版本的全部分页/原文/hash。无变化 Stop/SessionEnd 不产生额外自动版本。原生宿主持有的会话历史只为正常 resume 保留，不扫描或上传聊天。

## 实际矩阵

| 宿主 / 后端 | 已观察结果 | 精确边界 |
| --- | --- | --- |
| Claude Code 2.1.218 / 官方 DeepSeek Anthropic-compatible backend | PASS：headless 首轮真实文件 Hook；两次精确 `--resume`；v1–v4 原 key / 全页 / 原文核验；1 case、1 report / FAIL 保全、pending0 | 首轮 0 MCP 调用；第一次 resume 才显式补齐 case/task FAIL，不能倒写为首轮已完成；第二次 resume 只改计划 |
| Codex 0.144.6 / gpt-5.6-sol | PASS：`codex exec` headless、实际 MCP get/sync/get、真实 `exec resume <observed ID>`；v1–v3 全部固定版本读回、case/report/task FAIL 保全、pending0 | 单会话正常持久化，无 fork/--last/ephemeral；标准 Hooks trust 与窄 read/write MCP 许可单独配置，不以安装替代许可 |
| DeepSeek CLI 0.1.5-rc.1 / 组件0.1.5-rc.2 / 官方 deepseek-flash | PASS_WITH_EXPLICIT_LIMITS：真实官方 headless CLI 单次启动；持久 Registry API 新进程恢复同一 source；v1–v4 原 key/全页/原文核验，1 case、1 report / FAIL 保全、pending0 | resume 是验收专用有界驱动调用官方 `agents.resume`，不是 CLI / SDK wire flag，未交付通用恢复 CLI；保留官方先 read 再覆盖已存在文件的要求 |

Claude / Codex 原证明的 `review_status=PENDING_INDEPENDENT_REVIEW` 是生成时状态，逐字节保留。后续独立只读复核通过的资格单独写入[聚合矩阵](local-acceptance/local-matrix-20261023.json)。独立复核另外以正式 ApiClient 查询原 key、每页512字符读回 Codex v1/2/3 与 Claude v1/2/3/4，核对所有冻结请求、source/owner、case七字段、792B Markdown报告原字节及0pending；两宿主39份原件成员hash一致。原执行方使用128字符强制分页；两次读取分别留证，不混淆其页数。

两个宿主都以每次 CLI subprocess 被 spawn 并 await close 后再启动下一次 exact-ID resume 证明进程边界，未记录数字 PID，不声称有该字段。报告原文含 Unicode、空行、代码围栏与末尾标记；hash/完整分页证明字节保全，不能证明 SUT 行为通过。未新增一次重复完整 snapshot 提交；无变化抑制证据来自真实生命周期回调。

- [Claude Code 原始公开观察](local-acceptance/claude-code-matrix-20261023.json)，SHA-256 `e6a60ecbe7d3729d5836ba6ecece05ac5008610c23534c372cf09c3752e621f0`。
- [Codex 原始公开观察](local-acceptance/codex-matrix-20261023.json)，SHA-256 `e0f2f07816c329209eae07562ce99d47ad05b48d3df40c8144043047a454d85c`。
- [DeepSeek 原始公开观察](local-acceptance/deepseek-native-matrix-20261023.json)，SHA-256 `01a5ba99f44601d63381f2bf9b382529c0a6dffd86cbc6013a7eb359c7322685`。

## DeepSeek 的精确恢复与失败保留

官方 headless bundle `@deepseek-ai/dsh-headless@0.1.5-rc.2` 实际 PID 14187，单 turn 退出0并 flush 原生历史；最终恢复为新 PID 23262，官方 `agents.resume({resumeSessionId,agentOptions,setup})` 恢复同一 source，seq89→116，退出0。它没有 create fallback，不重建来源，不复制模型登录。只有获准 analysis 的 read→write 成功后，Hook 才接受v4；v1/v2/v3与原件历史保持，平台v4 `IN_PROGRESS / FAIL`、case/report FAIL和339B原Markdown报告 SHA不变。

原两次 setup 准备失败、两次 write `is_error` 和当时Taskv3均保留；未捕获的 filesystem错误码保持 `UNCLASSIFIED / NOT_CAPTURED`，不能倒填为具体 observed error。官方静态 filesystem guard解释了修订运行规范时为什么必须允许先read，但不是旧错误码的回溯证据。历史 marker 的连续性来自另一次真实恢复的失败 write 参数，最终成功覆盖严格走read-before-write，不声称首次write-before-read成功。

DSH独立只读复核28份证据成员、四个原key与v1–v4各3/4/5/5页（512字符）；最终完整文档 SHA-256 `4799982cea821ddcb4b47413eb9e9d3e10cbaedf408106e4994bbef543eeb03f`。明确限制：Stop产品handler次数未单独插桩；不新增主动故障UNKNOWN覆盖，不新增通用resume命令。独立复核收据SHA `253f3724644297ae8ec2e08408c4a5110558b2bb6fd142bc446b612c34783d68`，原件只在私有验收材料中保留，公开聚合仅含allowlist字段。

Codex最初一次CLI在任何session/event前退出，原stderr未保留，精确根因仍未知。后次在外部非Git fixture工作区使用文档所述 `--skip-git-repo-check` 后完成，不能倒填为首次失败的已证实错误。此次没有重验child边界；0.1.0 R6的独立真实child证据保持单独历史。Claude首轮漏用MCP也不据此认定adapter权限缺陷。

生产 Web 的实际发布与保全将在部署后另记 `LOCAL_WEB_PRODUCTION_DEPLOYMENT_20261023.md` 及脱敏JSON；当前不创建虚构的已部署记录。

## 后续 gate 与部署边界

三宿主最终证明及独立复核已齐备；本次只冻结聚合矩阵/文档和 Web 文案，接着运行 exact-head 完整 CI。CI 与最终 source review 通过后按 root 的验收 gate 合并 PR23，执行 Web-only 发布。当前没有发布新二进制或修改0.1.0资产。若必须修产品 runtime，则新 source digest/wheel 和三宿主重新资格必需，不能用这组旧包证据证明改后包。

生产验收须实际交互项目页：三宿主切换、私有路径占位符与授权确认、默认 MCP-only 和显式 Hooks 共六命令、固定tag/完整源码/三摘要、DSH host-config 派生、已有 SessionTask 详情。远端内部 GET-only 浏览器与 Mac 标准 CA/VPN来源 HTTPS分别核验，不把 HTML200、CI或内部浏览器称为公网浏览器 E2E。部署后另记实际 Web commit/image 与保全/回退结果。
