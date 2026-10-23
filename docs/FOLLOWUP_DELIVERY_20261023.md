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

固定Git、API/Cloud Worker镜像、schema及最小健康结果在本轮部署完成后补充；Web与legacy Worker保持各自现有镜像身份。新HTTPS开关保持false，不改变VPN/SSH/访问限制或Memory权限。新目标启用、新凭据/扩权及新版Local公开发行都需具体授权，不能以常规测试服务器部署代替。
