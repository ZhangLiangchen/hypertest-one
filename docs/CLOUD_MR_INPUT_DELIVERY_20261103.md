# Cloud MR 链接创建交付（2026-11-03）

## 实现

按 [ADR-038](architecture/ADR-038_TASK_FOCUSED_CLOUD_INPUTS.md) 及本轮用户要求，Cloud 创建页仅必填 MR/PR 地址，保留单个可选测试说明。移除标题、测试目标、PRD/版本、流程、范围及两组检出表单；名称由仓库名与 MR/PR 编号生成。项目详情继续维护两个仓库。

API 接受仅 `inputs.mr_url`，不会填造 PRD 或其摘要。SUT 默认使用对应 MR/PR head ref，框架默认 `main`，解析时固定实际 SHA。Agent 收到 MR 和原文 prompt，使用已有工具查询改动与需求。源码身份不证明部署版本或测试通过。

草稿编辑保留已存需求与显式 selector，变更 MR 后重新推导 SUT 引用；服务端继续核对 Project/Task 版本、仓库范围、权限及原 key。独立重试保留原输入与历史，重新确认的范围优先于原 prompt。四份基础规范、项目指导和用户指南同步。

## 检查

- Web 相关自动回归 49 项通过，涵盖仅 MR 提交、中英文精简表单、历史草稿、请求未决及版本/原 key 恢复；TypeScript 检查通过。
- 后端关联回归 40 项通过，涵盖 MR/PR 默认引用、main、非法/越界拒绝、Project 版本、创建→解析→下发→取消→独立重试及 prompt 传递。Git fetch 测试使用模拟 Git，不是对用户 MR 的实际检出。
- 数据库回归复用既有专用测试 PostgreSQL，在独立临时库 `hypertest_cloud_form_test_20261103` 写合成 fixture，完成后已删除该库；未写业务 fixture，未新建全栈环境。
- Ruff、差异检查及 Impeccable 机械检测通过。Web 镜像构建通过；没有运行完整平台回归或手动 CI。

## 部署

代码来自已推送提交 `7da244bc2a741a5f890807681fb551b62e9091f4`，分支 `codex/cloud-web-lifecycle-validation`，远端 ref 已核对。

| 组件 | 部署身份 |
| --- | --- |
| API | `hypertest-mac-api:7da244b` / `sha256:6f9e9790ee6541a63151a22125471e157b9747cacfb89e5159c832eb42aabafd` |
| Web | `hypertest-mac-web:7da244b` / `sha256:93c133cdef93d72684be090d220491f06e76833d9ea1ee2b130e9f15e8cd2acc` |
| 宿主 Worker | 相同固定源码，PID 76421 → 81527；复用既有 LaunchAgent、源码目录和 Memory 环境 |
| Schema | `0045_local_archive_status`，无迁移 |

API 复用原依赖镜像并替换固定 Git 源码，继承 wheel RECORD，未重新发行依赖包。完整 Compose 链末尾追加 `cloud-mr-input-20261103/compose.json`，只替换 API/Web/维护容器镜像。BFF、数据库容器和启动时间不变；WireGuard、TLS、凭据、Local 状态、Memory 及独立 PowerContext 配置保持。未删除业务数据或重发未知工作。

API/Web healthy，API health、项目任务列表、指定创建页 HTTP 200；实际交付的页面脚本包含 MR、可选说明、main 默认文案，旧 PRD 版本与源码选择控件已移除。本机 `CURRENT_DEPLOYMENT.json` 和 README 已更新。证据在 `~/.local/share/hypertest-mac/cloud-mr-input-20261103/`：`deployment.json`、`form-delivery-check.json`、`health.json` 和构建/启动日志。

## USER_OWNED 验收

未创建业务任务、调用真实 MR、模型或 SUT。浏览器控制不可用（browser access host unavailable / cgWindowNotFound），未进行实际页面交互；自动回归、脚本交付检查及部署健康不代替用户功能验收。
