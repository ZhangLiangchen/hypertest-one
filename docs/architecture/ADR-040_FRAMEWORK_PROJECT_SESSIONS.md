# ADR-040：Cloud 会话直接在测试框架项目中工作

- 状态：Accepted
- 日期：2026-11-04
- 决策来源：用户明确要求沿用本地 Harness 用法，直接以测试框架仓库为工作目录创建会话；xblock 使用 hypervise_pure，原生项目名称为 hypervise。

## 决策

HyperTest 传递任务、用户消息并归档结果，Agent 自主安排测试工作。新 Cloud 会话的原生项目目录和实际工作目录均为可复用的测试框架仓库；不以每次执行的私有消息目录作为 Harness 工作目录。Agent 按需要选择 Git 工作树，平台不强制为每次会话创建工作树。

按完整仓库身份区分框架项目，忽略 HTTPS/SSH 与 .git 的等价拼写，不按展示名称合并不同仓库。首次从已解析的框架源码准备共享仓库；后续保留已有分支和修改，不在另一个任务开始时自动 reset/checkout。ADR-038 的输入 SHA 仍是冻结的请求参考；共享仓库实际版本与修改由 Agent 核对并在结果中记录，不能把输入 SHA 当作实际执行版本的证明。本条取代宿主 Cloud profile 对实际框架工作目录必须等于每次执行独立检出目录的要求。

测试流程及产物位置沿用框架原有约定，与本地测试相同。HyperTest 从框架目录直接读取 Agent 明确提交的原文件归档，不要求搬运到平台另设目录。仅消息、回执和知识请求保留内部独立传输路径；上传 payload 的相对文件名相对于框架目录 artifact_workspace，输入快照不修改。根会话使用框架目录，原生子智能体继承项目来源目录。

原生 Harness 的 Workspace 由单一 Web/桌面宿主维护。薄适配只读取会话 header，通过官方 workspaceRegistry.create / attachSession 归组，不启动模型、不打开或恢复 Agent、不直接并发改写 workspace.json。SDK 进程不写原生 Workspace registry。

## 已核对的 hypervise_pure 结构

已读取框架 AGENTS.md、docs/codex-sut-operating-rules.md、README.md 和 Makefile：框架已有 artifacts/allure-results、artifacts/logs、docs/usecases 及 docs/reports 等产物位置；make report 会实际运行 pytest，不把它当作纯归档命令。平台只传递任务并归档明确选出的原产物，不重建一套测试流程或擅自执行框架命令。

## 既有会话

缺少新项目目录记录的旧会话保留原目录和 ID。当前官方接口没有跨目录改归属的方法；不修改旧 header 或移动原会话日志来伪造新来源。既有测试结果、未知外部操作及原 key 恢复规则保持；改变新会话的工作目录不授权重跑旧测试。

## 验证与交付

直接检查共享仓库复用、不覆盖已有修改、错误仓库拒绝、SDK 实际 cwd、独立交接路径及原生单宿主归组。自动回归和部署健康分别记录，不创建业务验收任务或触发模型来验证目录设置。
