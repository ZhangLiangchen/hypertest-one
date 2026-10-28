# 旧任务创建退出（2026-10-28）

本轮按 [ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 让当前统一创建入口只提供 LocalArchiveTask 与 CloudTask。代码、数据库迁移、部署和用户验收分别记录。

## 实现范围

- 移除旧 SessionTask 的创建、读取、同步、BIND/JOIN、协作与原 key 恢复 API、项目页面及旧服务实现；Cloud 任务目录不再投影旧 SessionTask。既存旧数据不转为 LocalArchiveTask。
- `0034_remove_legacy_session_tasks` 在一个事务中定向清空 11 张 SessionTask 专属表，并删除 `SessionTask` 聚合的审计/事件；使用 `TRUNCATE ... RESTRICT`，遇到未列出的外键则迁移失败，不级联其他域。此迁移不可恢复旧数据。共享 Project、当前 LocalArchiveTask、CloudTask、独立 Memory 数据与凭据不属于清理范围。旧 Memory 条目仍可读取，其被删除的 SessionTask 报告来源不再可重新验证；新的旧 Local 来源明确拒绝。
- 浏览器 journal 升级至 v4，仅删除 `local-create` 和 `local-collaboration`；Cloud、LocalArchive 和 CLI 授权账本保留。升级发生在各浏览器下次访问相关功能时，不代表部署已经清理了所有客户端。旧 UNKNOWN 的外部副作用不因记录删除被判为成功或失败，也不自动重发。
- 项目页旧受管 TestRun 创建弹窗及 Cloud 重复创建页退出。用户随后明确要求一并删除旧受管 TestRun 及其相关执行、证据和报告，本轮后续改造覆盖它们。已发行 CLI 0.1.1 使用的 `/archives` 归档链接继续跳转当前任务详情，不是旧 SessionTask 入口。
- 项目删除检查增加现行 LocalArchiveTask 依赖保护，防止软删除仍有归档的项目。
- 用户明确旧受管 TestRun 及关联数据一并退出：旧 Run、Mission/Job、执行、Evidence、Verdict、报告及相应 API/页面退出；`0035_retire_legacy_test_runs` 定向清理其专属记录及明确关联的审计/队列数据。Project 级共享快照、需求、用例等不做无差别清空。部署前本机旧 Run 及这些共享快照/需求/用例等均为 0。原独立 Native、Cloud、Archive、Memory 和授权保持各自范围。

## 验证与部署状态

- 后端：专用临时合成 PostgreSQL 数据库验证 SessionTask / TestRun 退休迁移和现行 Cloud、LocalArchive、CLI 授权、Memory 与 Project 相关回归：92 passed。旧 TestRun 的非空 Job、RunReport、Evidence 均被清理，未列入的外键阻止清理并回滚。此前仅 SessionTask 的范围为 81 passed，不重复累计。旧报告、回执和来源外键非空时可清除；未列出的外键阻止清理，Project/Cloud/Archive 和 Project 审计保留。临时数据库和中继容器已清理。首次扩大回归的 80 passed / 1 failed 为测试临时表不能引用永久表，修正测试后重跑通过。
- Web：首次 SessionTask 退休的相关回归 99 个独立测试通过；随后删除旧 Run 页面，受影响的现行页面与 Cloud 轮询回归 61 个独立测试通过。两轮存在重叠，不相加；最终 TypeScript 检查通过。
- CLI：源码移除旧 `legacy reconcile`；保留 `legacy retire` / `cleanup` 用于受管配置退出。CLI 定向回归 40 passed；最初混合测试顺序发现既有事件循环污染，修复测试 fixture 后以原失败顺序重跑通过。已发行 `cli-v0.1.1` 包未修改或重发。
- 未执行完整后端或 Web 回归；测试收集与迁移验证分别记录，不作为用户验收。
- 本轮最初误将历史远端 SSH 当作测试服务器；用户随后明确本 Mac 的 Docker 容器即测试环境。已现场核对 schema `0033_project_repositories`、SessionTask 0、TestRun 0；后续迁移及部署结果另行记录。
- 业务功能验收仍由用户执行；上述测试不代表用户验收，也不构成服务器数据已清理的证据。
