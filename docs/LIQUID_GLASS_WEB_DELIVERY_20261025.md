# 全页面 Liquid Glass 视觉统一

日期：2026-10-25（Asia/Singapore）。本轮只调整 Web 的视觉与布局，开发、部署和用户功能验收分别记录。

用户后续明确只在 **PC 宽屏**使用。此约束成为本轮交付目标，不继续投入移动端或竖屏适配。

## 实现

- 覆盖全部 8 个页面路由：项目列表、项目工作台、新建任务、Cloud 工作台、Memory、本地任务详情、Cloud 任务详情及历史 Run。
- 提取 `WorkspaceHeading`、`ProjectNavigation`、`WorkspaceLoading`，统一标题、返回入口、操作区、状态元数据、项目导航与加载占位。
- 沿用 Apple Liquid Glass 方向：玻璃材质用于导航，表单、表格、原始报告与证据使用不透明阅读面；统一圆角、留白、标题尺度、页签与表格密度。
- Cloud 双仓配置、需求和授权预算按相同规则分组；Memory 补齐面板并消除嵌套表格卡片；新建任务居中，保留 Cloud 表单独立面板。
- 保留中文/英文、键盘焦点、减少动态效果、减少透明度、高对比度和 forced-colors 回退。

未改变 API、权限、幂等账本、历史或测试状态。Cloud / Local 的任务身份继续独立；任务进度、reported result 与正式证据/判定保持原语义；Memory 继续作为历史参考。

设计参考：[Apple Liquid Glass](https://developer.apple.com/documentation/TechnologyOverviews/liquid-glass)、[ReportPortal 测试执行列表](https://reportportal.io/docs/test-executions/)。Web 使用 CSS 半透明和 backdrop filter 表达材质，不实现 Apple 原生光学折射。

## 技能与相关回归

使用仓库既有 `impeccable`；从 `openai/skills` 安装用户级 `playwright`。复用原 checkout、node_modules 和 Node 环境；为浏览器截图补充 Chromium 运行库与中文字体，没有新增完整平台或测试数据库。

相关自动回归共 **84 passed / 0 failed / 0 skipped**，为下列互不重叠的文件组：

| 文件组 | 结果 |
| --- | --- |
| Cloud client / resources / recovery | 27 passed |
| Memory UI / Local task creation / session tasks | 24 passed |
| Canonical details / run harness / record management / input answers / Local mode guide | 33 passed |

TypeScript 检查通过；Impeccable 检测无发现。现有组件测试为共享 UI 新 import 补充加载支持，保留原业务断言；导航断言随链接迁入共享组件而调整。

浏览器首轮覆盖全部 8 route 与 Cloud 资源/创建两个子视图，PC 1440px 的 10 张截图均无页面横向溢出。共享 Modal / Drawer 另作桌面检查；浏览器 API 全部由本地合成响应接管，无业务写入和运行时错误。用户补充 PC 范围前已生成的 390px 截图保留为当时的回归材料，不作为移动端交付承诺。

独立视觉复核发现 Memory 面板间距和 Warning 派生底色两项问题；已同批补齐 24px 分隔及显式浅色语义 token。Memory、Local 详情、历史 Run 的桌面确认截图无溢出、无运行时错误，21 项 API 读取均由浏览器 mock 接管。预览开发进程曾因自身内存阈值重启；重新加载后完成确认，未据此改动应用运行边界。

复核者对上述两项视觉修复及设计文档同步均判定 `resolved / ship`；该结论范围是本轮列出的修复项。DESIGN.md、token sidecar、surface brief 和 PRODUCT.md 已同步 PC 宽屏范围与共享组件契约。

桌面中英文切换后表单草稿保留；高对比度与减少动态效果下，项目导航为不透明 `rgb(246,249,255)`、`backdrop-filter: none`、过渡 `0s`。

## 部署

从已推送分支 `codex/liquid-glass-unification` fetch 后固定完整源码 SHA **`4f54a4f99ba7bb4e65b444bbffd83963388677b3`**；复用当前干净 checkout，在本服务器停止受影响的 Web 后按 `web/Dockerfile` 构建。Node 基础镜像固定 digest，构建内编译、类型检查、页面生成和优化全部成功。

| 项目 | 实际结果 |
| --- | --- |
| Web image | `sha256:bba398e4b6fba5f7566ddc916bbf1446e2546ef28b20e069e152a7484714f841`；revision 为上述完整源码 SHA |
| Web container | `9f75df50c3886111c7e3f09664c3970be34ef81fe16876101c465244933f9e7d`，healthy |
| 替换前 Web | `sha256:0e534f0f93c8029087216a948538804544692484f2d9c4d03c0d9e2dbe9f0d16`，镜像保留 |
| 服务与入口 | 只替换 Web，容器 nginx reload 刷新上游；五容器 healthy，ingress guard protected |
| 最小冒烟 | ingress/API health 为 ok；Web 根页 HTTP 200；其正式 CSS HTTP 200，包含共享标题和项目导航样式 |
| API / Worker / schema | API 保持 76edb01、legacy Worker 保持 55de50e；独立 Cloud Worker / Bridge 未迁移；无 schema 变更或迁移 |
| 资源与清理 | 构建前约 11GiB、完成后约 9.2GiB 可用；本轮预览进程与浏览器已关闭，无新平台/测试库；保留构建缓存、截图与源产物 |

原 TLS / VPN / SSH 和访问限制保持；仅更新 compose.env 的 Web image 键。部署和冒烟回执在本机 `output/playwright/`，不包含业务凭据。后续补录本节及当前身份指针是纯文档提交，不重建镜像。

本轮不创建验收项目、任务、凭据，不调用模型或 SUT；功能验收保持 **USER_OWNED**。
