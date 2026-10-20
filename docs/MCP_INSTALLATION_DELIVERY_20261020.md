# MCP 安装发行与 Web 引导交付（2026-10-20）

本轮交付正式 MCP wheel、独立本机 `setup` / `doctor`，以及
**创建测试运行 → 我的电脑**中的三步安装指引和项目专属安装 Prompt。
[PR #19](https://github.com/ZhangLiangchen/hypertest-one/pull/19) 已合并，
Web 于 **2026-10-20 08:29:06.873775 UTC** 完成独立发布。
API / Worker 仍是此前 ADR-016 核心发布；本轮没有迁移或新的正式测试周期。

## 发行身份

| 项目 | 已验证值 |
| --- | --- |
| 固定发行 | [mcp-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/mcp-v0.1.0) |
| 合并源码 | `980f27ab2341f1d62b2ee4896a321a240555548b` |
| wheel | `hypertest_one-0.1.0-py3-none-any.whl`，341,961 bytes |
| wheel SHA-256 | `a44b16c7394b41bdf104e9c5458b29567b9a9f1764044e62bc14f7b105eb796a` |
| 附件 | wheel、`release-manifest.json`、`SHA256SUMS`、`INSTALL.md` |
| PR / main CI | 989 passed、21 skipped；Web 124 passed，typecheck / production build 通过 |

四份附件已匿名通过 HTTPS 下载，清单中的源码、大小和全部 SHA-256 校验通过；
下载 wheel 与本机从相同固定提交构建的 wheel 字节一致。发行工作流从实际 tag
导出源码，在仓库之外的全新 venv 安装 wheel 并核验模块、CLI 和捆绑资源后才发布。
安装方法见[安装指南](INTERACTIVE_MCP_CLIENT.md#install-and-pair-from-my-computer)。

## 用户流程与权限边界

1. 在“我的电脑”选择通用 stdio Agent 或 Codex Desktop，复制安装 Prompt。
   内容包括平台 HTTPS API、项目 ID、固定发行和安装步骤，不包含密钥值。
2. 部署管理员将既有 `HYPERTEST_CONNECTOR_OPERATOR_KEY` 私下交付到本机用户拥有的
   `0600` 文件，或由用户直接在独立 CLI 的隐藏 TTY 提示中输入。
   普通用户没有下载该全局 Operator 密钥的 API；Git / glab / Provider 登录不能代替它。
3. Agent 安装校验后的 wheel，调用独立 `setup` 配对并注册此项目权限，将生成的
   绝对命令和配置路径合并进宿主 MCP 配置，保留其他服务；运行 `doctor` 后按宿主要求
   重新加载 / 重启，再查询项目。密钥不得粘贴进聊天、命令参数或 MCP 配置。

通用宿主首版支持 **macOS / Linux stdio** 的任务提交、读取和 CLOUD 请求。
当前 Agent 的 LOCAL 执行需要受控 Codex Desktop 适配器、被接受的源码、原生会话证明
和显式执行绑定；安装 / 配对不隐式取得源码、问题单或执行权限。首版不支持 Windows，
不宣称任意 Agent 都支持 LOCAL，也不宣称当前会话能够热加载新工具。
网页表单继续创建受管 Harness Run；MCP Run 由当前 Agent 另行发起。

`setup` 的写请求先持久化 UNKNOWN 意图，再发送请求。结果不明或一次性 token
丢失时保留原目录、node key 和 client identity，要求管理员对账；不自动创建替代身份、
重复签发或轮换 token。已完成的同参数重复 setup 保留原设备和客户端身份。
独立准备 CLI 不属于 Agent 可调用的 MCP 管理工具，也不启动模型。

## 实际验收

- 新隔离 PostgreSQL / 严格 HTTPS / 实际 API 上，通用与 Codex setup 配对和注册成功；
  通用模式限四个项目 scope，Codex 模式另行显式授予受控适配器所需能力。
  重复安装保留原设备 / client / registration；没有源码或问题单授权。
- 37 项本机相关测试通过；其中22项覆盖 setup。未知结果、权限、TLS、目录保护和
  私有文件路径由相关测试覆盖。正式发行 wheel 的 `doctor` 实际返回 READY，
  integration authorization CHECKED；device token 只检查私有文件，不冒称做了 live probe。
- 正式发行 wheel 在仓库外私有 venv 中，经官方 MCP SDK → stdio → 私有 daemon →
  严格生产 HTTPS 列出 **18 个工具**，使用既有限项目授权查询未存在的 submission key，
  得到预期 NOT_FOUND。使用独立临时本机 state，验证后 daemon 已停止；没有签发新授权。
- 本机真实浏览器验证中英文引导、复制、无密钥提示和390px布局；对话框无横向溢出。
  线上 Chrome 验证中文三步引导、Codex 宿主选项、“已复制 Prompt”状态、预览中实际
  项目 / API / host 匹配及空密钥刷新后输入框获得焦点的就地提示。
  内置浏览器因不信任私有 CA 未继续，未绕过证书警告；Chrome 采用其既有信任配置。

本轮没有新生产 Run、配对 / grant、源码传输或问题单操作，也没有重做完整 Runner / Gate
周期。[此前33项真实 HTTP 周期](ADR016_PRODUCTION_DEPLOYMENT.md)属于独立验收，
不作为本轮安装后新周期的证据。生产只读连接与隔离 setup 的证明范围分别保留。

## Web 发布与保全

| 组件 | 实际状态 |
| --- | --- |
| Web 源码 | `980f27ab2341f1d62b2ee4896a321a240555548b`，独立导出到 `web-releases` |
| Web 新镜像 | `sha256:07ad4852ac16a270bf8ed832c495eaff3ed9936006bed8f9d85547be34a9705b` |
| Web 原镜像 | `sha256:6b10ea21d3d3d9128cc77d0cff14d7d4e9de27d45e0f5af6819a4d705171e795`，保留用于回退 |
| API / Worker 源码 | `c7cd43ad6346d8ce6c85564f7838afbb017f2da4` |
| API 镜像 | `sha256:8cfc764b1ccacc97ff3faf2b23b61b937bfdf0b1f29afda3349b3dd954d25a33` |
| Worker 镜像 | `sha256:7796433173907d7b4d3aa62f55a24dedc49af8ac91f959b3b1999a13a1c47f60` |
| Schema | `0020_interactive_tool_inbox`，没有迁移 |
| 固定 ops | `61b4e2800472db67d0e52cbc1507663fc8ac9d707b43e308e6fb88e32ff8214d` |
| Bridge | `95e92c584897ff18bc1a0006823891ca45a619be` |

Web 构建沿用既有固定 Node digest，Dockerfile、锁文件、API / Worker 依赖及迁移未变。
既有维护锁内只原子替换 `compose.env` 的 `HYPERTEST_WEB_IMAGE`，通过固定 ops 的
`compose_command(..., up, -d, --no-deps, --no-build, --pull, never, web)` 重建 Web，
保留原 TLS / GitLab overlays。没有调用会停止整栈的 `start.start` / `start.py`。
Web healthy 后对原 nginx 执行配置检查和 reload，以刷新上游；nginx 容器未重建。
`container-current` / `ops-current` / `bridge-current` 均未切换。

首次切换因 Docker inspect Mounts 数组顺序触发严格比较失败，自动恢复旧 Web。
原始失败记录保留。确认挂载内容全部相同后，第二次仅按 Destination 排序比较每个完整
mount 字典，没有放宽 Source / RW / Type 等字段；最终 **35项保全检查全部通过**。

两次切换之间重新采集独立基线。58张非节点表的4,016条完整行 count / hash 相同，
另2个节点的稳定配置及集合相同，仅4个连接观测字段按既有规则单列；时间、generation
和 row version 不回退。运行 heartbeat / runtime-control 表不纳入业务行相等断言。
85个 Artifact、8,533个 workspace、13个 Bridge state 文件 hash，以及28个原生会话
文件的 hash / 大小相同。OAuth metadata / 登录状态、受保护配置、授权行、SSH、VPN、
UFW、Docker 守卫、unit、ops / Bridge 源码均相同。API / Worker / PostgreSQL / nginx
的容器 ID、镜像、挂载、启动时间和重启计数相同；没有重启数据库。

**Web-only 备份例外：**本次没有后端 / schema / 数据写入变更，沿用此前 ADR-016 已验证的
配对冷备和隔离恢复记录；没有新做冷备或恢复演练，不把历史备份描述为当前时刻的恢复点。
后端持续服务，没有关闭 API admission。此范围的回退只恢复旧 Web image；不得恢复覆盖
生产数据库。API / Worker / schema / Bridge / 存储变更仍须执行常规配对备份流程。

08:32:44 UTC 的 `ops/check-remote.sh` 为10 / 10就绪。切换完成后采集的 API / Worker /
Web / nginx 日志中无 HTTP 5xx 或 traceback；这不涵盖两次切换窗口，也不主张 PostgreSQL
没有预期的遥测锁竞争 ERROR。五个容器在后续观测中仍 healthy，ID / image / 启动时间 / 重启计数未变，
OOMKilled 为 false。原服务器与本地 Connector 受管配置保留；本轮不冒称重跑
两种受管模式的完整周期。

完整快照、切换日志、失败与成功结果、发行校验和截图保留在本机私有
`~/.local/share/hypertest/mcp-onboarding-20261020`；服务器切换材料在
`/opt/hypertest/deployments/mcp-onboarding-20261020`。不提交密钥、实际入口、私有源码
或原生会话身份。本轮隔离测试 API / Web / 数据库及临时 daemon 已停止；数据卷与
验收证据保留，既有本地受管 Connector 未停止。
