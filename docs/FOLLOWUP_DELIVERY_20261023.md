# 剩余 TODO 跟进交付（2026-10-23）

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
