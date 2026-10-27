# 剩余 TODO 跟进交付（2026-10-23）

2026-10-27 CLI 项目授权简化：移除旧 ACTIVE 身份下拉框，新批准仅核对短码、项目、权限和有效期；服务端用不可变映射解析专用CLI actor，保留原授权/任务/回执。相关实现和定向检查已完成，部署状态见[本轮交付](CLI_PROJECT_AUTHORIZATION_DELIVERY_20261027.md)。

2026-10-27 CLI HTTPS 排障：确认服务由自有 Connector CA 直接签发，无缺失中间链；默认系统信任复现失败，显式 CA 验证通过。提供 CA 公共证书、固定摘要和命令级信任配置，见[修复指引](CLI_TLS_TRUST_20261027.md)。未改服务私钥/访问限制或发起配对，本机验证与原请求恢复待用户执行。

2026-10-27 CLI 安装体验：本轮把新 CLI 的推荐安装入口改为“复制 Prompt，交给本机 Agent”。页面 Prompt 带明确平台/项目，通用发行 Prompt 先安装再在需要时询问平台；复用固定 cli-v0.1.0 与两个摘要，安装 Skill 并发起配对，网页批准仍由用户完成。README 与[授权指南](CLI_AUTHORIZATION_GUIDE.md)同步，旧 Local 安装指引标为历史。**Web 已按 Git `8b90efb878c51568c9e35901ad31116b742a5f7f` 部署；发行说明与中英文 Prompt 附件已公开并核验，定向检查、构建和部署健康通过。** 精确状态见[Prompt 安装交付](CLI_PROMPT_INSTALL_DELIVERY_20261027.md)；不重建 CLI 包，不自动测试或上传，USER_OWNED 验收未执行。

2026-10-27 Local 实施：按已确认的 ADR-027 完成独立归档 API/模型、CLI 配对授权、全局 CLI/显式 Skill、PC Web、受管旧配置清理及旧 Local 新写退休；保留原 key 只读恢复、旧浏览器未决 CREATE、来源与历史语义。相关定向自测已完成，结果按模块分别记录于[本轮归档交付](LOCAL_ARCHIVE_DELIVERY_20261027.md)，不重复累计。**API/Web 已按 Git `1512d11f99c5e500e4fc56c685410ffa9e533530` 部署、schema0031，五容器及新授权 BFF 只读路径健康；cli-v0.1.0 已公开。USER_OWNED 业务验收未执行。** 下段“纯文档”是此前方案阶段记录，不再表示当前源码未实施。

2026-10-27 Local 重构方案：用户已确定由 MCP/Hooks 同步转为测试后显式 Skill/CLI 归档。[ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)与[开发计划](LOCAL_ARCHIVE_REFACTOR_PLAN_20261027.md)记录改造原因、新 Task/Subtask/Submission 模型、独立权限、CLI/Skill、旧入口退出及历史恢复；四份基础文档添加目标合同。本轮补充[CLI 授权操作指南](CLI_AUTHORIZATION_GUIDE.md)：全局授权页、一键绑定、用户级 profile/Skill、明确项目授权，上传必填 Project/Task、可选 Subtask，省略时写任务根空间；同步根/子任务版本及授权原 key 恢复合同。**本轮为纯文档交付，产品实现未开始**，未移除正在使用的配置、未部署新接口、未发行CLI或执行用户验收。后续工作按当前TODO的归档重构项推进，下方已交付版本和历史资格保持。

2026-10-26 正式发行：按用户要求将最新 rc.2 功能发布为 `local-v0.1.1`，GitHub Latest 已指向该正式版，stable updater 已能发现。六份公开资产、Mac/Linux发行构建及相关自测通过；正式发布与宿主验收分别记录，旧候选/验收原件不改写。精确源码、摘要和状态见[正式发行记录](LOCAL_STABLE_RELEASE_20261026.md)。本轮不改服务器部署镜像/数据库，不开展模型、SUT或用户验收。

2026-10-26 Local 更新：PR #26已合入main；一条命令/Prompt的安装与升级已实现，local-v0.1.1-rc.2候选公开，Web按df5155b部署。自动识别收据、保留Hooks/授权/账本、真实daemon版本检查与公开入口合成安装/升级回归通过。实现、发行摘要、CI与镜像见[本轮记录](LOCAL_ONE_COMMAND_DELIVERY_20261026.md)；API/Worker/schema身份保持，真实宿主验收仍USER_OWNED。

2026-10-26 多会话后续：用户已要求实施[ADR-026](architecture/ADR-026_MULTI_SESSION_TASK_COLLABORATION.md)，首片源码连通同一 Local 任务的多真实root授权/JOIN、独立贡献、单一主会话汇总、交接、MCP与PC详情；领域 §50.6/TMP §45.5 与初始绑定兼容同步更新。自动回归、迁移、部署及镜像见[本轮交付](MULTI_SESSION_LOCAL_DELIVERY_20261026.md)，旧公开Local包/宿主资格不升级；未执行模型、SUT或用户功能验收。下方API/Worker/Web身份保留其原轮次，最新部署以新交付记录为准。

2026-10-26 Local 后续：按用户本轮更新接入包的指令，PR #25 已审查合入，Skill 已纳入 `local-v0.1.1-rc.1` Mac/Linux公开候选包并增加显式安装/升级；80项相关回归、代码CI及发行构建通过。精确源码/摘要与下载见[本轮交付](LOCAL_ONBOARDING_SKILL_DELIVERY_20261026.md)。新版宿主验收仍USER_OWNED/NOT_OBSERVED，旧正式发行和下文API/Worker部署身份保持原义。

本轮继续既有授权范围内的开发，不重复P0-1/P0-2或PowerContext集成；完整处置见[当前TODO](TODO.md)。新API能力默认关闭，没有为任何Project增加授权、凭据、Task或经验，不运行真实模型/SUT。功能验收保持USER_OWNED。

## 核对与实现

开始时工作区干净，文档HEAD为bb2ee77。只读核对API/Web镜像与Cloud ops-current，实际来源仍为`e28d23cd58cd868a9a672be9f9ab6f608416c5c7`，schema0027，五容器healthy、Cloud Worker active；legacy Worker保留55de50e。P0和Memory原交付与验收状态不升级、不覆盖。

本轮新增[ADR-025](architecture/ADR-025_CLOUD_CONTROLLED_HTTPS_READS.md)的HTTPS_CONTROLLED_API_V1公开只读目录、严格TLS/public-IP pin、受限UDS、canonical不可变SENT/观测、原key/UUID只读恢复、UNKNOWN/HELD收尾阻断；与SSH原检查复用而不改写固定诊断状态机。FRAMEWORK_LOCKED_V1在prompt前核原锁文件与固定Python/Node版本/摘要，只读、不安装或执行项目入口。新增0028两表为additive，不改任务/报告/旧回执。TMP§50、领域§55和架构§49同步更新。

Local caller官方源码研究维持已核Codex路径和unsupported宿主拒绝，没有虚构新兼容；见[具体来源](LOCAL_CALLER_FOLLOWUP_20261023.md)。SDK续接/SUT CI/一般SSH/Cloud Claude分别设计并记录真实缺口，未实现的执行能力不标完成。平台回归CI只补原有完整测试未覆盖的安装轮廓/SDKmetadata/ops lint，不创建新secret或部署权限，不手动触发远端Actions，不将静态检查称为远端CI PASS。

## 相关自动化回归

最终组合9文件：HTTP broker/transport、实际TLS、DB authority、HTTP runtime、原Worker runtime、framework runtime、迁移链、Cloud tasks与SSH authority，**202 passed / 1 skipped，27.88s**。跳过项是既有可选DeepSeek SDK环境缺包，不计通过。不是全量pytest，也不是真实模型/业务测试。

随后仅为HTTP live投影补充SENT原意图/UNKNOWN观测的区分与无正文断言，DB authority 17项再次通过；与上行重叠，不另加总。Runtime schema也拒绝新profile的重复入口声明，旧profile不改历史序列化。

该组合包含独立开发轮次的HTTP62项（含3项真实回环TLS）、DB authority17项、框架35项等，不能把不同轮次数相加当成新覆盖。真实TLS以临时CA与test-only TCP映射验证原hostname证书、错误hostname及不可信CA；不放宽runtime公开IP规则、不访问外网SUT。

DB定向开发首次12通过/1失败，发现合法OBSERVED的lease字段误用；修后追加约束时15通过/1失败，发现NULL metadata可绕过守卫，均已修复。中间新增原绝对deadline要求造成旧fixture5通过/9失败，随后对齐fixture；HTTP runtime首轮2通过/6失败为异常code断言与UUID fixture错误，已修正。最终上述202通过覆盖这些修正，不把中间失败改称首次全通过。

最终0028 migration在独立空临时库从0001全链成功。测试只用本轮专用tmpfs PostgreSQL，不接线上库；Ruff改动范围和diff检查通过，CI YAML/inline Python静态检查通过。没有新Web修改，无重复Web构建或全量回归。

## 部署

代码已推送main，服务器fetch后固定完整SHA `76edb01a985b484bb1d1e1a88fcadd44b7a3532b`，从干净源码构建API和Cloud Worker；本记录部署后补充为纯文档变更，不重建镜像。Web与legacy Worker保持各自现有镜像身份。

| 项目 | 固定身份 / 结果 |
| --- | --- |
| API | `sha256:070fabb665246d108c33091ddb0f76bdaf5c761ed6e39044edcfbaaacd1b0b19`；revision为上述76edb01完整SHA |
| Cloud Worker | `sha256:2ec7dc863f544fe64ea41cdb6ef65c010218b96ace85704998f01eb62473adc3`；release `/opt/hypertest-cloud/releases/76edb01a985b484bb1d1e1a88fcadd44b7a3532b`；manifest SHA-256 `4b9b66788657c19830ccae71bad8c556b9640bfd75f6fd92cb5c5454817d43ff` |
| Web | 保留`e28d23cd58cd868a9a672be9f9ab6f608416c5c7`，image `sha256:0e534f0f93c8029087216a948538804544692484f2d9c4d03c0d9e2dbe9f0d16` |
| legacy Worker | 保留`55de50e215961ee4a1061b32f86670bd23259324`，image `sha256:ff650c8a9f59d311f51614a3183f4327bd1125f4d9e6edd511b8b7ff96e3bf4c` |
| 迁移与保全 | 线上0027→0028成功；迁移前`pg_dump -Fc`为1,650,580 bytes；新HTTP两表均0行，未创建线上fixture |
| 健康 / 关键只读路径 | 五容器healthy、独立Worker active；API health、Web根页、Memory setup及Cloud BFF capabilities均HTTP200 |
| 能力展示与开关 | API/BFF implemented HTTPS=true，但configured=false；运行Worker进程的HTTPS开关false；resume_supported=false、reconcile_supported=true |
| 访问边界 | ingress guard protected；原TLS/VPN/SSH及Memory配置、grant目录保持；没有新目标授权、新凭据或真实模型/SUT执行 |

本轮停止并替换API/Cloud Worker，重启nginx刷新上游解析；Web、PostgreSQL与legacy Worker保持运行。Worker经原启动准入，运行进程所见release manifest的source_commit已核对。新HTTPS开关保持false，不改变VPN/SSH/访问限制或Memory权限。新目标启用、新凭据/扩权及新版Local公开发行都需具体授权，不能以常规测试服务器部署代替。

构建后磁盘曾仅余约90MiB。仅对本轮新release中4个与原只读Codex payload逐文件摘要相同的大文件改用硬链接共享，释放458,379,264 bytes；原文件路径、内容和manifest摘要全部保留，旧release/镜像/源archive/数据库/卷/会话/未决journal均未删除，准入校验仍通过。剩余约0.5GiB，**后续构建前需决定扩容或明确可清理范围**；本轮不擅自扩容、付费或清理历史。

部署回执目录为 `/var/lib/hypertest-cloud/delivery/20261023-followup-76edb01a`，含build/deployment JSON、构建/migration日志、before-0028.dump与payload-sharing.json。回归tmpfs数据库仅清理了本轮精确owner容器。基础健康检查已通过，无具体未解决的本轮实现故障后停止，不追加用户验收或恢复演练。
