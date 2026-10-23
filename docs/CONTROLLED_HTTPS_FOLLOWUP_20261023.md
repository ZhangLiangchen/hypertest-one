# Cloud 受控 HTTPS 首片（2026-10-23）

本片增加默认关闭的 `HTTPS_CONTROLLED_API_V1` 源码能力，用于用户明确授权的公共只读 API 资源。它不启用测试服务器上的新目标或一般网络，不触发真实模型、SUT、浏览器、CI 或 SSH。功能验收由用户负责；构建、隔离自动化回归和健康检查分别记录，不当作真实 API 任务执行证明。

## 固定授权

配置中的 HTTPS Environment 固定 canonical host、显式 port、公共 IP 集合和资源目录。每个资源固定 `key / GET|HEAD / exact path / timeout_seconds / response_limit_bytes`；目录整体有 SHA-256，随原 Cloud 输入冻结。路径是规范 ASCII 路径，不接受 query、fragment、百分号编码、反斜杠、`.`、`..` 或二次 origin。首片不接受请求正文、自填 Header、Cookie、应用私钥、Bearer 或客户端证书；`application_private_key` 不能自动解释为 API token。

单资源总耗时上限为 15 秒，响应正文最多 256 KiB；目录最多 16 项、单 Attempt 最多 32 次已登记操作。实际配置可以收紧这些限额。任务还须显式包含精确 origin 的 `targets / network_targets`、`environment:read`、原授权有效期和冻结 framework runtime；参见[框架工具链首片](FRAMEWORK_RUNTIME_FOLLOWUP_20261023.md)。`LOCAL_ONLY` 继续拒绝 Cloud，`WEB_ONLY` 只收紧访问范围。XBlock SSH/服务器任务及 166dev 的 Local 路由保持，不能通过本能力绕过限制。

## 网络与 TLS

Agent namespace 仍没有目标 DNS/TCP 或通用网络，只挂载专用只读 UDS。host broker 每次解析时要求全部 DNS 结果为获准公共地址，且落入冻结 pin 集合；拒绝混合公私地址、metadata、loopback、link-local、保留地址和 IPv6 转换地址。连接使用已经选择的 literal IP，TLS SNI、证书 hostname 校验及 HTTP Host 仍使用原获准 host，避免再次解析造成 DNS rebinding。

正常 CA 校验始终开启，不能关闭 hostname 验证。不跟随任何重定向，不读取代理环境，不重试连接，不继承前次请求 Cookie，也不开放 WebSocket、HTTP CONNECT 或一般 Header 通道。3xx 仅作为实际已收到的 HTTP 响应记录，不访问 Location。响应流和 Header 分别有界，拒绝压缩响应及不完整、超限正文，不静默截断后宣称完整。

## 原操作与取消

`WorkerHttpAuthority.prepare_start` 先在 PostgreSQL 提交原 key、固定 request digest 和 `SENT`，才允许唯一一次网络发送。DNS 后、发送前再次核验当前 Worker lease、grant、授权、固定目录及截止时间。既存 key 返回原记录，不重新发送。

失答、超时、取消、旧 lease、输出拒收或原件缺失不能触发第二次 HTTPS。namespace 客户端仅支持固定资源调用和原操作读取：

```text
python -m hypertest.cloud.http_client invoke --key ORIGINAL_KEY --resource RESOURCE_KEY
python -m hypertest.cloud.http_client query --key ORIGINAL_KEY
python -m hypertest.cloud.http_client query --operation ORIGINAL_OPERATION_UUID
```

恢复只使用后两个查询；如果首次准入回执丢失、尚不知道 UUID，仍能用原 key 只读查询。NOT_FOUND 不能证明请求未发生，也不授权换 key 或重新 invoke。查询只读原平台记录及 host 私有原件，不再访问目标。

只有当前 fenced Worker 能接受 `OBSERVED`。失权后可以追加受限的 UNKNOWN 安全元数据，不能恢复普通报告写权或向 Agent 返回正文。正文先经已知秘密扫描并持久保存至 namespace 外的私有不可变原件，再核对平台接受回执后释放；平台表只存非秘密操作/观测元数据和正文 digest、大小，不存正文或 token。原件及最终观测不可覆盖，ACK 失答可以从原 DB ID 和原文件恢复，不重放 HTTPS。

broker 关闭先封闭新连接并取消在途 handler，再等待监听器关闭；避免 Python 3.13 的 `Server.wait_closed()` 等待活动连接形成关闭延迟。取消或断开本地连接不证明远端应用没有处理请求。未确认操作继续 UNKNOWN，平台完成与人工 RECONCILE 同时检查这份独立 ledger，不能绕过，原 HELD 不释放。

`OBSERVED` 仅表示取得了有界、校验过的 HTTP 响应；HTTP 200、3xx、4xx 或 5xx 均不是平台自动产生 PASS 的依据。项目测试框架负责断言，HyperTest 保留实际结果、原始报告和原操作身份。

## 本片相关回归

首片 62 项合成回归通过，覆盖资源目录与方法限制、路径绕过、public-IP/DNS pin、零重定向/代理、响应边界、总超时、准入与 ACK 失答、原 key/UUID 读取、Worker 失权、秘密输出拒绝、UDS 在途取消、私有原件完整性和不可变性。此数字包含下述 3 项 TLS 专项，不与之重复相加。

TLS 专项使用真实 HTTPX/httpcore/TLS 路径和临时 CA/certificate。仅 fixture 的 NetworkBackend 在断言连接目标仍是冻结 public-IP 后，把 TCP 映射至临时 loopback 服务；runtime 公共 IP 策略未放宽。原 hostname 及可信 CA 成功，错误 hostname 和不可信 CA 均拒绝；没有外网或真实 SUT 请求。

## 剩余范围

这不是浏览器自动化、一般 API 写入、任意 URL/参数、认证 API 或动态依赖安装能力。首批范围仅公共 `GET / HEAD` 固定资源；写方法、请求正文、query、应用认证、mTLS、扩展网络与更宽工具链各自需要后续明确授权和独立实现。真实 SDK 原会话恢复、一般 SSH、远端 CI 和 Cloud Claude 的状态不因本片改变。部署身份、镜像、迁移及现场开关由本轮统一交付记录拥有。
