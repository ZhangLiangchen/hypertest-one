# 创建测试任务页显示修复

日期：2026-10-26（Asia/Singapore）。范围为 PC 宽屏下 `/projects/[projectId]/tasks/new`。

## 原因与修改

- 原共享 Form 直接使用 `workspace-panel`；AntD Form 的默认 `padding: 0` 覆盖面板留白，实测内边距为0、标题距边框仅1px，输入框和本地提交按钮贴边。改由独立的语义 section 承担面板样式，内部 Form 继续管理字段和提交。实测内边距24px、标题距外缘25px，无横向溢出。
- 云端资源未完成读取时，原实现提前渲染“请先保存项目资源”；读取失败时也会混同为空资源。现在首次读取显示加载态，读取失败显示错误，仅成功确认无资源后显示空态。
- 已加载的 Cloud 表单在刷新和失败时保持挂载，保留草稿；失败时禁止创建。执行方式切换保留字段，Local 创建不依赖 Cloud 是否可用，原请求/key/UNKNOWN恢复与授权限制保持。

不改变 API、数据库、任务身份、幂等、权限或测试结果；未创建任务、签发凭据、执行模型或 SUT。

## 验证

- 相关组件回归19 passed / 0 failed / 0 skipped，含新增5项四态、面板结构及失败禁止提交检查；TypeScript检查通过，Impeccable layout检测无发现。
- 正式构建 PC 1440×1000 浏览器确认真实页面的 Cloud/Local 两种布局，内边距24px、无横向溢出。另用仅浏览器内的合成配置阻塞/失败响应，确认加载不误报空资源、切换和刷新失败后保留同一PRD输入节点及内容、失败禁用创建。0次业务写入、0个JS运行时错误；注入的503有预期HTTP错误日志，不计作应用脚本错误。
- 浏览器初次状态检查曾在请求到达拦截器前检查同步变量；调整为等待请求到达后完成确认，未为此修改应用代码。前后截图、测量和日志保留在 `output/playwright/task-create-fix-20261026/`。浏览器已退出。
- [代码CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40261101670)：Web **281 passed / 0 failed / 0 skipped**、Typecheck、Build均通过，Memory最小依赖检查通过。平台旧FRAMING拒绝测试遇到发送端BrokenPipe：服务在非法Content-Length头处正确拒绝并关闭，测试继续发送独立body形成竞态。仅修改该参数项为只发非法头，拒绝类别、502、无upstream及无泄露断言保持；复用现有Python环境跑该无DB测试文件17/17通过。测试修正提交为 `dedd1b2f3ad5ff740ecdfab3a3e003acdeb81ecb`，不改变已部署应用代码，无需重建镜像。最终[代码CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40261592495)的 Web、平台 `test`（含lint/迁移/pytest）及 `memory-api-profile` 三个任务全部成功；保留首轮失败记录。

## 部署

从已push main fetch并固定完整源码 `d2d329ef575978e978f7b322a4a4123122688760`，复用现有干净checkout和构建缓存，仅停止、重建并更新Web容器；没有迁移。

| 项目 | 实际结果 |
| --- | --- |
| Web源码 | `d2d329ef575978e978f7b322a4a4123122688760` |
| Web镜像 | `sha256:58653a0269d5e63531f38e40087d98f84f8cb69eb0b9b5687f499dddc50bbea8` |
| Web容器 | `0da08cf1237b628a415d87b0b46960f45655d667a27d92708004c22999e8820c`，healthy |
| 原Web镜像 | `sha256:e10af0c704e75235aad87fc463b2337195f67edbe6017678adbe7ba31bd308be`，保留 |
| 最小检查 | Web根页200、SSR样式和CSS200、API/入口健康ok，既有网络守卫通过 |
| 其他角色 | API/独立Cloud Worker保持76edb01、schema0028；legacy Worker、数据库/数据卷、历史及访问限制保持 |

构建前根盘可用约6.8GiB，后约6.2GiB；未清理历史镜像或构建历史。功能验收保持 **USER_OWNED**；上述检查为变更回归与部署健康检查。
