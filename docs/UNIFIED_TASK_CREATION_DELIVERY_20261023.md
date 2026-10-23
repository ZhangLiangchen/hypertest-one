# 统一任务创建入口：2026-10-23 实现与部署交付记录

> 后续 Web 的 Cloud 与 Local CREATE 持久账本交付见[P0 恢复记录](P0_RECOVERY_DELIVERY_20261023.md)。本轮开始时实际部署为 `55de50e`；下文 C4/6d49 和 sessionStorage 时期的描述保留其历史轮次，不作为当前状态。

**功能验收：由用户执行，本轮未开展。**

本记录保存统一Cloud/Local任务入口的实现来源、已发生的远端构建与部署回执，以及既有组件回归引用。原浏览器验收计划已取消，不再安排fixture创建、凭据操作、截图或线上故障注入。

## 实现来源与范围

| 来源 | 已记录身份 |
| --- | --- |
| UI提交C0 | `947a4ed6f4f3abb879c09c5063283b326f04575e` |
| C3应用源码 | `9b45ae994c2cd246d0c2ff1ca66af771afad1615` |
| C4已部署基线 | `d065ae2e27b6ff37c87a8ebe0c549a96dda45a73`；仅增加ops builder及其测试修改，应用源码保持C3；部署状态为DEPLOYED_AVAILABLE_FOR_USER，不是功能验收 |
| 当前Web修复源码 | `6d496890013614de5f216a9e672b4e915fd66550`，tree `874d110be36fc64cd4f3f813050548a3a947d3e7`；已单独构建并部署Web，API、Cloud Worker与schema保留C4部署身份 |

统一入口按Cloud/Local类型调用各自API，保留共享标题、目标与各自草稿，使用同一Cloud operation状态和pending互锁。Cloud创建保存DRAFT而不下发；Local预创建保存稳定Task ID及UNBOUND状态，不伪造来源或绑定。项目目录按任务类型重新打开对应详情。

Local新绑定及手动已绑定Task显式新sync的caller适配目前仅实现Codex CLI 0.144.6的逐调用路径；Claude/DeepSeek对应新caller适配未实现，既有auto任务resume与原key只读恢复保留。具体合同和限制见[ADR-024](architecture/ADR-024_OPERATOR_CREATED_TASKS_AND_LOCAL_BINDING.md)。

## 已发生的远端交付

执行环境为用户的单人专用HyperTest One测试服务器，交付来源为已推送Git历史。以下部署数据由执行者实际回执及其本地安全摘要核对；C4记录类型为DEPLOYMENT_CHECKS_NOT_USER_ACCEPTANCE，后续Web记录类型为WEB_ONLY_DEPLOYMENT_SUPPLEMENT_NOT_USER_ACCEPTANCE，不另建运维操作记录。

| 项目 | 当前实际记录 |
| --- | --- |
| API构建来源与复用 | 物理构建来源为C3，image `sha256:2e20377e8af61bc5ebe42666ecb68475c26ff48c0d7b27be64f094e058f81405`；C3→C4完整应用构建输入闭包zeroDiff，复用且未重建/重标 |
| C4历史Web构建来源与复用 | 物理构建来源为C3，image `sha256:7fcae540c62e8c3d286cdd1be0ef7862c52f91691325efdff43c409181e63a70`；同一输入闭包核对后供C4复用，未声称C4重建。此Web镜像已由下述6d49构建替换 |
| 当前Web构建与部署 | 物理Git为`6d496890013614de5f216a9e672b4e915fd66550`，正式build成功，image `sha256:da14c5738094488683df8205a3fad53d3a19fab4567f1b24b5fb17743652e0aa`；Web健康，根页面HTTP 200，Cloud setup HTTP 200且configured为true |
| Cloud Worker构建 | 首次因旧ignore规则及inner 700相关问题失败；C4修正builder后完成构建与导出，image `sha256:ff1130be30aeced1e30bebe3132ac1a96351b9a2bc344b4f4e61164d7c641a77`。首次失败与后续修复分开保留 |
| 迁移与健康回执 | C4 guarded stack已迁移至`0026_cloud_ssh_operations`，5个角色健康检查通过；此为部署健康结果，不是功能验收 |
| 数据保全回执 | 15个Project、14个SessionTask、9条管理修订计数保持不变 |
| 长期Cloud Worker状态 | active-idle / IDLE_READY，Codex委派配置为true、SSH配置为false；pending前后均为0，没有SDK/model子进程 |
| Cloud待执行工作 | 待执行Task、Attempt、input-resolution均为0，没有据此发起测试任务 |
| Web实际身份的只读连通检查 | UID1000经UDS使用严格CA与IP SAN校验，TLS 1.3 typed GET返回HTTP 200；此为服务间连通检查 |
| 服务器部署记录 | `/var/lib/hypertest-cloud/delivery/20261023-fe4c4348/deployment-c4.json`；SHA-256 `41bc5d77428202d44da09be6d30e3b8a52821470d617ad3b02de5a221459d590` |
| Web部署补充记录 | `/var/lib/hypertest-cloud/delivery/20261023-fe4c4348/web-followup-6d496890/deployment-web-supplement.json`；SHA-256 `a1345bdb388145a916019d76e428bd8f5dd8cbcdc9a727b820af53558b76c6f3` |
| Web更新保全回执 | API、legacy Worker、PostgreSQL、nginx容器ID和镜像，以及Cloud Worker PID前后保持一致；未再执行schema迁移，未启动模型、SUT或验收fixture，原C4部署记录保持原摘要 |
| Cloud正式部署文档引用 | [Cloud Git交付记录](CLOUD_GIT_DELIVERY_20261023.md) |

Web进度P2修复已包含在上述6d49部署中：DRAFT、早期FAILED或CANCELLED的进度不再错误回落到Harness完成step4。当前交付由C4的API、Cloud Worker与schema身份，加上6d49单独构建部署的Web组成。

本机未运行测试、typecheck、build或本轮功能验收。

## 已有组件回归与历史边界

[Local绑定验证记录](LOCAL_TASK_BINDING_ACCEPTANCE_20261023.md)保留A首次157通过/4失败、b6原4项定向复验，以及F首次128通过/3失败、F2原3项及14个相关边界复验通过的分run原件与计数边界；这些结果不改写成首次全通过，也不是统一入口浏览器验收或真实宿主绑定E2E。Cloud既有实现与隔离回归范围见[Cloud实现状态](CLOUD_IMPLEMENTATION_STATUS.md)，不在此复制其完整统计。

6d49 Web修复的远端定向组件回归仅运行`tests/cloud-client.test.cjs`，17通过、0失败、0跳过；正式Web build退出码为0。此为组件回归与构建结果，不是线上功能验收。

迁移前曾作一次只读历史观察：Project `01a15de2-205e-76e6-bfad-7468a724f886`，原Task `01a15de5-9aca-76b4-bd57-c673112f2e92`，固定v1为IN_PROGRESS / reported FAIL；页面显示15个用例、2份原始报告，最后同步时间为2026/10/21 17:58:10，管理历史未显示手动修改。此观察仅为迁移前历史基线，不记功能PASS，不代替迁移后功能核验。

功能验收由用户执行，本轮未开展；真实Codex宿主parent/child绑定E2E仍为NOT_OBSERVED。上述组件回归、部署健康和连通回执均不新增功能验收成功结论。
