# ADR-038：Cloud 聚焦任务输入、下发与产物归档

**状态：Accepted；实现、部署和用户验收分别记录。**

**日期：2026-11-03**

**决策来源：** 项目负责人明确要求移除项目资源页和预期部署版本，创建任务保留任务名称输入，源码信息只需粘贴开发提交的 MR/PR 地址，测试框架默认使用 main 最新提交；测试环境及补充要求可在单个任务 prompt 中告知 Agent。

## 背景

项目详情已经提供被测对象仓库和测试框架仓库的编辑入口。Cloud 另建资源修订页面重复管理仓库，并把环境连接、预期部署版本变成任务前置配置，超出了测试任务控制平面的职责。被测对象由其独立 CI 部署；源码或 MR 身份也不能证明某个环境已部署该版本。

## 决定

- HyperTest 聚焦测试任务生命周期、任务下发和测试产物归档。项目详情的编辑入口管理 `Project.repository_url` 和 `Project.test_framework_repository_url`；移除 Cloud 项目资源页及其创建前置步骤。
- 新建及编辑 Cloud 草稿使用 Project 当前的仓库配置，不接受用户选择的 `config_id`。请求必填 `expected_project_version >= 1`，服务端锁定 Project 后核对 row_version，不匹配时返回 409；Task 的 expected_version 独立校验。服务端在既有不可变配置修订表中保存内部仓库快照，供输入解析和执行追溯使用；该内部记录不再是用户管理的“资源”。项目编辑不回写已有任务快照；显式编辑草稿时重新固定 Project 当前配置，之后须重新解析。
- `inputs.mr_url` 为新建及编辑草稿的必填项，接受无凭据 HTTPS GitLab `/-/merge_requests/<id>` 或 GitHub `/pull/<id>` 地址。它是 Agent 检索 MR/PR 改动、定位被测对象、目标及内容的上下文；不是 SUT 部署版本、部署指令、部署证明或自动授权。MR 内容仍按不可信仓库材料处理。MR 仓库须与 Project SUT 地址同主机，且属于其精确仓库或下级路径范围；GitLab `/groups/<scope>` 按实际 namespace 规范化。内部快照以该范围内 MR 所在仓库作为 SUT origin，以 Project 测试框架地址作为 framework origin，拒绝兄弟路径和跨主机来源。
- 新建页面保留必填任务名称和 MR/PR 地址，另提供单个可选 `inputs.prompt`，供用户补充测试环境、流程、范围或需求；不再要求填写 PRD、PRD 版本、目标、流程、范围或检出选择器表单。Web 提交用户填写的 `title`；API 仍支持省略 `title` 时由服务端以仓库名和 MR/PR 编号生成（如 `service MR !123`），这是接口默认行为，不取代页面名称输入。旧 `prd_markdown`、`prd_version`、`objective`、`basic_flow`、`test_scope` 可省略，不把自动提示文字或 MR URL 伪装成用户提供的 PRD；实际提供的内容仍原样保存，未提供 PRD 时不生成 `prd_sha256`。
- 源码检出选择器与 MR 上下文分别记录。省略 `sut_selector` 时，服务端从 MR/PR 地址生成对应 head ref：GitLab 为 `refs/merge-requests/<id>/head`，GitHub 为 `refs/pull/<id>/head`，均以 `BRANCH` 选择器解析；省略 `framework_selector` 时使用 `BRANCH main`。最新提交指输入解析时观察并冻结的完整 SHA；下发后分支移动不改变本次输入。明确提交的既有选择器仍按原合同解析，已存草稿、冻结任务和复测来源不因默认值调整自动改写。Agent 使用已配置的原生工具（如 glab）从 MR 查询改动、关联需求和测试内容；仓库材料仍是不可信上下文。
- 哪个测试环境、执行位置和操作流程可由用户在任务 `prompt` 中告知 Agent，旧任务提供的目标、基本流程等内容仍保留；缺少信息时由 Agent 查询或澄清，不凭空补造。新仓库快照不保存 `environment`、`expected_deployment` 或部署匹配要求；HyperTest 不提供测试环境目录、环境配置、部署编排或目标部署版本管理。SUT 的 CI 和项目工具链负责部署，执行环境负责其网络、登录和工具准备。
- 产物可以如实记录 Agent/框架实际观察到的 SUT build、环境、命令、日志和未知项。这些是执行材料及结果来源，不构成平台对环境或部署的管理，也不能从 Git SHA、MR 或任务 COMPLETED 推断部署成功或测试 PASS。
- 任务身份、版本、原 key 对账、Worker lease/fence、独立 Attempt、报告来源及权限边界保持。任务 prompt 不自动授予新的平台权限或解除宿主访问限制；凭据不得放入 MR URL、prompt、报告或普通日志。模型和插件仍由 Harness 原生配置负责。
- 新建和编辑草稿的内部源码读取授权由当前双仓快照生成，不接受用户指定 `authorization`，编辑器不回传旧授权。这样更换项目仓库或 MR 后不会沿用旧目标，也不会继承旧环境权限；已冻结任务和独立复测仍使用各自原合同。

## 旧入口与历史范围

`CONFIGURE` 新写退役并返回 HTTP 410，产品移除项目配置列表入口。配置 GET 只保留供旧 CONFIGURE 原 key 的接受结果读回核对，新任务不通过该接口配置资源，也不要求先保存资源。任务读取仍可返回其原冻结仓库/配置快照；原操作 key 的查询及恢复保持既有语义。旧页面地址 `cloud?tab=resources` 只呈现 Cloud 任务列表。

本轮保留既有任务、Attempt、产物、凭据和旧不可变快照，不把旧环境字段复制进新仓库快照。编辑未冻结草稿须补充 MR URL，并按新输入合同保存；旧冻结任务与独立复测保持原来源和历史，不自动迁移或重新执行。未知外部操作仍不得重发。上述调整复用既有表，不要求数据库迁移。

本决定覆盖 ADR-019 及领域 §51、TMP §46、技术架构 §45、白皮书中要求单独管理 Cloud 项目资源、项目环境或预期部署版本的规则；ADR-032 的轻量 Worker 与 ADR-033 的独立复测语义继续适用。旧受控 SSH/HTTPS、环境路由及部署验收文档只解释各自历史 profile，不再定义新 Cloud 任务的产品配置入口，也不因此开放未经授权的网络或外部操作。

## 验证范围

必要自动回归覆盖页面名称输入和接口仅 MR 创建默认、可选 prompt 与无虚构需求、MR/PR head ref 和框架 main 默认值、Project 仓库快照与版本冲突、MR 必填/非法地址/范围越界拒绝、旧配置新写退役、草稿更新和原 key/版本行为，以及 Worker 对 MR 与 prompt 的传递。前端验证简化创建表单、项目仓库编辑保留及任务详情。实现、自动回归、部署健康和 USER_OWNED 功能验收分别记入交付记录。
