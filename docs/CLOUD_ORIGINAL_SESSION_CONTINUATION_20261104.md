# 旧 Harness 会话归组与原报告续写（2026-11-04）

## 用户范围

旧会话归入对应测试框架项目，并通过原 Harness 会话继续中断的报告。保留已接受测试结果；不重跑测试，不重发结果不明的操作，不新增 HyperTest 接管或审批。xblock 的框架是 hypervise_pure，原生项目名为 hypervise。

## 已交付的归组

依据原任务冻结的框架仓库和实际会话 header，配置 11 个旧根会话的精确映射，4 个原生 parentSession 子会话自动继承。实际 Harness 中共 15 个旧会话完成归组：hypervise 9 个（5 根、4 子），hypertest-one 6 个。原 ID、cwd、header 和压缩聊天日志均保持；归组后逐文件核对一致，桌面项目列表可见。既有个人会话和其他项目保持。

原生 Workspace 的跨目录成员适配由单一桌面宿主执行，固定版本内部方法摘要检查通过后才更新成员表。新会话仍直接从框架仓库启动并通过官方接口归组。规则见 [ADR-040](architecture/ADR-040_FRAMEWORK_PROJECT_SESSIONS.md)。

## 原会话恢复修复

目标任务为“宿主薄 Worker 实际链路检查”，Task `01a1a117-58bf-76f7-bce6-37b321f1c6d8`，原执行 `01a1a117-9488-75d9-9cd0-830202d5e38c`，Harness 会话 `cloud-01a1a117-9488-75d9-9cd0-830202d5e38c`。

首次连接在消息投递前失败：旧 Worker 自有 `.hypertest-cloud` 目录权限为 0755，不符合当前 SDK 适配要求。通过已核对的目录描述符将该目录收紧为 0700，文件内容不变；真实固定 SDK 的配置准备检查通过，检查本身未恢复会话或调用模型。

另修正普通发送接口：同一正文、发送者及原 key 对应的消息仍是 QUEUED 时，连接失败后可复用它重新连接原会话；已投递、投递中或结果不明的消息只返回原记录。只读查询不连接，不增加第二条用户消息。规则见 [ADR-041](architecture/ADR-041_CLOUD_AS_HARNESS_SHELL.md)。

原用户消息 `01a1a4df-22e7-773b-9cc5-da41b14fa299`，原 key `continue-report-b87a96f6e0a24fc29f0ee589d98e51c7`；修复后使用完全相同请求恢复连接。该消息已送达原会话，SDK 回执 `35dcdef6-411f-44b1-8109-83591625842c`。没有发送原任务 prompt 或平台生成的默认续写指令。

## 原报告完成结果

2026-11-04 05:02:50 UTC 读回：原 Task 与原执行均为 COMPLETED / FAIL，Task version 17，会话转为只读。原 Agent 自行读取旧收据、修正草稿中预写的完成表述，提交此前未提交的最终 REPORT 并完成归档收尾。没有人工补充报告或替代会话。

- 原 Run `01a1a11d-2a83-7e3b-87e9-8962cebc61c3` 保留，仍仅 1 次测试执行：3 项、2 PASS / 1 FAIL、exit code 1；原 3 个附件保留。
- 新 REPORT AssetRevision `01a1a4ef-f5dd-7091-8e63-cf39a4896d42`，revision 1，接受时 Task version 16，reported_result FAIL。
- 最终 COMPLETE_ATTEMPT 由原 Agent 发布，交接键 `01a1a117-9488-complete-attempt`，指向上述已接受报告；服务端收尾到 version 17。它不把进程、外部业务或环境事实升级为独立验证。
- 保留失败说明：冻结框架版本的路由声明与安装脚本 allowlist 不一致；保留实际 SUT 部署行为未观察等限制。没有通过重跑或修改旧 Run 消除失败。

## 平台改动验证与部署

- 会话恢复/原 key/拒绝路径回归 17 项、通信目录回归 13 项、归组 Node 回归 8 项、固定 SDK 归组/重启回归 1 项通过。SDK 合成回归使用临时 profile 和假 provider，模型请求为 0；数据库回归仅使用专用 hypertest_test。
- 部署来自已推送 `bca2112df0e1dca20e56c97466819128660e76a2`，包含并行上线的 `87f6fa4` 会话锁顺序修复。API 镜像 `hypertest-mac-api:bca2112`，ID `sha256:e708faea6361df3582691617352e39811d612f4362e0c36bb7d2fa8db03f0ba2`。
- 宿主薄 Worker 更新通信目录适配并重启，PID 52380。schema 仍为 0048，无迁移。Web/BFF/数据库身份和启动时间保持，API/网页健康检查 200。
- 桌面插件来自同一推送提交，重新加载后验证了实际归组。现行 Compose 链、插件配置、原消息回执及检查记录位于本机 `~/.local/share/hypertest-mac/legacy-session-groups-20261104/`，当前入口记录在 CURRENT_DEPLOYMENT.json。

以上平台回归与用户授权的原报告续写分别记录；没有创建新的业务验收任务。
