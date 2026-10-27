# HyperTest CLI Prompt 安装交付（2026-10-27）

本轮将新 CLI 的推荐安装方式改为“复制 Prompt，交给本机 Agent 执行”。用户从 HyperTest One 页面或 GitHub Release 取得完整指令，由 Agent 完成固定版本下载安装、双摘要校验、适用 Skill 安装及配对发起，用户在网页确认授权。

这是 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 的接入体验改进，不改变归档、授权、任务身份或原 key 恢复合同。当前公开 CLI 仍为 [cli-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0)，原包、安装器、manifest、Git tag 和源码身份不重建或重标；原始归档交付见[原记录](LOCAL_ARCHIVE_DELIVERY_20261027.md)。

## 交付状态

| 维度 | 本轮状态 |
| --- | --- |
| 页面与 Prompt | 已实现：页面以复制安装 Prompt 为主入口，保留手动命令；平台/项目上下文随 Prompt 明确传入 |
| 文档 | README 与[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)以 Prompt 安装为推荐路径；旧 Local 安装推荐标为历史 |
| GitHub Release | 2026-10-27 04:48 UTC 已发布中英文 Prompt 附件，发行说明首部提供完整中文 Prompt；公开下载核验通过，原四资产 ID/摘要与 tag 保持不变 |
| Web 部署 | 已按推送后的 Git `8b90efb878c51568c9e35901ad31116b742a5f7f` 完成 Web Docker 构建和部署，相关健康检查通过；API、schema 与 CLI 运行时保持原身份 |
| USER_OWNED | 未执行。真实本机安装、技能发现、用户网页授权仍由用户验收 |

## 用户流程与入口

1. 全局「CLI 授权」页复制安装 Prompt；项目入口带入明确 Project ID，平台地址来自当前配置的 HTTPS origin。
2. 用户将 Prompt 交给本机 Agent。Agent 检查实际运行环境与既有安装，下载指定 `cli-v0.1.0` 安装器和 CLI 包，分别验证固定 SHA256 后执行受管安装。
3. Agent 安装 `hypertest-archive` Skill，复用匹配的已有 profile；缺少绑定时发起配对，显示授权地址和短码。
4. 用户在网页核对上传身份、项目、权限与期限后批准。Agent报告实际安装和绑定结果；未批准或未决时如实保留待处理状态。

不在平台页面时，使用 [中文通用 Prompt](cli-install-prompts/hypertest-cli-install-prompt.zh-CN.txt) 或 [English prompt](cli-install-prompts/hypertest-cli-install-prompt.en.txt)。GitHub Release 提供相同文本附件，发行说明包含完整中文 Prompt。通用文本先完成安装，再在需要绑定时询问 HTTPS 平台地址，不猜域名、项目或上传目标。

## 单一文本源与发行身份

页面 Prompt 与中英文发行文本由 [cli-install-prompt.ts](../web/lib/cli-install-prompt.ts) 生成，共用 [cli-release.ts](../web/lib/cli-release.ts) 的固定发行信息。页面增加上下文时只补明确 server/project，不改变包和安装器的摘要；通用发行文本无用户凭据或预设项目。

维护时复用已有 Web 依赖，在仓库根目录运行：

```sh
node scripts/render-cli-install-prompts.cjs --write
node scripts/render-cli-install-prompts.cjs --check
```

`--write` 从单一文本源生成两份发行文本，`--check` 核对仓库文本是否一致。未来升级应使用对应 CLI 版本及其固定地址、源码和摘要生成、发布 Prompt，不借仓库全局 Latest 选择旧 `local-v*` 包，也不改写旧 CLI 包的身份。

| 项目 | 保持的固定身份 |
| --- | --- |
| CLI 版本 | `0.1.0` / `cli-v0.1.0` |
| CLI 源 Git | `d02ab1dd893200eb2eee398d795f9b96a41ab768` |
| 安装器 SHA256 | `20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95` |
| CLI 包 SHA256 | `c96c8bb0380658d9eee2efd890eee6de95e9fbec11ec6d3255ba49448334713e` |

完整安装 Prompt 是给用户主动交给 Agent 的操作说明，不是自动执行入口。安装器保持受管命令/版本冲突检查，已有自定义命令或被修改 Skill 文件不覆盖；私有配置、旧版本、journal 与未决 key 保留。Codex 使用现有全局 Skill 安装命令，其他宿主必须明确已核实的技能目录，不推定已通过宿主验收。

安装 Prompt 不申请 Operator key、不替用户批准网页授权，不创建任务、执行测试、上传产物或安装旧 MCP/Hooks/bridge/常驻进程。已有旧配置清理由用户另行发起。SENT、UNKNOWN、失答和 NOT_FOUND 仍只按原 request ID/key 查询；无法确认的配对不能换 key 重发。

## GitHub Prompt 发布记录

[cli-v0.1.0 Release](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0) 已更新推荐安装入口：完整中文 Prompt 可直接复制，中英文各有文本附件；[安装指南](https://github.com/ZhangLiangchen/hypertest-one/blob/8b90efb878c51568c9e35901ad31116b742a5f7f/docs/CLI_AUTHORIZATION_GUIDE.md)与 Prompt 源固定到本轮 Git `8b90efb878c51568c9e35901ad31116b742a5f7f`。原发行说明完整保留在新增指引之后。

| 新增公开附件 | GitHub asset ID | SHA256 |
| --- | --- | --- |
| [中文 Prompt](https://github.com/ZhangLiangchen/hypertest-one/releases/download/cli-v0.1.0/hypertest-cli-install-prompt.zh-CN.txt) | `680476862` | `952dfd7a1d72e0247162f57a64a74cc3797061983c1a270491d3b872866d4220` |
| [English prompt](https://github.com/ZhangLiangchen/hypertest-one/releases/download/cli-v0.1.0/hypertest-cli-install-prompt.en.txt) | `680476860` | `6822057191e663bbffe8b98802f63f8955cfff00ac75795cee44c59d9f536dde` |

两附件经无授权 HTTPS 公开下载，分别为 4076/4620 bytes，与仓库原文逐字节及 GitHub 资产摘要一致。原安装器、CLI zipapp、manifest 和 SHA256SUMS 的 asset ID、摘要、大小与更新时间均未变；原 tag、源码目标、发布时间和正式发行状态保持。没有重新安装 CLI 或替换已有资产。

发布前后元数据、原/新发行正文及核验结果保存在测试服务器 `/opt/hypertest/cli-releases/0.1.0/prompt-update-20261027/`；本轮临时公开下载已清理。网页部署与真实用户安装验收另外记录。

## 定向检查与部署记录

- Web 定向回归 `archive-ui`、`local-mode-guide`、`local-task-creation`、`cli-install-prompt-ui`：37 项通过；涵盖入口、复制成功反馈及剪贴板失败后的全文回退。
- `cli-install-prompt`：4 项通过，覆盖双语固定发行身份、非法 HTTPS origin/项目参数拒绝、未发行/无效元数据拒绝、公开文本与页面单一文本源的一致性。
- `npm run typecheck` 通过；文本生成器 `--check` 与 `git diff --check` 通过。静态设计扫描无 findings；未开展浏览器视觉或真实用户安装验收。
- GitHub 两公开附件已核验，结果见上表；Web 从干净复用 checkout 的 Git `8b90efb878c51568c9e35901ad31116b742a5f7f` 构建，正式构建成功。
- 新 Web image：`sha256:65330f8ac5330ceb47b88bb2dbeb9cc36c80658254de582ad7cdfaaf0c0dd28f`。五容器 healthy、网络守卫 protected；授权页 HTTP 200 且含新复制入口、固定双摘要和 Skill 安装指令，CLI authorization setup 为 configured，现有 `/api/v1/health` HTTP 200 / status ok。
- 本轮仅替换 Web image。API/固定 ops 保持 Git `1512d11f99c5e500e4fc56c685410ffa9e533530`，schema0031，无迁移；API、legacy Worker、PostgreSQL 与 nginx 镜像保持。独立 Cloud Worker active，启动时间仍为 2026-10-23 16:29:49 UTC。既有 nginx ACL、TLS、数据卷和私有配置保留。
- 部署首次误用了 Compose `create` 不支持的 `--no-deps`；复用已完成镜像，改为 `up --no-start --no-deps` 创建，再经守卫检查启动，未重复构建。首次健康脚本误用 `/health` 返回404，按现有就绪脚本改为 `/api/v1/health` 后通过。这两项为本轮运维命令修正，不记作首次全通过。
- 构建日志、前后镜像身份和健康结果保存在服务器 `/opt/hypertest/container-builds/cli-prompt-8b90efb/`。构建后根盘可用约13GiB；复用现有 checkout/依赖/缓存，没有新建测试库或全栈环境。

仅做受影响页面/Prompt 契约检查及部署健康，不重复归档业务全量回归，不创建用户验收项目、任务、凭据或测试产物。
