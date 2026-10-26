# 项目工作台多 Agent 文案更新

日期：2026-10-26（Asia/Singapore）。按用户确认的能力修正中英文文案：本地接入 Codex、Claude Code、DeepSeek Harness；云端支持 DeepSeek Harness + Codex 测试。

首页说明改为“按项目统一管理本地与云端测试任务、用例和报告”，标题改为“让测试工作，有迹可循”。同时同步首页空态、创建项目说明及使用指南，保留本地会话同步与云端产物归集的区别，以及任务进度和 Agent 报告结果分别展示的语义。没有调整业务逻辑、权限、任务身份或测试结果。

变更已合入 main，从已push并fetch固定的 `72322d66417f17b6cecad2f194a6866cec18f3d3` 构建，仅更新 Web；镜像 `sha256:e3e5448d77b35c52dd3985938082333f1a64254ac5f83a1aecb1877080185182`，容器 healthy，原镜像 `sha256:92b6f2c349766015b32243474a9bf5296ef2fb02ea61a6f2a77588126b2c8560` 保留。API继续66f69f1/schema0029，独立Cloud Worker继续76edb01，其余服务和访问保护保持，无迁移。

按低影响文案修改处理：检查差异，复用部署构建的编译/类型检查，不新增专用测试或重复本地全量回归。PC 1440px 中英文显示无页面横向溢出；首页、创建说明及指南文字确认，首页HTTP200含新文案，入口API健康ok，0次业务写入，未调用模型/SUT。浏览器语言选择器的自动定位未命中后，改用既有locale cookie确认英文显示，未改动语言选择逻辑。

[代码CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40285512078) 的 Web测试/类型/构建及memory-api-profile通过；平台test任务被取消，未计通过，未重跑。本轮没有用户功能验收。浏览器已关闭；截图、日志和部署回执保留于 `output/playwright/multi-agent-copy-20261026/`。构建前根盘约4.6GiB，后约4.0GiB，未清理历史。
