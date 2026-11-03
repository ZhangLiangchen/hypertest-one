# Cloud E2E 测试说明模板（2026-11-03）

创建及草稿编辑表单在“测试说明”下方增加默认折叠卡片，展开可查看和复制中英文模板。MR/PR 地址沿用当前表单，测试环境和草稿保留明确占位内容，复制后由用户填入说明并编辑。复制使用已有 WireGuard HTTP 剪贴板兼容实现，失败时显示手动复制提示；模板展示和复制不修改用户草稿。

模板按测试背景与草稿、测试分析、执行前 subagent 范围审查、执行与完成后闭环审计、完整报告五部分整理。保留用户要求：glab 读取 MR、不偏离 E2E 链路、不擅自扩展范围、逐项说明未执行/跳过/阻塞原因，报告包含一句话总结、用例、执行记录、系统日志或适用的链上证据。审查不可用须如实报告；该模板不是平台已执行审查的证明。

本轮仅新增可选填写辅助，任务名称、MR、prompt 提交和版本/原 key 合同不变，无后端或 schema 修改。模板正文位于 `web/lib/cloud-test-prompt.ts`，使用说明见 [Cloud 指南](CLOUD_TASK_WORKFLOW.md)。

## 检查与部署

- 23 项直接相关的表单和剪贴板回归通过，含中英文模板默认折叠、名称/说明提交和原有 HTTP 复制回退。差异及 Impeccable 机械检测通过。
- 部署提交 `7d59c6ce3a56512ad98e4d28abbb6546e3e24fa1` 已推送，镜像 `hypertest-mac-web:7d59c6c` / `sha256:5fda5a5b9f80ca4ca61995fcd86f2a8c478fb51b2c4f768e0fbd1426ea7afd01`，OCI revision 一致；Web 构建含类型检查通过。
- 仅重建 Web，完整 Compose 链追加 `cloud-test-prompt-20261103/compose.json`；API/BFF/数据库容器与 Worker PID 保持。Schema `0045_local_archive_status`，无迁移；WireGuard/TLS、权限与 Memory 配置未修改。
- Web healthy，指定创建页及 API health HTTP 200。Next.js 将表单抽入共享脚本，已核对实际页面引用及模板内容；无需重建或更改业务代码。
- 本机当前部署清单和 README 已更新。证据在 `~/.local/share/hypertest-mac/cloud-test-prompt-20261103/deployment.json` 与构建/启动日志。

## USER_OWNED 验收

浏览器控制连接不可用，本轮未实际点击展开/复制，也未创建业务任务、读取真实 MR、调用模型或执行 SUT。上述回归和资源交付检查不代替用户页面交互与测试验收。


## 通用模板优化（2026-11-03）

本次仅优化中英文通用模板正文，沿用默认折叠、复制及 MR 自动带入交互，保留任务名称与可选测试说明。具体业务仍由用户填写草稿，模板未写入本次示例的资产、交易类型、环境、MR 编号或费用规则。

- 将 MR 变更点关联到最小必要 E2E 场景、明确断言和证据，为用例分配 ID；明确可观察业务终态，未触发变更行为不能记作该验证点已覆盖。
- 先查项目已有文档、框架和配置，仅就无法确认且影响执行的关键信息提问，不增加表单必填项。
- 两次 subagent 均只读审查，基于 MR/草稿/计划或完整台账/原始证据，意见关联用例或覆盖缺口，由主 Agent 逐项回应。
- 未知写入按原标识查询核对，保留未决状态；用例调整保留原因，跳过、阻塞和未执行分别报告原因、影响及继续条件。

### 实现与部署

- 已推送并部署提交 `73e621aa17e5ce5ba25b1f9de2585747b2e70d73`。
- Web 镜像 `hypertest-mac-web:73e621a` / `sha256:bf7e6097f2df4fbf793af217327ccb693833283277029160b36535bce44bc9a5`，OCI revision 与上述提交一致。
- 19 项相关创建/编辑表单回归通过，差异检查和 Impeccable 机械检测通过；模板静态检查未包含示例业务词。Web 构建（含类型检查）通过。
- 仅替换 Web，完整 Compose 链追加 `cloud-generic-prompt-20261103/compose.json`。API/BFF/数据库容器身份与启动时间保持；schema `0045_local_archive_status`，无迁移。
- Web healthy；创建页面与 API health 均 HTTP 200；已验证创建页实际加载脚本包含新模板文案。
- 部署前发现宿主 Cloud Worker 为 `not running`、最近退出码 `1`；部署后状态相同，本轮未重启或修复 Worker。此现有状态不作为 Cloud 任务可执行的证明。
- 本机部署清单与 README 已更新；证据位于 `~/.local/share/hypertest-mac/cloud-generic-prompt-20261103/` 的 `checks.json`、`deployment.json` 及构建/启动日志。

### 验收范围

本轮复用已完成的相关回归，不重复执行全量检查。浏览器控制不可用，未实际点击展开/复制；未创建业务任务、调用模型或执行 SUT。页面交互及实际测试任务验收仍为 USER_OWNED。
