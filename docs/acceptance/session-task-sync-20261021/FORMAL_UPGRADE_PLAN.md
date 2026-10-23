# 正式环境升级待确认方案

2026-10-21，Asia/Singapore。**本文件仅供审阅；未执行正式迁移、停服、镜像切换或业务同步。**

## 已完成的远端候选验收

候选源码快照 `4036ba150bf743db317bf51b13ae28363c46b49c5eae5098576ee6e703e50f4b` 基于 `5a68dd1` 的未提交工作区，采用独立 editable 安装，**不是正式发行 wheel，本轮没有对应的已提交版本或 CI 通过证明**。

同一远程服务器的独立数据库实际完成0020→0021→0022迁移；86项后端/MCP兼容测试通过（54条 SQLAlchemy 弃用警告）。既有宿主 Node 完成 npm ci、类型检查、129项 Web 测试与正式构建。候选 API/Web 仅监听18101/13101回环端口。

真实 Codex 任务已通过官方 MCP SDK 同步：15条设计用例为10 PASS、2 FAIL、3 UNKNOWN；2份原始报告逐字节读回，原key回执与固定版本三页读取一致。Web反代读回相同任务 JSON，3个HTML页面及24个静态资源HTTP200；没有另跑SUT，也没有完成浏览器交互验收。证据见[远端报告](REMOTE_REPORT.md)和[原始记录](remote/remote-validation-commands.json)。

## 正式切换的最小范围与前置条件

1. 先固定可交付的提交、CI、API/Web镜像及新客户端发行身份，保留现有 Worker/Bridge/PG/nginx 的精确版本。API与Worker镜像在 Compose 中独立指定；新管理同步不创建Job，因此不要求更换Worker或Bridge镜像。[配置依据](../../../compose.production.yml#L52)、[Worker分派依据](../../../src/hypertest/worker.py#L50)。
2. 在同一维护锁和已核实的空闲窗口内，关闭新写入入口，核对活动、等待和未知工作；存在未对账工作则保留原执行进程并退出维护，不强制换会话或重放请求。
3. 完成当次配对冷备及独立恢复/0020→0022迁移/旧行和文件核验。既有备份协议要求短停旧Worker和Bridge进程，但保留它们的镜像、配置、原生会话与数据；**PG容器、数据卷及启动时间全程保持**。不得直接调用会停止整栈及PG的 `scheduled_backup.py`/`start.start()`。[备份约束](../../../ops/container/backup.py#L32)、[整栈停止行为](../../../ops/container/scheduled_backup.py#L74)。
4. 前置结果通过后才对正式库向前迁移0021/0022。0021新增11张历史表；0022新增4张管理表并扩大允许的scope集合，不自动给旧授权增加 `task:sync`。
5. 使用经过审阅的组件切换操作只替换API/Web，恢复原Worker/Bridge版本；既有PG、固定ops、TLS/SSH/VPN与白名单保持。记录独立组件身份，不把旧Worker冒称新提交构建。完成内部就绪、旧报告/授权/数据保全后再恢复正式入口。
6. 正式同步前先查询真实生产Project和原session/key，建立正确Project映射及独立 `task:sync` grant。**不复用候选Project UUID或token，不盲发同一任务POST。** 请求失答只查原key；正式任务仍保存Agent报告结果，不触发Runner/Gate。

## 回退与当前保全边界

未产生新管理写入且兼容性确认时，可恢复已核验的原API/Web，schema保持向前；已有任务/报告/授权历史时，优先使用兼容修复版或向前修复。旧API缺少管理接口，不能当作完整功能回退。不降级、不用旧dump覆盖正式库、不删卷/历史、不重发未知操作。候选回退只停止其独立进程，保留数据库、原件和日志。

当前正式库仍为0020。58/61张表的行数和完整行摘要aggregate与前置基线严格一致；`harness_nodes`（2→2）、`worker_heartbeats`（44→44）摘要变化，`runtime_control_requests`（3808→3809）新增一条。新增操作为07:57:21 UTC的 `ENVIRONMENTS/SUCCEEDED`；调用来源未唯一确定。初始基线没有列级快照，因此不声称节点仅改变四个连接字段。5个正式容器身份、镜像、启动/重启计数和完整挂载、current入口及所采受保护配置元数据一致。[实际差异](remote/production-preservation-comparison.json)。这些是保全记录，不是测试执行证明。
