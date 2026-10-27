# HyperTest One 当前 TODO

更新：2026-10-27（Asia/Singapore）。以本表和链接中的精确范围区分开发、部署与用户功能验收；历史交付原件不重标。本次后续交付见[FOLLOWUP_DELIVERY_20261023](FOLLOWUP_DELIVERY_20261023.md)，PC 界面统一见[原 Web 交付](LIQUID_GLASS_WEB_DELIVERY_20261025.md)，后续优化见[Web 性能交付](WEB_PERFORMANCE_DELIVERY_20261025.md)。

| 项目 | 开发 / 当前处置 | 剩余条件 |
| --- | --- | --- |
| CLI Prompt 安装入口 | **实现进行中**：全局授权与相关项目/任务入口以安装 Prompt 为主，Agent 下载固定 cli-v0.1.0、核验双 SHA、安装 Skill 并引导网页绑定；README/指南同步，原 CLI 包与历史发行身份保持。见[本轮交付](CLI_PROMPT_INSTALL_DELIVERY_20261027.md) | 中英文 Prompt 发行附件/Release 说明、定向检查与 Web 部署完成后记录；USER_OWNED 真实本机安装和授权验收保留 |
| Local 显式 Skill 与 CLI 后置归档重构 | **实现、API/Web部署及cli-v0.1.0公开发行已完成；schema0031**。独立归档 Task/可选 Subtask、CLI 配对授权与全局 profile、显式 Skill、根/子任务归档、PC Web 与原 key 恢复；代码默认退休旧 Local 新写，按收据清理自有 MCP/Hooks/bridge。每次上传必填 Project/Task ID，Subtask 可选。见[本轮交付](LOCAL_ARCHIVE_DELIVERY_20261027.md)、[ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)与[授权指南](CLI_AUTHORIZATION_GUIDE.md) | 部署固定Git 1512d11，公开CLI源d02ab1d；相关回归、构建、迁移及健康通过。USER_OWNED尚未验收；真实本地受管配置清理由用户在明确安装位置执行，不能由服务端切换推定。旧历史/未决key保留，下方旧交付不重标 |
| 旧 Local 一条命令 / Prompt 安装升级（历史） | **当时已实现并部署Web；local-v0.1.1正式公开并设为Latest，现由ADR-027 CLI接入替代**；updater 自动发现渠道/目标、保留原收据配置与Hooks、核对真实daemon、同命令安装Skill；stable发现和两目标发行构建通过。见[正式发行](LOCAL_STABLE_RELEASE_20261026.md)及[实现原记录](LOCAL_ONE_COMMAND_DELIVERY_20261026.md) | 正式发布不升级真实宿主验收，仍USER_OWNED；首次需已有私有Project授权，未知目标/Python明确报缺口 |
| Local 多会话任务协作 | **ADR-026 首片已实现并部署API/Web，schema0029**；ENABLE/精确授权/JOIN/撤销、独立贡献、主会话汇总/交接、固定版本/原key恢复、MCP与PC详情已连通。见[本轮交付](MULTI_SESSION_LOCAL_DELIVERY_20261026.md) | PR #26已合入main，正式local-v0.1.1已包含协作客户端；真实宿主接入/USER_OWNED验收保留；标准A2A adapter、跨actor与跨root私有UNKNOWN自动枚举不在首片 |
| Local 接入 Skill 与新版包 | **PR #25 已合入；Skill已随local-v0.1.1正式公开**；单一技能源码纳入wheel、固定摘要与显式安装/升级。见[正式发行](LOCAL_STABLE_RELEASE_20261026.md)和[原实现记录](LOCAL_ONBOARDING_SKILL_DELIVERY_20261026.md) | 新版宿主验收保持 USER_OWNED / NOT_OBSERVED；旧正式版与候选不重标 |
| PC 任务详情快速导航 | **已实现并部署**；左侧悬浮目录、章节跳转/滚动高亮、用例/报告数量、中英文与键盘导航；Web源码57cb595，32项相关回归、构建及只读浏览器检查通过 | USER_OWNED功能验收保留；见[导航交付](TASK_QUICK_NAVIGATION_DELIVERY_20261026.md) |
| PC 创建任务页显示 | **已修复并部署**；独立面板恢复24px留白，Cloud读取中/失败/空资源分别显示，保留草稿；Web源码d2d329e | USER_OWNED功能验收保留；见[回归与镜像](TASK_CREATE_WEB_FIX_20261026.md) |
| PC 首屏与滚动性能 | **已实现并部署**；AntD SSR样式、静态玻璃、延迟记录/分页、状态/页签轮询及非首屏拆包；Web源码8c18232，正式构建和健康检查通过 | USER_OWNED体感/功能验收保留；合成DOM与JS估算不等于真实PC帧率。见[测量、CI与镜像](WEB_PERFORMANCE_DELIVERY_20261025.md) |
| PC 宽屏全页面视觉统一 | **已实现并部署**；全部8个路由统一 Liquid Glass 导航、标题、内容面板、表格与表单；84项定向回归、构建、桌面视觉修复确认及健康检查通过；Web源码4f54a4f | USER_OWNED功能验收保留；不扩展到移动端/竖屏。见[精确范围及镜像](LIQUID_GLASS_WEB_DELIVERY_20261025.md) |
| P0-1 Web未决请求持久保全 | **已实现并部署**；独立IndexedDB、双标签、原key恢复、固定版本完整读回 | USER_OWNED 功能验收保留；浏览器清除站点数据不能推导未执行。见[P0原记录](P0_RECOVERY_DELIVERY_20261023.md) |
| P0-2 取消、失联与人工收尾 | **已实现并部署**；fence/lease/对账、人工入口、明确SDK恢复不支持 | USER_OWNED 功能验收保留；UNKNOWN/HELD及原件/历史不由声明清除 |
| P1-1 Cloud框架依赖与受控HTTPS | **首片实现并部署，整体部分完成**：FRAMEWORK_LOCKED_V1及公开GET/HEAD目录adapter、canonical账本、原key恢复、Worker/权限集成与合成故障回归；新开关保持关闭 | 真实Project/目标/IP/只读资源/期限/预算尚未授权。依赖闭包与离线安装供应、认证/写API/query/body、其他工具链与浏览器仍待独立开发。未宣称一般框架或真实API任务已通过 |
| P1-2 Local新任务绑定扩展 | **旧合同研究与拒绝边界已核对；新宿主绑定扩展由ADR-027归档路线替代，不再作为新流程待办**。当前已部署Codex仅已核0.144.6；Claude/DeepSeek caller继续unsupported，不放宽身份 | 旧Codex真实parent/child绑定E2E仍USER_OWNED/NOT_OBSERVED；历史发行不升级。已部署新归档；旧来源只读恢复与历史拒绝边界保留，不再扩展旧BIND入口。见[caller原记录](LOCAL_CALLER_FOLLOWUP_20261023.md) |
| P2-1 真实SDK原会话恢复 | **独立缺口/设计已记录，未实现**；保持supports_resume=false | 需确定允许续接的非终态、原session/home/workspace、旧prompt enqueue歧义处理、新generation与预算处置。不能删除闭锁直接调用resume或重放prompt |
| P2-1 平台回归CI | **快速原型阶段改为按需手动执行**：关闭push/PR自动触发，保留workflow_dispatch及原后端/Web/最小API依赖检查；tag发行构建独立保留 | 日常按改动范围做关键自测，手动CI不作为普通交付前置条件；停用自动触发不等于CI PASS，也不等于SUT CI执行adapter |
| P2-1 SUT CI adapter | **独立设计已记录，未实现** | 需选择provider/API版本、项目/workflow、runner/环境及触发/读/取消权限、独立凭据引用与预算；不得借Git权限或管理服务器token触发 |
| P2-1 一般SSH | **独立设计已记录，未实现**；固定诊断旧能力保留 | 需明确Cloud可达且允许的目标/host key/非root账户/受限入口/远端manager；XBlock SSH/日志/操作与166dev仍仅Local |
| P2-1 Cloud Claude | **独立设计已记录，PLACEHOLDER保持** | 需云端服务身份来源、endpoint/model/共享预算与精确payload/profile；无新凭据、不复制Mac登录、不从Codex启用推定Claude可用 |
| P2-2 PowerContext Gateway | **已实现并部署**；Project映射、独立权限、候选、人工发布/检索/修订/撤回、Local/Cloud可选接入 | USER_OWNED功能验收保留；各Project grant仍需显式授权/配置，旧grant不自动升级。Local v0.1.1正式包包含独立可选客户端，真实宿主/Memory功能验收未升级。见[集成交付原记录](POWERCONTEXT_INTEGRATION_DELIVERY_20261023.md) |

[P2独立设计与具体所需输入](CLOUD_P2_FOLLOWUP_20261023.md)、[受控HTTPS首片](CONTROLLED_HTTPS_FOLLOWUP_20261023.md)、[框架冻结](FRAMEWORK_RUNTIME_FOLLOWUP_20261023.md)。待授权、未实现与USER_OWNED验收分别记录，不能只因缺少真实目标而把尚未开发的能力写成已完成。

当前Web部署SHA为`57cb59543a0e1b2102eccb06d917ba4e88bed071`，本轮快速导航构建后根盘余约3.4GiB，见[导航交付](TASK_QUICK_NAVIGATION_DELIVERY_20261026.md)；此前多Agent文案构建后约4.0GiB，见[文案更新](WEB_COPY_DELIVERY_20261026.md)；此前Local入口交付见[Local更新](LOCAL_ONE_COMMAND_DELIVERY_20261026.md)；API保持`66f69f17a249ee382d60096ef9871695be457ee5`，schema0029；独立Cloud Worker保持`76edb01a985b484bb1d1e1a88fcadd44b7a3532b`。此前多会话构建后根盘余约5.2GiB，见[多会话交付](MULTI_SESSION_LOCAL_DELIVERY_20261026.md)。先前经用户授权定向清理释放11.63GiB，详见[磁盘清理记录](DISK_CLEANUP_20261024.md)；此前任务页Web构建后根盘可用约6.2GiB，见[任务页修复](TASK_CREATE_WEB_FIX_20261026.md)。后续开发默认复用现有环境，操作前分别检查根盘与tmpfs实际余量；未授权或用途不明的历史继续保留。
