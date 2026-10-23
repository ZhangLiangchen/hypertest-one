# PowerContext 集成交付（2026-10-23）

**实现完成，部署待执行；功能验收 PENDING / USER_OWNED。** 用户本轮明确授权集成；本记录与[P0-1/P0-2交付](P0_RECOVERY_DELIVERY_20261023.md)及独立[PowerContext服务历史](POWERCONTEXT_SERVICE.md)分开。本轮不创建线上验收Project/Task/经验fixture或验收grant，不触发真实模型/SUT，不导入聊天、推理、raw tool payload或认证目录。

## 已实现范围

API内可选Memory Gateway为唯一上游admin持有者。Project配置映射、私有候选、人工脱敏发布、FTS检索、追加修订、撤回及固定历史读取已实现，页面为 `/projects/{projectId}/memory`。BFF复用现有服务端Operator及严格TLS/UDS，浏览器独立IndexedDB只保存恢复metadata，不与Cloud/Local任务流共用槽。Gateway独立memory权限和四表/版本/原key账本不改任务结果、报告或Cloud HELD。

`0027_project_memory`为additive迁移：新增memory_project_mappings/entries/revisions/operations及历史保护，扩展integration scopes但不自动授予旧grant。候选核固定Local report或Cloud同Attempt asset，非owner仅共享opaque provenance；原报告权限不因发布放宽。人工publish/revise/retract须Operator，非Agent。scope只由服务端Project UUID映射，不能靠填上游scope绕过项目授权。

发布先提交SENT，再单次remember；完整GET原固定revision核scope/family/text/digest后接受。失答/UNKNOWN按原key恢复，未知ID时只读FTS查原marker，不重remember。撤回立即从Gateway可见集排除，旧索引/迟到响应不复活；历史/上游原件不删除。查询只返回当前已发布/未过期集合；每网络阶段总超时≤5秒，故障降级不阻任务同步。

## Cloud / Local 使用

- Local私有客户端profile显式设置 `memory_enabled=true`，另有 `memory_timeout_seconds≤5`；当前源码新增hypertest_query_memory/propose_memory/get_memory_operation。仍需真实Codex父caller及Task绑定；查询无需先有报告，候选必须固定接受来源。其他宿主新调用明确拒绝，原key恢复保留。
- Local既有私有Project integration grant须由Operator显式授memory:read/propose，保留所需task:sync；不复制Operator或上游key，不自动改grant/身份/journal。旧local-v0.1.0和mcp-v0.2.0资产不重打包、不重标，新源码工具不冒称真实宿主验收。
- Cloud经独立私有HTTP broker，Worker注入原claim Task/Attempt/accepted version作为query context，候选仍带固定asset。意图在 `.hypertest-cloud/memory-ready`，安全回执在memory-responses；与正式report handoff/账本分开。
- Cloud逐Project独立memory grant文件由宿主配置的私有目录按规范UUID选择；Agent不能给文件路径或跨Project借token。缺失/撤权/超时只使Memory不可用；不自动签发或继承cloud:work。正常Operator按既有integration API显式授memory:read/propose后，宿主将该Project的token保存在专用只读目录 `<projectUUID>.token`；文件由Worker997:988持有0400/0600，目录0700，不给Agent挂载。

精确HTTP/字段/权限见[ADR-022 §0](architecture/ADR-022_PROJECT_MEMORY_WITH_POWERCONTEXT.md)、TMP§49、领域§54、架构§48。经验命中仅历史参考，不是当前执行证明或操作授权。

## 当前服务与限制

现有独立PowerContext已通过严格CA/IP SAN HTTPS只读health/capabilities读取200，FTS可用，Generation相关false、search_modes为auto/fts；本轮不升级/重启该服务或改其VPN/Xray/SSH/证书配置。管理token仅进入Gateway宿主私有文件与API只读挂载，不进入Web/Worker/Agent、仓库或交付物。

上游固定1.4.0的Atomic Memory文本采用NFC/strip并限8192 UTF-8字节；候选可以更长，人工发布需精简到渲染正文上限。上游remember不提供本平台幂等保证；未匹配/歧义的失答保留UNKNOWN，由有权者调查。浏览器清除站点数据或私密模式结束可能移除其metadata账本，服务端原key意图仍保留。Web有未决Project Memory key时新Memory POST阻塞，包括新的撤回意图；可先恢复原回执或由有权Operator走原API收尾，不影响任务流。

## 回归与部署

| 相关检查 | 结果与范围 |
| --- | --- |
| Gateway + 迁移链最终定向 | 22项Memory及1项迁移链，23 passed；最终0027从0001在空临时库成功 |
| Gateway早期兼容组合 | Memory/既有SessionTask/Cloud/迁移链60 passed；与上行有重叠，不合计 |
| Cloud/Local Memory客户端 | query可用性修订后的10项通过；随后逐Project私有grant目录新增1项通过（不同检查轮次） |
| 客户端早期兼容组合 | interactive/session_task_mcp/cloud_delegation/runtime/handoff等135 passed / 1 skipped；可选SDK缺包跳过，不计通过，不冒称最终整组重跑 |
| PowerContext真实协议adapter（MockTransport） | 13 passed，覆盖scope、固定读回/digest、FTS、丢ACK查询、HTTPS/重定向/体积/秘密错误边界 |
| Memory Web/BFF/持久账本 | 18 passed |
| 既有Cloud服务端auth/TLS transport | 15 passed |
| Memory/Cloud ops overlay与listener | 25 passed，含实际Compose合并；Cloud-only/默认禁用输出保持，Memory-only不依赖Cloud执行配置 |
| 类型检查、改动文件Ruff、差异检查 | 通过；机械UI检测7文件无finding（regex-only，非浏览器验收） |

相关故障回归使用合成fixtures，数据库为本轮专用tmpfs容器，已清理该精确测试容器，无线上数据库/真实PowerContext写入。最终Git/镜像/schema及基础健康在部署后补充；这些结果不是线上功能验收、真实模型或SUT执行。
