# 旧任务创建退出（2026-10-28）

本轮按 [ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 让当前统一创建入口只提供 LocalArchiveTask 与 CloudTask。代码、数据库迁移、部署和用户验收分别记录。

## 实现范围

- 移除旧 SessionTask 的创建、读取、同步、BIND/JOIN、协作与原 key 恢复 API、项目页面及旧服务实现；Cloud 任务目录不再投影旧 SessionTask。既存旧数据不转为 LocalArchiveTask。
- `0034_remove_legacy_session_tasks` 在一个事务中定向清空 11 张 SessionTask 专属表，并删除 `SessionTask` 聚合的审计/事件；使用 `TRUNCATE ... RESTRICT`，遇到未列出的外键则迁移失败，不级联其他域。此迁移不可恢复旧数据。共享 Project、当前 LocalArchiveTask、CloudTask、独立 Memory 数据与凭据不属于清理范围。旧 Memory 条目仍可读取，其被删除的 SessionTask 报告来源不再可重新验证；新的旧 Local 来源明确拒绝。
- 浏览器 journal 升级至 v4，仅删除 `local-create` 和 `local-collaboration`；Cloud、LocalArchive 和 CLI 授权账本保留。升级发生在各浏览器下次访问相关功能时，不代表部署已经清理了所有客户端。旧 UNKNOWN 的外部副作用不因记录删除被判为成功或失败，也不自动重发。
- 项目页旧受管 TestRun 创建弹窗及 Cloud 重复创建页退出；TestRun 是独立执行域，现有执行和历史仍保留。已发行 CLI 0.1.1 使用的 `/archives` 归档链接继续跳转当前任务详情，不是旧 SessionTask 入口。
- 项目删除检查增加现行 LocalArchiveTask 依赖保护，防止软删除仍有归档的项目。

## 验证与部署状态

- 后端：专用临时合成 PostgreSQL 数据库迁移到 0033，执行 SessionTask 退休迁移、Cloud、LocalArchive、Memory 和 Project 相关回归：81 passed。旧报告、回执和来源外键非空时可清除；未列出的外键阻止清理，Project/Cloud/Archive 和 Project 审计保留。临时数据库和中继容器已清理。首次扩大回归的 80 passed / 1 failed 为测试临时表不能引用永久表，修正测试后重跑通过。
- Web：任务/归档/Cloud/CLI 授权、journal 与旧 Run 跳转等相关回归共 99 个独立测试通过，TypeScript 检查通过。不同命令之间有重叠，不重复累计。
- CLI：源码移除旧 `legacy reconcile`；保留 `legacy retire` / `cleanup` 用于受管配置退出。CLI 定向回归 40 passed；最初混合测试顺序发现既有事件循环污染，修复测试 fixture 后以原失败顺序重跑通过。已发行 `cli-v0.1.1` 包未修改或重发。
- 后端 `pytest --collect-only -q` 收集 2313 项（3 warnings）；未执行完整后端或 Web 回归。
- 测试服务器：**尚未部署，尚未执行旧数据清理**。SSH 使用既有 alias、公钥与严格主机密钥校验，在 banner 阶段超时；已配置代理及物理接口尝试同样未连接。服务器 Git、image、schema、旧任务数量与实际迁移效果均未知。连接恢复后应按 [服务器操作](SERVER_OPERATIONS.md) 固定提交、核对实际 schema 和范围、部署并执行该迁移，记录实际结果与健康检查。
- 业务功能验收仍由用户执行；上述测试不代表用户验收，也不构成服务器数据已清理的证据。
