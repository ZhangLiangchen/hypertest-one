# ADR-025：Cloud 受控公开 HTTPS 读取与框架冻结

状态：2026-10-23 本轮开发决定，首片源码已实现、默认关闭；真实目标准入及业务验收为 USER_OWNED。该决定只扩展 ADR-019 的一种独立环境 adapter，不修改 ADR-018 Local 管理路径、ADR-023 固定 SSH、P0 恢复规则或历史结果。

## 范围

首片 `HTTPS_CONTROLLED_API_V1` 只支持用户明确授权的公开、无鉴权、无副作用资源 GET/HEAD。环境必须 connection=HTTPS、显式 host/port、可选 WEB_ONLY，且不能为 LOCAL_ONLY，不能引用 environment credential。禁止用 HTTPS 读取代替 XBlock 的 SSH/日志/服务器操作，166dev 与内网仍仅 Local。认证 API、查询参数、请求体、写方法、浏览器自动化、CI 与一般网络不在本片。

`environment.https_access` 精确字段为 profile、catalog_sha256、allowed_addresses、resources、max_operations。目录包含固定规范 HTTPS origin（显式端口）、最多8个公开规范IP、最多16项资源及最多32次操作；每项资源为 key、method(GET/HEAD)、ASCII exact path、timeout_seconds(1..15)、response_limit_bytes(1..262144)。不接受 query、fragment、百分号编码、点段、重复斜杠、可变 URL 或自定义 header。catalog_sha256 是对不含其自身、但含 target 的完整目录使用 sorted/compact/ASCII JSON 的 SHA-256。

任务原授权须同时包含精确 origin 的 targets/network_targets 与 environment:read；network_targets 只能是该单一 origin。现有 Git read/framework execute、Project grant、期限、当前 Worker lease/work grant/fencing 和原总预算继续逐操作核验。`cloud_https_enabled` 是独立默认 false 的开关，存在配置或网络可达均不等于获准执行。

## 网络与凭据边界

Agent namespace 仍 unshare-all，只获只读 Unix socket `/run/hypertest-https.sock`。host HttpBroker 接收 resource key 与稳定 operation key，不接收 URL、header、凭据或平台 writer token。DNS 的所有结果必须为公开地址且属于冻结 pin 集，连接使用已校验 literal IP，TLS SNI、证书主机校验及 Host 保持原授权 hostname。固定 CA 校验开启，零重定向、代理环境、自动重试、跨调用 cookie 和后续下载；流式正文及 header 有界，压缩响应拒绝。DNS、复核、连接与读取共用本资源 deadline，不能用 Git 准备或续租重置原任务期限。

本片无鉴权资源不调用环境秘密、不推测私钥用途、不复制本机身份。原始响应先经当前权限与项目秘密扫描，通过后写私有原件并 fsync，再由 fenced Worker 接受 canonical OBSERVED；最后才给 namespace 返回正文。失权只允许为本操作追加零正文 UNKNOWN 安全元数据，不能继续普通产物/报告写入。HTTP observation 只是 runtime-reported 传输事实，不是测试 PASS、部署身份或独立执行证明。

## 原操作与收尾

新增 `0028_cloud_http_operations` 的独立 immutable intent/observation 表，不复用 SSH profile 或篡改 SSH 票据。Task 聚合锁下保存固定 Project/Task/Attempt/config/work grant/generation/resource/request digest/SENT/deadline 并 commit 后，才可作 DNS/HTTP；发送前再次核当前权。一个新 key 最多获得一次发送许可，同 key 异资源冲突。

SENT、UNKNOWN、失答、NOT_FOUND 只查询原 key/operation UUID；即便还未获得 UUID，也能按原 key 纯读恢复。不能通过新 key、prepare_start 或断连重开来重发。返回 OBSERVED 前须 canonical 回执与私有完整原件/摘要一致；丢原件不重复请求。3xx 保留实际状态且拒绝 follow；4xx/5xx 也只是原响应，不自动重试。

HTTP UNKNOWN 纳入所有原有 ensure_remote_closed 检查：完成、结算、重试、恢复和人工 RECONCILE 都不可绕过；保留 HELD、原操作、原件及旧终态。关闭本地 socket/namespace 不证明外部动作完成，操作者声明不能制造 OBSERVED。本片不提供未经设计的人工“强制清 UNKNOWN”接口。

## 框架依赖与入口

新 HTTPS 任务必须冻结 `inputs.framework_runtime`，profile=`FRAMEWORK_LOCKED_V1`，含 lockfiles(path/sha256)、tools(name=python|node,version,sha256)、entrypoints(key/argv)。入口 key 集必须精确匹配既有 framework_entrypoints；Run 继续受原入口准入。旧任务省略新字段时序列化完全不增加 null，不改变旧 digest。

Worker 在模型 prompt 前，从固定 framework SHA 的工作区读取最多16个正规、无软硬链接、无秘密路径的锁文件（总≤1MiB），核完整摘要；只选择固定 root-owned Python/Node，先核可执行文件摘要，再在干净环境中执行固定 `--version`。不执行仓库脚本、安装命令或入口 argv。只冻结依赖声明与实际工具身份，不冒称已经验证依赖闭包、框架可安装、所有 SDK shell 语义已受限或真实项目已成功；需要额外依赖的框架仍需独立准备受控离线供应与准入。首片仅适用于当前镜像已具备依赖的明确 API 框架。

## 交付边界

合成 PostgreSQL、MockTransport、Unix socket 和临时 CA 的回环真实 TLS 回归属于开发验证，不是用户业务 E2E。启用真实目标之前需用户指定 Project、无副作用资源目录、IP/证书身份、期限/预算并明确授权；新凭据或新权限另行确认。Local 新发行、SDK 原会话续接、SUT CI、一般 SSH 与 Cloud Claude 各自独立。
