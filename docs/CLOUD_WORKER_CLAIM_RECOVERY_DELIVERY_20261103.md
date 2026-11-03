# 薄 Worker 领取恢复与本机实际闭环验证

日期：2026-11-03（Asia/Singapore）。本轮由用户明确要求修复、部署、恢复薄 Worker，并实际验证领取、执行、结果回传及完成管理。

## 修复与部署

实现提交：`c7b9249e44605e11b1332ff262a083dcff0f9e1c`，已推送 `codex/native-worker-claim-recovery`。

旧 Worker 只保存本地 `local_key`，未传给服务端；领取失答后无法按原请求核对，只能长期停止。按 [ADR-036](architecture/ADR-036_WORKER_CLAIM_RECOVERY.md) 新增单行领取高水位、原序号/key/digest 校验及封口/撤权恢复。领取授权与高水位同事务提交；恢复不重新交付能力、不调用 SDK、不重跑任务。客户端在全生命周期持有进程锁，空闲网络/5xx 有界退避，正常完成后的关闭失答也不会重新执行。真正 runtime 故障仍停止。

本机 API 从该固定推送提交构建为 `hypertest-mac-api:c7b9249`，镜像 ID `sha256:760a61e72d4432c9e5a4282269dc075c990e511b4855698d83efd9704cde61c2`。维护容器将 schema 从 `0043_deleted_cloud_recovery` 增量迁移到 `0044_cloud_worker_claim_state`。私有 BFF 增加两个受限 Worker POST 路由，继续使用独立 bearer、严格 TLS 和清除 Operator header 的边界。WireGuard Web 保持 `hypertest-mac-web:df42ef1`，无需重建。

宿主 LaunchAgent 继续复用原 SDK/runtime 配对、profile、Worker 身份和私有凭据；仅使用本轮源码。服务恢复后首个空闲领取为 `EMPTY / closed=true`，已观察到后续序号推进。API 健康 200，无凭据恢复入口 401，旧无序号领取 422。

## 原未决记录处理

部署先停止并替换旧 API handler，Worker 原来已停止。前后只读核对均未发现该 Worker 的活动授权、待领取/运行 Attempt 或未完成解析。原 `local_key=dab73089a380342d2e48b8b213d18981` 的文件原样移入私有 `native-worker/state/reconciled-claims/20261103-legacy-dab73089-UNKNOWN.json`，处置为 `UNKNOWN_PROTOCOL_RETIRED`，没有重发原请求，也没有把它标成 EMPTY 或证明未执行。

历史 Attempt `01a19b74-0b63-7570-939f-5707b5e6583d` 保持 `RECOVERY_REQUIRED`、generation 3、无 lease owner；其外部未知操作、报告和历史身份未改写。此次恢复的是 Worker 调度能力，不是历史 SDK 会话或未知外部操作。

## 相关自动回归

- Worker 客户端 35 项通过：完整意图、flock、旧记录拒绝、重启零执行重放、网络失答恢复、完成后关闭失答等。
- 新领取恢复协议 11 项通过，API/原生集成 17 项通过：并发、迟到封口、同 key 异正文、原子回滚、旧序号、终态保真、凭据隔离和数据库高水位拒绝路径。
- macOS BFF/LaunchAgent 准备工具 3 项通过；相关 Ruff 与差异检查通过。

数据库回归只使用专用 tmpfs PostgreSQL `hypertest_test`，没有将 fixtures 写入业务库。证据位于本机私有 `claim-recovery-tests-20261103/`。

## 用户授权的真实任务验证

复用先前验证项目 `01a19fb1-63e9-7f0c-9ee2-595f30993abe`，新任务 `01a1a015-356d-76a6-878a-2d35a588f65d`。SUT 与 framework 都固定到本轮实现 SHA，环境为 `NONE`，范围只含任务工作区及现有无数据库单测，不执行外部业务操作。

首轮真实 Attempt `01a1a015-d7f3-7fd3-9153-ba18720ae8c5` 实际执行 35 项单测并生成 JUnit，accepted Run 为 PASS，35 个 CASE、报告和原件已回传。但任务未完成：直接 SDK driver PID 47710 在退出时触发 SIGABRT，Worker 随后 fence 并关闭原领取槽，Task 保持 `RECOVERY_REQUIRED / NOT_RUN`。固定版本 12 快照保留此前 RUNNING 的业务历史，当前执行状态应读取 summary，不能用该历史快照推断仍在运行。

macOS crash 符号栈与离线真实子进程复现共同确认：实时问答线程阻塞在 buffered stdin 读取，解释器 `Py_FinalizeEx` 清理输入时在 `_enter_buffered_busy` 中 abort。新增无缓冲、可中断的共享管道读取器与显式 close/join；父端 stdin 保持打开的正常/异常退出及合并帧等 7 项相关测试通过。Worker 另保存不含内容的直接 SDK exit code，并保留已支持的具体恢复原因。此修复只涉及宿主执行进程，API/schema 不重复部署。

首轮失败任务随后显式取消并移出列表，删除前后的固定版本 12 读回完全一致；没有伪造完成或消除 UNKNOWN。

宿主 SDK 退出修复提交为 `3ce67f3876d56326783b601c87dc8a16852acea1`。新验证 Task `01a1a01e-e98a-734b-b348-af4c0ed3a002` 固定该 SHA：首次输入解析失败且已撤权，新显式只读解析成功。首个 Attempt `01a1a021-6b2a-7336-8bdd-5a91696998b4` 已 `COMPLETED / PASS`（v13）；直接 SDK returncode 0，JUnit 35 passed，3 个原件完整读回及哈希一致，完成管理显示可以独立复测。

实际复测创建新 Attempt `01a1a023-e61d-7fd5-b1bc-faa44e1300b0`，但在 Git 准备阶段结束，尚无 SDK prompt 意图、无 framework checkout、无模型/测试执行。旧 owner、lease 与 grant 均已撤权，按这些观察通过 `OPERATOR_ATTESTATION` 收尾为 `FAILED / NOT_RUN`；该证明不是独立的宿主全局停止证据，原通过 Attempt 不变。原 Git stderr 已丢弃，不能追溯具体原因；一次复用 LaunchAgent 环境的只读 fetch 在 5.45 秒成功并匹配原 SHA，未据此猜测 HTTP/TLS/代理问题。

后续增补只对识别出的瞬态错误执行有界 Git **只读 fetch** 重试，保留原 URL/ref；认证、证书、缺失引用、未知错误、取消、checkout、SDK 与测试均不自动重试。原始 stderr 不落盘，只映射有限诊断码。另修复已完全撤权的 `RECOVERY_REQUIRED` 输入解析错误阻止删除的问题；仍有 lease 或未撤销 grant 的解析继续拒绝，6 项专用数据库正反例通过，原解析未知状态保持。

最终部署、复测和删除结果待本轮实际执行结束后补充。

原请求、逐阶段回执、固定版读回和部署身份存于本机私有 `~/.local/share/hypertest-mac/claim-recovery-20261103/`。这些是本轮操作证据，不是新的常驻平台机制。
