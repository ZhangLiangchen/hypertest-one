# Cloud / Local 测试环境路由

**状态：用户确认的执行边界（2026-10-23，Asia/Singapore）。该规则不新增Task或授权scope，也不自动启动测试；Environment只新增可选的收紧字段，不赋予执行能力。**

同一Project可同时拥有CloudTask和Local SessionTask；按本次任务实际需要的工具、网络和身份选择执行来源，不给Project设置排他模式，也不把已有Task转换身份。Local表示本机Agent负责工作与管理同步，获授权的框架可以在远端；它不要求SUT或所有测试都在Mac上运行。

| 目标与任务范围 | 允许的模式与当前边界 |
| --- | --- |
| XBlock staging，需SSH、服务器日志或服务器操作 | **仅Local**。该SSH受源IP限制，仅用户本地Mac经Workbench CLI可达；使用其现有独立授权，不从CloudWorker连接 |
| XBlock staging，纯Web / API任务 | 产品上可选择Cloud，前提是该路径可达、另有明确授权且对应HTTPS / 浏览器adapter已实现并验收。**网络可达不表示当前Cloud runtime已经支持通用HTTPS / Web测试**；该路径排在当前固定SSH小片之后另行接通 |
| 166dev内网及自建链相关任务 | **仅Local**。不从云端直连内网环境或自建链；实际远端执行仍须本机已有工具和本次授权 |
| 通用Cloud固定SSH诊断 | 只在独立隔离sshd / manager fixture内开发验收，默认关闭。为未来另行批准、云端可达的目标准备，不用于绕过上述两类环境限制，不宣称真实staging已可用 |

环境资源可保存`cloud_access_policy=LOCAL_ONLY|WEB_ONLY|None`：XBlock staging的SSH资源与166dev为LOCAL_ONLY，staging纯Web / API资源为WEB_ONLY。None按旧序列化省略，保持历史冻结digest。LOCAL_ONLY在Cloud创建 / 解析 / 下发及Worker执行前拒绝并提示另行授权Local；WEB_ONLY只允许HTTPS连接，但不启用尚未实现的HTTPSruntime。Worker还会在真正prompt前复核冻结限制，不能靠重新分类、改Project模式或将CloudTask转换SessionTask绕过。当前只加入通用限制能力，未实际更改XBlock / 166dev Project配置或使用本地秘密。

禁止为Cloud建立转发 / 代理 / 隧道绕过源IP或内网限制、扩大IP许可，或复制用户Mac登录、Workbench身份、个人SSH目录和环境秘密。管理HyperTest服务器的本机SSH alias / key / VPN规则与测试环境访问分别保留，不互相授予执行权。不得以“已有远端连接”推导部署 / 写入权限。

`hypervise_pure`本机的`configs/dev/env_password`仅是用户指定的**本地秘密入口**；由本机获授权工具按需使用，不读入Cloud配置 / 容器 / 提示词、源码、普通任务字段、证据或日志。本文只记录来源语义，不复制秘密值。项目加密SSH credential设计也不授权将该本机入口上传云端。

这次HyperTest开发与fixture验收不是XBlock测试请求，不因此新建XBlock Task或执行SUT。未来实际XBlock测试会话继续遵循既有Local管理同步、真实父会话与唯一writer、冻结请求 / key / expected_version和UNKNOWN原key只GET；环境选择不放宽这些规则。

Cloud已验收的公共fixture六步、固定SSH专项及其余未验收范围见[实现状态](CLOUD_IMPLEMENTATION_STATUS.md)、[ADR-023](architecture/ADR-023_CLOUD_SSH_FIXED_DIAGNOSTICS.md)；Local的发行 / 宿主适配状态由其独立文档负责。
