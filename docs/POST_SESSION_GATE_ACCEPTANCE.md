# 会话关闭后的 Finding 处置与独立 Gate 验收

日期：2026-10-19。规范依据为 [ADR-014](architecture/ADR-014_POST_SESSION_GATE_REASSESSMENT.md)、领域模型 §18/§19/§23.8、TMP §38.1 和白皮书 §18。

本记录区分本分支的功能验收与生产访问配置。生产业务应用基线为 main `828225d1c1d698f820aebb265ad962e3ab6c2151`、主机 Bridge `95e92c5`、schema `0014_harness_operations`。本分支功能尚未部署，不能用访问配置切换推定新功能已上线。

## 实现与边界

- Web 在完整报告关闭原会话后继续展示 Finding 分诊、确认、解决、关闭及有界处置历史。每次人工更新提交预期版本、原因并形成配对 Audit/Outbox；旧 API 可选版本字段保持兼容。
- 独立 Gate 必填原因，保存为 DurableJob，由 Worker 在原 Run/Binding epoch 和有效租约下执行。只有原 Binding 和主 Session 均 CLOSED、且已有同归属的被接受报告才获准。其他终态、等待、恢复和未完成报告状态不获准。
- 治理 Job 不调用 Agent、Bridge、Runner、Git 或环境预检，取消/失败/租约回收也不触发外部资源恢复或清理。原 Session、预算、checkpoint、执行事实、证据、报告和工作区保持不变。
- 状态变化追加 FINAL；连续相同状态只复用最新匹配 Verdict。A→B→A 追加新序号，不能倒指旧结论。不同请求保留自己的原因、Job 和结果审计。
- 报告保留生成时的结论；Web 显示其原 Verdict，并在与当前 FINAL 不同时标明历史差异。关闭 Finding 不能豁免正式测试失败；验证代码修复须创建新固定 SHA 的运行。

无新增迁移，不改变 Gate 质量算法、可信执行来源或 Agent wire/profile。两套独立 PostgreSQL 数据库均实际从 `0001` 升至 `0014`，原开发库与生产库不用于测试夹具。

## 自动化检查

最终后端冻结源检查：Ruff 通过，`pytest -q` 为 **686 passed / 18 opt-in Docker skipped / 3 existing warnings**（113.05 秒）。147 个 Python/配置输入在检查前后相同，清单摘要 `57fc2cb1e517e9641cd6fdf60e51023b31047e277240a3f39579a5dd5ef36651`。

独立 Web 上下文已完成 `npm ci`、95 项回归、typecheck 和生产 build。真实浏览器随后发现从 Finding Drawer 打开 Gate Modal 时的遮挡；已修复为打开 Gate 时隐藏但保留原 Finding/表单，取消恢复原抽屉和草稿，成功提交才关闭。修复后在同一独立上下文重新通过 **96/96 Web 回归、typecheck、生产 build**。原 lockfile/依赖不变，先前 `npm ci` 仍对应最终依赖。新增真实 hook 事件回归验证打开 Gate 隐藏原 Drawer、取消恢复同 Finding 和表单 key。实际桌面浏览器确认空理由拦截、取消恢复处置草稿和 Gate 理由草稿、成功提交任务；英文界面也实际填写并提交。曾请求 390×844 的浏览器覆盖尺寸，但独立 DOM 读取显示仍为 1280×720；因此只声明实际桌面验收，不声明移动设备或窄屏通过，临时覆盖已清除（`evidence/responsive-viewport-limit.json`）。

并发、租约、CLOSED 准入拒绝矩阵、取消/过期的外部工作隔离、最新 Verdict 复用、A→B→A、报告只读投影与有界历史读取由真实 PostgreSQL 回归覆盖；不将这些合成边界测试冒称真实模型验收。

## 真实 Web / Codex / Docker

在独立本地 API、Worker、主机 Bridge 和生产构建 Web 中，通过实际浏览器创建 Project、选择 PRD 文件、提交固定仓库/SHA、启动持久测试周期。Agent 输出来自真实 Codex 模型；正式 HTTP 测试来自无外网、预制镜像的 Docker Runner，没有预设 Agent 结果或模拟执行。

独立验收目录：[closed-gate-20261019](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/closed-gate-20261019)。原生会话只采集身份和指定文件摘要，不读取对话正文。

| 链路 | 实际结果 |
|---|---|
| 故障服务原周期 | Run `01a15304-4ed4-7183-b0cf-3ac9dd928351`；真实 27 项 JUnit，18 PASS / 9 assertion FAIL / 0 ERROR / 0 SKIP；诊断 Finding 和 RELEASE_BLOCKED 报告被接受，原会话 CLOSED；独立 33/33 检查通过 |
| CLOSED 后人工处置与 Gate | 同一 Finding 按 NEW→TRIAGED→CONFIRMED→RESOLVED(WONT_FIX)→CLOSED，版本 1→5；确认后追加 FINAL #2，关闭后追加 #3，仍 RELEASE_BLOCKED；第三次同状态重评复用 #3，每次原因与 Audit/Outbox 独立记录；三个阶段治理比较为 31/31、31/31、32/32 通过 |
| 修复服务新周期及 CLOSED Gate | Run `01a15314-50d4-77ab-b3da-86a2a89985e9`；6Req / 8Risk / 15Case / 15Impl / 1Execution / 5Evidence，15/15 JUnit PASS；FINAL #1 RELEASE_READY 与报告已接受，独立模型检查32/32；CLOSED 后新 Gate Job 精确复用原 #1，治理31/31及复用证明4/4通过 |

故障链处置前，已冻结 325 条旧行、9 个 Artifact、531 个 Workspace 文件、2 个 Bridge ledger 文件及指定原生会话文件摘要。后续比较只允许受控 Finding/Run 字段、追加 Gate Job、Audit/Outbox/Verdict 及关联；禁止改写任何旧事实或重新产生模型/执行活动。负向最终比较全部通过：3 个 Gate Job 只追加 2 份 FINAL；原会话、预算、checkpoint、模型/Runner 调用、正式执行、证据、报告字节与全部原文件均保持。实际打开旧报告，仍引用第 1 份 Verdict，页面说明最新为 #3，并显示原报告摘要 `08059fa90aa1ded8331dfb38781900e9e5823f72e51c67d7581b4ddfc31260a7`。

从故障运行真实点击“新轮次”，Review 沿用输入、更换修复 SHA 和 ASGI app，并再次通过文件选择器导入同一 PRD。独立14/14检查核对同 Project、新 Run/Source、PRD原文及摘要、原配置文本、完整编译Policy及其hash；Binding、logical Worker、主Session和原生UUID均不同。正向周期和治理后，负向已有510行在38张表中的摘要及原文件仍保全。两条新链没有触发问答、失败Gate重试或进程崩溃；不将回归或历史问答结果冒称这些新链的实际行为。

独立汇总为 `acceptance/independent-final-rollup.json`，GET/只读SQL/文件摘要工具清单为 `tools/manifest.json`。桌面实际操作截图：[Finding处置历史](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/closed-gate-20261019/evidence/finding-closed-history-desktop.png)、[原报告与最新判定](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/closed-gate-20261019/evidence/report-original-versus-final-desktop.png)、[正向Gate任务结果](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/closed-gate-20261019/evidence/positive-gate-result-desktop.png)。

## 生产访问配置

最新操作者要求为唯一的既有跳板白名单 Web 入口；具体地址只保存在受保护运维配置中，不写入白皮书或示例。SSH 用于管理，禁用 TCP/Unix socket 转发及隧道，保留原认证方式和主机密钥。

常规部署核对有效白名单和内部就绪；仅首次启用、边界变更或故障诊断补充来源访问验证。本次边界变更已实际完成：固定 ops manifest 为 `90037658b11338ea183e9daa197d1bde5671cf8617bc6322f9ead96f009c2c96`，独立于业务应用的 main/镜像身份；后续启动与配对备份从可追溯的 `ops-current` 选用。仅精确健康端点允许回环 GET/HEAD；回环 Web/API 及健康 POST/OPTIONS 均 403。新 SSH 管理连接成功，TCP/Unix socket 转发明确拒绝；UFW、Docker 守卫和原认证配置保留。一次现有白名单来源浏览器 Web/health 确认通过，不重复手机或多源矩阵。

生产 **29/29 保全检查**通过：39 张表及 60 个原 Artifact、2380 个 Workspace 文件、11 个 Bridge ledger 文件摘要不变（排除心跳和运行控制队列）；OAuth、5 个镜像、业务828225d与Bridge95e保持。已完成配对备份并核验4组件摘要，本次不冒称再次执行隔离恢复。真实切换曾暴露旧API不支持HEAD的405，严格检查自动回退；最终只在精确健康路由把允许的HEAD代理为GET，重新切换成功。该 renderer 与对应测试晚于686冻结；随后 **48/48 运维定向回归、Ruff及真实nginx 9项允许/拒绝检查通过**，不将先前全套结果归给较晚输入。完整版本、维护锁、回退与备份记录见[访问切换交付](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/closed-gate-20261019/SERVER_ACCESS.md)。

## 冻结输入与本地收尾

最终实现、测试、运维和 Web 共219个输入摘要为 `9b099ac458a18e060d6937f9a18b5d749201525ef506375b4ed0433938cee61e`（`evidence/final-source-manifest.json`，不是Git SHA）。Web最终55输入与通过96项检查和build的独立上下文逐个一致；686项后端冻结后的唯一变动测试输入为 `tests/test_container_deployment.py`，对应的较晚renderer和该测试已由48项定向及真实nginx验收覆盖。产品代码在真实验收期间未变化。

两条真实链及治理采集完成后，仅停止本轮拥有的API/Worker/Bridge/Web进程。本地原开发数据库34/34表行数和全行摘要与开始前一致，原schema仍为0012；新测试库和验收库独立迁移至0014。PostgreSQL容器恢复本轮开始前的停止状态，卷、验收数据、原生会话和产物保留，不删除OAuth或修改全局CLI。原生产浏览器页保持原URL。

## 第一阶段剩余范围

本增量只补齐完整报告后的人工处置与确定性质量治理。外部 GitLab 实际提单、其他 Harness、多主机、多人身份/RBAC、通用语言/环境和更长周期可靠性仍须各自验收；不以这两条模型链宣称全部白皮书目标完成。
