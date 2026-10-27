# CLI 0.1.1 stable_key 修复与发行

更新：2026-10-27。用户报告的 CLI 0.1.0 缺陷已确认并修复，[cli-v0.1.1](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.1) 已公开。CLI 发行、Web 安装入口部署与本机验收分别记录。

## 问题与修复

`normalize_asset()` 先以 `key` 保存 `stable_key`，随后时间字段循环覆盖同一变量，最终固定写成 `report_created_at`。从原公开 0.1.0 pyz 直接复现：`report-a`、`report-b` 均被归一化为该值。多个同 kind 资产触发本地重复拒绝；单资产或每种 kind 仅一个资产时可能携错误身份提交。

0.1.1 分离 `stable_key`、`origin_key` 和 `timestamp_key`，保留 manifest 中的资产标识。领域 §56.2 和 TMP §51 的 `(kind, stable_key)` 资产身份、重复校验、时间校验、原 key 幂等及固定接受版本读回合同保持，无 API/schema 迁移。

## 发行身份与下载

CLI/tag 源码为 `01b6d1ebcd64326808771ed06ac1166b98cceb6c`，由干净、已提交并推送的 checkout 构建。运行要求 Linux/macOS、Python ≥3.12，无第三方 Python 依赖。六份公开附件已匿名 HTTPS 下载并逐字节核对。

| 附件 | SHA-256 |
| --- | --- |
| hypertest-cli-0.1.1.pyz（39,234 bytes） | `6b258850b14ece41a5489f995e3ca832ea673b575b4859b2649b5992444ad735` |
| hypertest-cli-0.1.1.manifest.json | `f6a96b2224c18af3744103b4d0124e571a3b74c7d1a669bcc3720a1375758de5` |
| install-cli-release.py | `20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95` |
| SHA256SUMS | `5147c65828138000ca7b67aa4728cf8540199f770a22fdc0c182b4f785373494` |
| hypertest-cli-install-prompt.zh-CN.txt | `8290d59ecfaf2d8238a6502c02c27abe25721033c34ec5356bcca324fa9553fd` |
| hypertest-cli-install-prompt.en.txt | `343eb334c186d6cd8a8751d729531b6ba2d367fad74e44cf2d6990f8e4fa000d` |

原 0.1.0 tag、包与所有附件保留，只在发行说明顶部增加缺陷提示与新版入口。安装器逻辑无需修改：它核对受管启动命令并安装到新版本目录，不要求旧 pyz 仍与旧发行摘要一致；新下载包仍须通过固定摘要校验。仓库全局 Latest 保持原发行线状态，页面和 Prompt 明确选择 `cli-v0.1.1`。

## 相关验证

- `tests/test_archive_cli.py` 与 `tests/test_archive_cli_integration.py`：32 passed，包含单资产、同类型多资产、真实重复、所有时间字段拒绝路径、UNKNOWN/幂等/读回篡改检查，以及 Task 根空间和 Subtask 各 1 PLAN + 3 REPORT 的实际 API 接受与完整读回。
- 新增安装器保全/拒绝测试 3 passed；与已有打包/Skill 测试一起运行时为 4 passed，后者已包含在上面的 32 项，不重复累计。
- 中英文安装 Prompt、复制交互与关联页面：13 passed；生成文本一致性与差异检查通过。未运行全量后端/Web 回归或手动 CI。
- 实际 0.1.0 → 临时修补旧包 → 正式 0.1.1 安装升级在 Linux/Python 3.13.5 合成目录通过；新版命令、内置 Skill、实际 pyz 的不同 REPORT key 均核验。旧修补包、原包备份、合成 profile/回执/journal 保持原字节。首次冒烟夹具权限 0755 被 `PRIVATE_DIRECTORY_REQUIRED` 正确拒绝，修正夹具为 0700/0600 后通过。
- CLI/API 集成使用本轮独立 tmpfs PostgreSQL 测试库并迁移至 0032，仅写合成数据；测试完成后容器已删除。没有业务库 fixture、真实模型/SUT执行或用户任务上传。

发行材料与下载核验：`/opt/hypertest/cli-releases/0.1.1/`，包括 `package-smoke.json`、`public-download-verification.json` 和保留的旧发行说明。

## 安装 Prompt 与 Web

`web/lib/cli-release.ts`、中英文安装 Prompt、README 与授权指南固定新版和摘要。Prompt 指导 Agent 升级临时修补过的 0.1.0，保留旧 pyz/备份，复用受管安装位置与既有授权/可信 CA；检查实际 PATH 命中的版本，不改写或重发历史未决归档。

本提交时 Web 部署待执行；完成后在此追加实际源码、镜像与健康结果。API 保持 `006100788751a416b0d6f1dbe8d78c96d3155a5f`、schema `0032_cli_archive_uploader`，固定 ops 和 Worker 无本次变更。

## 本机与历史边界

用户报告其 Mac 临时修补后四资产已被接受，随后完整读回连接中断；这是用户观察，不作为本轮新执行结果。本轮未连接该 Mac、升级其真实安装、查询或重发该请求。连接中断尚待原机器按原 request ID 执行 `hypertest reconcile` 并核对完整接受版本；不能将本次 stable_key 修复宣称为该问题已解决。

新版本不自动重命名历史 `report_created_at` 资产，不猜测已经丢失的原始 key，不改写冻结请求/回执/版本。Mac 真实升级与用户归档验收仍为 USER_OWNED。
