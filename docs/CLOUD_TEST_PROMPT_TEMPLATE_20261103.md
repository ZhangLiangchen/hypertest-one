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
