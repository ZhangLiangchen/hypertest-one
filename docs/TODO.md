# HyperTest One 当前待办

本表只列尚未完成的开发、操作和用户验收。各轮实现、部署和验证事实保留在[历史交付记录](FOLLOWUP_DELIVERY_20261023.md)；日期和提交不代表服务器此刻的运行状态，操作前应核实。新 Local 接入以 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 和 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)为准。

## 用户操作与验收

- Local CLI：真实本机安装、配对、项目追加授权及归档由用户验收；按 [0.1.1 修复记录](CLI_STABLE_KEY_FIX_DELIVERY_20261027.md)处理 Mac 升级和原已接受请求的读回中断。未知请求只按原 key 恢复，不重发。TLS 信任问题见[指引](CLI_TLS_TRUST_20261027.md)。
- Web：Local 任务统一页面、归档 Prompt、授权页面、任务导航与性能等的用户功能或体感验收仍待用户执行；自动回归和部署健康检查不等于用户验收。各轮范围见[历史交付](FOLLOWUP_DELIVERY_20261023.md)。
- Cloud、P0 恢复与 PowerContext：各自用户功能验收仍待用户执行；Memory 项目授权需独立配置，不能由 Local 或 Cloud grant 推定。见[跟进记录](FOLLOWUP_DELIVERY_20261023.md)和[Memory 交付](POWERCONTEXT_INTEGRATION_DELIVERY_20261023.md)。
- 旧 Local：旧版多会话、Codex parent/child 绑定及新版宿主的真实验收维持原记录中的 USER_OWNED / NOT_OBSERVED；旧接入扩展已由 ADR-027 的新归档路线取代，历史合同和原 key 恢复继续保留。

## 未完成的开发与条件

- Cloud 框架与受控 HTTPS 只完成首片；真实目标授权、依赖闭包和离线供应、认证或写 API、其他工具链与浏览器等尚未完成。见[受控 HTTPS](CONTROLLED_HTTPS_FOLLOWUP_20261023.md)和[框架冻结](FRAMEWORK_RUNTIME_FOLLOWUP_20261023.md)。
- 真实 SDK 原会话恢复尚未实现，保持 `supports_resume=false`；需先明确可续接状态、原会话与工作区、旧 prompt 歧义、generation 和预算，不能重放未知请求。
- SUT CI adapter、一般 SSH 和 Cloud Claude 尚未实现；分别需要明确 provider 与独立权限、受限目标及 host key、云端服务身份和模型预算。见[P2 设计与输入](CLOUD_P2_FOLLOWUP_20261023.md)。
- 平台完整回归 CI 为按需手动执行；日常按改动风险做必要检查。未运行不等于通过，发行标签构建单独保留。

源码、部署与验收分别记录；历史实现或已完成工作不重复排入待办。新开发遵循 [AGENTS.md](../AGENTS.md)，服务器操作遵循[运维指南](SERVER_OPERATIONS.md)。
