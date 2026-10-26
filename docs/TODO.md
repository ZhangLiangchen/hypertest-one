# HyperTest One 当前 TODO

更新：2026-10-26（Asia/Singapore）。以本表和链接中的精确范围区分开发、部署与用户功能验收；历史交付原件不重标。本次后续交付见[FOLLOWUP_DELIVERY_20261023](FOLLOWUP_DELIVERY_20261023.md)，PC 界面统一见[原 Web 交付](LIQUID_GLASS_WEB_DELIVERY_20261025.md)，后续优化见[Web 性能交付](WEB_PERFORMANCE_DELIVERY_20261025.md)。

| 项目 | 开发 / 当前处置 | 剩余条件 |
| --- | --- | --- |
| PC 创建任务页显示 | **已修复并部署**；独立面板恢复24px留白，Cloud读取中/失败/空资源分别显示，保留草稿；Web源码d2d329e | USER_OWNED功能验收保留；见[回归与镜像](TASK_CREATE_WEB_FIX_20261026.md) |
| PC 首屏与滚动性能 | **已实现并部署**；AntD SSR样式、静态玻璃、延迟记录/分页、状态/页签轮询及非首屏拆包；Web源码8c18232，正式构建和健康检查通过 | USER_OWNED体感/功能验收保留；合成DOM与JS估算不等于真实PC帧率。见[测量、CI与镜像](WEB_PERFORMANCE_DELIVERY_20261025.md) |
| PC 宽屏全页面视觉统一 | **已实现并部署**；全部8个路由统一 Liquid Glass 导航、标题、内容面板、表格与表单；84项定向回归、构建、桌面视觉修复确认及健康检查通过；Web源码4f54a4f | USER_OWNED功能验收保留；不扩展到移动端/竖屏。见[精确范围及镜像](LIQUID_GLASS_WEB_DELIVERY_20261025.md) |
| P0-1 Web未决请求持久保全 | **已实现并部署**；独立IndexedDB、双标签、原key恢复、固定版本完整读回 | USER_OWNED 功能验收保留；浏览器清除站点数据不能推导未执行。见[P0原记录](P0_RECOVERY_DELIVERY_20261023.md) |
| P0-2 取消、失联与人工收尾 | **已实现并部署**；fence/lease/对账、人工入口、明确SDK恢复不支持 | USER_OWNED 功能验收保留；UNKNOWN/HELD及原件/历史不由声明清除 |
| P1-1 Cloud框架依赖与受控HTTPS | **首片实现并部署，整体部分完成**：FRAMEWORK_LOCKED_V1及公开GET/HEAD目录adapter、canonical账本、原key恢复、Worker/权限集成与合成故障回归；新开关保持关闭 | 真实Project/目标/IP/只读资源/期限/预算尚未授权。依赖闭包与离线安装供应、认证/写API/query/body、其他工具链与浏览器仍待独立开发。未宣称一般框架或真实API任务已通过 |
| P1-2 Local新任务绑定扩展 | **研究与拒绝边界已核对**；Codex保持已核0.144.6路径；Claude/DeepSeek无可信逐调用MCP归因则继续unsupported；不为扩覆盖放宽身份 | 新宿主adapter需要可靠host-native transport证据；Codex真实parent/child绑定E2E仍USER_OWNED/NOT_OBSERVED。新Local发行未执行，旧local-v0.1.0不重标。见[caller核对](LOCAL_CALLER_FOLLOWUP_20261023.md) |
| P2-1 真实SDK原会话恢复 | **独立缺口/设计已记录，未实现**；保持supports_resume=false | 需确定允许续接的非终态、原session/home/workspace、旧prompt enqueue歧义处理、新generation与预算处置。不能删除闭锁直接调用resume或重放prompt |
| P2-1 平台回归CI | **配置补齐**：API最小依赖轮廓、SDK只读metadata、ops lint；原pytest/Web发现规则保留 | 远端Actions结果未在本记录观察，不能称CI PASS；不等于SUT CI执行adapter |
| P2-1 SUT CI adapter | **独立设计已记录，未实现** | 需选择provider/API版本、项目/workflow、runner/环境及触发/读/取消权限、独立凭据引用与预算；不得借Git权限或管理服务器token触发 |
| P2-1 一般SSH | **独立设计已记录，未实现**；固定诊断旧能力保留 | 需明确Cloud可达且允许的目标/host key/非root账户/受限入口/远端manager；XBlock SSH/日志/操作与166dev仍仅Local |
| P2-1 Cloud Claude | **独立设计已记录，PLACEHOLDER保持** | 需云端服务身份来源、endpoint/model/共享预算与精确payload/profile；无新凭据、不复制Mac登录、不从Codex启用推定Claude可用 |
| P2-2 PowerContext Gateway | **已实现并部署**；Project映射、独立权限、候选、人工发布/检索/修订/撤回、Local/Cloud可选接入 | USER_OWNED功能验收保留；各Project grant仍需显式授权/配置，旧grant不自动升级。Local新版安装包未发布。见[集成交付原记录](POWERCONTEXT_INTEGRATION_DELIVERY_20261023.md) |

[P2独立设计与具体所需输入](CLOUD_P2_FOLLOWUP_20261023.md)、[受控HTTPS首片](CONTROLLED_HTTPS_FOLLOWUP_20261023.md)、[框架冻结](FRAMEWORK_RUNTIME_FOLLOWUP_20261023.md)。待授权、未实现与USER_OWNED验收分别记录，不能只因缺少真实目标而把尚未开发的能力写成已完成。

当前API/Cloud Worker部署SHA为`76edb01a985b484bb1d1e1a88fcadd44b7a3532b`，Web部署SHA为`d2d329ef575978e978f7b322a4a4123122688760`，schema0028。先前经用户授权定向清理释放11.63GiB，详见[磁盘清理记录](DISK_CLEANUP_20261024.md)；本轮Web构建后根盘可用约6.2GiB，见[任务页修复](TASK_CREATE_WEB_FIX_20261026.md)。后续开发默认复用现有环境，操作前分别检查根盘与tmpfs实际余量；未授权或用途不明的历史继续保留。
