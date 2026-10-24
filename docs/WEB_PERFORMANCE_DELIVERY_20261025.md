# Web 首屏样式、滚动与加载性能改进

日期：2026-10-25（Asia/Singapore）。本轮范围为 PC 宽屏；实现、部署及用户功能验收分别记录。此前全页面视觉统一保留在 [Liquid Glass 原交付](LIQUID_GLASS_WEB_DELIVERY_20261025.md)。

## 四项实现

1. **首屏组件样式随 HTML 到达。** 接入与现有 Next 15 / AntD 5 / cssinjs 1.24.0 匹配的官方 `@ant-design/nextjs-registry@1.1.0`。`AntdRegistry` 按请求收集样式；静态 theme 与 `motion: false` 在服务器和浏览器一致，避免 hydration 后再切换 token/hash。按钮 hover/press 仍使用遵守 reduced-motion 的短 CSS 反馈。
2. **导航采用静态玻璃材质。** 顶栏、项目导航和历史 Run 导航统一不透明浅色渐变、高光及两层阴影，移除实时 `backdrop-filter`，减少滚动时对背后内容的重新采样。保留原有配色、字体、圆角、导航和实体阅读面；未增加移动端或竖屏范围。
3. **控制记录渲染和后台刷新。** Local 当前报告先展示带结果/修订的摘要，展开后才挂载完整原文；用例/报告历史和 JSON 快照按需创建，六组记录每页 20 条。Run 按当前页签、运行/Job/输入状态调整轮询，终态停止记录定时器，活动 Job 保持 1.5 秒观察，等待输入 5 秒，静止/受阻状态放慢；capabilities/harness 控制观察、刷新及 mutation invalidation 保留。大表分页。Cloud 定时获取 summary，接受版本变化才获取该固定版本的完整文档，并核对 Project、Task、Attempt、version，失败保留旧文档。
4. **非首屏功能按需加载。** 指南 Drawer、创建项目、legacy 创建运行、通用 ClientModal、Cloud 资源和创建表单拆包；对话框首次打开后保留实例，已访问 Cloud 页签保留，关闭/切换不会丢弃草稿。复制输入确认、完整策略、原幂等 key、UNKNOWN 对账和固定版本读回语义保持。

Local 接口仍完整读取所选固定版本；本轮减少其渲染与 DOM 成本，不改变传输契约。

无 API、数据库迁移、权限或领域状态改动；没有对真实业务库写入测试 fixtures、创建验收任务、签发凭据或启动模型 / SUT。

## 测量与回归

生产构建的 PC 1440×1000 浏览器实测：

| 检查 | 改进前 | 改进后 |
| --- | --- | --- |
| 禁用 JS 时的 AntD 样式 | 无内联组件样式；主按钮灰色、高 24.39px | 官方 registry 已含样式；主按钮蓝色、高 38px |
| 启用 JS 后主按钮 | 蓝色、高 38px，与首屏不同 | 蓝色、高 38px，与首屏一致 |
| 导航 backdrop filter | blur(24px) saturate(1.3) | none；静态浅色渐变 |

SSR 根页 HTML 从约 21.8KB 增至 200.7KB（本轮 gzip 估算 23.3KB），其中约 179KB 为首屏组件样式。这是把关键样式随 HTML 交付的明确成本；不能只按静态 CSS 文件大小评价首屏。

同一 manifest 去重口径，统计 layout + route 的初始 JS 文件；逐文件 gzip 大小为估算，**不代表实际网络传输、总加载大小或时间**，不包含 HTML/CSS、prefetch 或首次打开功能后的动态包：

| 页面 | 初始 JS 文件数 | gzip 估算 | JS 减少 |
| --- | --- | --- | --- |
| 项目列表 | 18 → 16 | 421.2 → 395.6 KiB | 6.1% |
| 项目工作台 | 25 → 20 | 489.6 → 430.8 KiB | 12.0% |
| 历史 Run | 24 → 24 | 498.7 → 488.5 KiB | 2.1% |

合成大历史（100 份当前报告、每类历史 500 条）的同进程 SSR 对比：初始 DOM 元素 36,497 → 1,236（减少 96.6%），HTML 9,794,350 → 70,566 bytes，`pre` 2,101 → 1。所有历史均可分页/展开读取，原文、FAIL 与固定修订不变。这是合成渲染测量，**不是用户 PC 的 GPU/FPS 或业务任务性能证明**；本服务器的浏览器使用软件绘制，未宣称真实设备帧率。

- 定向回归覆盖：轮询/Cloud 46 项、Local 记录/创建 24 项、创建运行/草稿相关 53 项、共享延迟 UI 5 项，以及其他相关组件检查；各组有重叠，不相加为总数。统一类型检查通过。
- PC 浏览器六个受影响页面的合成截图无页面横向溢出、未匹配 API 或运行时错误；原文展开后内容一致。正式构建另确认项目/运行/Cloud 资源草稿关闭或切换后保留，指南按需打开，减少动态偏好不丢草稿。
- Impeccable 机械检测无发现；范围内视觉复核 `disposition: ship`，设计文档/sidecar 已同步。预览浏览器交互检查曾因 AntD 中文按钮自动插空格、关闭图标本地化而出现 locator 超时；修正检查定位后，在正式构建完成检查，未因此改动应用实现。
- CI 首次发现 source-preparation 测试 loader 未映射新 helper，六项加载失败；补齐映射后该文件 8/8 通过。随后发现既有 Memory 竞态测试以固定事件循环次数等待，在并发负载下过早超时。改为单调时钟 deadline、条件完成即返回及事件循环让出；旧机制已用150轮异步链确定性重现，新增和相关回归48/48通过。保留原失败，不改写为首次通过。

## 部署身份

从已推送 main fetch 并固定源码 `8c18232ef28455fd41155946414461a0926a72ab`；复用当前 checkout/依赖/构建缓存，在本机停止受影响 Web，按原 Dockerfile 构建，再仅更新 Web 镜像并启动。类型检查、页面生成和生产优化构建成功。

| 项目 | 实际结果 |
| --- | --- |
| Web source | `8c18232ef28455fd41155946414461a0926a72ab` |
| Web image | `sha256:e10af0c704e75235aad87fc463b2337195f67edbe6017678adbe7ba31bd308be` |
| Web container | `a811b0272f85ed0e5b346e3dc56a8739b52bedde7a7aeb579316dc097efd01d5`，healthy |
| 原 Web image | `sha256:bba398e4b6fba5f7566ddc916bbf1446e2546ef28b20e069e152a7484714f841`，保留 |
| 基础检查 | Web 根页 200、首屏 AntD registry/样式存在、CSS 200、API 及容器入口健康返回 ok；既有网络守卫通过 |
| 其他角色 | API/独立 Cloud Worker 保持 `76edb01...`，schema0028；legacy Worker 镜像、数据库/数据卷/历史及访问保护保持 |

本轮构建前根盘可用约 9.1GiB，后约 6.9GiB；未自行删除历史镜像或构建历史。临时预览进程和浏览器已退出；本轮测量/部署材料保留于 `output/playwright/performance-20261025/`。

测试加载器与等待机制的后续修正只涉及测试，不改变已部署应用代码，不为此重复构建。部署源码与 Git 文档/测试后续提交分别标识。

用户功能验收维持 **USER_OWNED / PENDING**。本轮组件回归、合成浏览器检查和健康检查不构成真实模型/SUT执行或用户验收，不升级任何历史结果或证据资格。

## CI 补录

- 应用实现：`8c18232ef28455fd41155946414461a0926a72ab`，其首次 [CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40131292997) 保留 source-preparation loader 6 项加载失败记录；API测试与最小依赖检查通过。
- 测试映射修正：`1c243c7dc190877739cc85d5ec8137cb3b74bde7`；[第二次 CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40131420177) Web 272/273通过，保留上述既有 Memory 等待过早失败。
- 测试等待机制修正：`5ff8c00ef3a043947438099e7cc8e3b0433dc2b4`，与部署源码相比只有测试变化；[最终代码 CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40131660909) Web **276 passed / 0 failed / 0 skipped**、Typecheck 和 Build 均通过；平台 `test`（含 lint、迁移与 pytest）及 `memory-api-profile` 均通过，最终工作流为 **success**。
