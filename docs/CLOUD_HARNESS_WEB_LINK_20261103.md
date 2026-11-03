# Cloud 原生 Harness Web UI 入口（2026-11-03）

任务详情“测试执行”区域新增“打开 DeepSeek Harness”，直接在新标签页打开已有原生 Web UI；有当前 Attempt 时可复制 `cloud-<attempt_id>` 会话 ID 辅助定位。本轮复用用户指定的 `http://10.66.66.3:3080/`，未增加创建表单、独立观察器或新的 Harness 服务，也没有猜测会话深链接。

Web 通过服务端非秘密配置 `HYPERTEST_HARNESS_WEB_URL` 向既有 setup 响应提供导航地址。未配置或无效时隐藏入口；拒绝非 HTTP(S)、内嵌凭据、查询参数和片段。链接采用 `noopener noreferrer`，认证由 Harness 原生页面处理，不转发 HyperTest 的平台身份。

## 验证与部署

- 实现及 Web 部署提交：`2d0ea58ed073dbc9420bd8218a16ce49cf032f51`，已推送。
- 47 项相关 BFF/client 回归通过；初次直接运行因当前 worktree 无 TypeScript 依赖未能加载，复用主 checkout 已有 node_modules 后完成。没有新增依赖环境。
- 设计机械检查无发现；Web Docker 构建（含类型检查）通过。
- 镜像 `hypertest-mac-web:2d0ea58`，ID `sha256:32a2c8c059fb208d360ab02e9799ee78aea0af45fdd9f03e35942940fc9cb025`。
- 只重启 Web；保留完整 Compose 链，追加 `cloud-harness-link-20261103/compose.json`。API/BFF/数据库容器身份保持，Worker PID 14711 保持，无迁移，schema `0045_local_archive_status`。
- Web healthy，原任务详情及 API 健康接口 200；实际 setup 返回配置地址，页面交付脚本含新入口及复制会话 ID。
- Harness 3080 入口可达，未认证请求返回 401。浏览器连接不可用，未验证已登录页面、实际点击及 SDK 会话在原生 Web UI 中的可见性或实时更新；不以首页入口上线宣称会话实时观察已验收。

没有提交、重启、取消或续接任何业务测试。原生 Web UI 的会话操作与测试结果继续遵循各自事实；链接本身不改变 HyperTest 任务状态。

本机部署证据：`~/.local/share/hypertest-mac/cloud-harness-link-20261103/deployment.json`、构建/启动日志；CURRENT_DEPLOYMENT 已按原对象更新 Web 字段并保留并发 Worker 补丁记录。
