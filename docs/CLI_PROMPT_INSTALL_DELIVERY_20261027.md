# HyperTest CLI Prompt 安装交付（2026-10-27）

本轮将新 CLI 的推荐安装方式改为“复制 Prompt，交给本机 Agent 执行”。用户从 HyperTest One 页面或 GitHub Release 取得完整指令，由 Agent 完成固定版本下载安装、双摘要校验、适用 Skill 安装及配对发起，用户在网页确认授权。

这是 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 的接入体验改进，不改变归档、授权、任务身份或原 key 恢复合同。当前公开 CLI 仍为 [cli-v0.1.0](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.0)，原包、安装器、manifest、Git tag 和源码身份不重建或重标；原始归档交付见[原记录](LOCAL_ARCHIVE_DELIVERY_20261027.md)。

## 交付状态

| 维度 | 本轮状态 |
| --- | --- |
| 页面与 Prompt | 已实现：页面以复制安装 Prompt 为主入口，保留手动命令；平台/项目上下文随 Prompt 明确传入 |
| 文档 | README 与[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)以 Prompt 安装为推荐路径；旧 Local 安装推荐标为历史 |
| GitHub Release | 待发布本轮中英文 Prompt 附件与发行说明更新；不替换已有发行资产 |
| Web 部署 | 待从推送后的固定 Git SHA 构建与部署；API、schema、CLI 运行时不需要变更 |
| USER_OWNED | 未执行。真实本机安装、技能发现、用户网页授权仍由用户验收 |

## 用户流程与入口

1. 全局「CLI 授权」页复制安装 Prompt；项目入口带入明确 Project ID，平台地址来自当前配置的 HTTPS origin。
2. 用户将 Prompt 交给本机 Agent。Agent 检查实际运行环境与既有安装，下载指定 `cli-v0.1.0` 安装器和 CLI 包，分别验证固定 SHA256 后执行受管安装。
3. Agent 安装 `hypertest-archive` Skill，复用匹配的已有 profile；缺少绑定时发起配对，显示授权地址和短码。
4. 用户在网页核对上传身份、项目、权限与期限后批准。Agent报告实际安装和绑定结果；未批准或未决时如实保留待处理状态。

不在平台页面时，使用 [中文通用 Prompt](cli-install-prompts/hypertest-cli-install-prompt.zh-CN.txt) 或 [English prompt](cli-install-prompts/hypertest-cli-install-prompt.en.txt)。GitHub Release 提供相同文本附件，发行说明包含完整中文 Prompt。通用文本先完成安装，再在需要绑定时询问 HTTPS 平台地址，不猜域名、项目或上传目标。

## 单一文本源与发行身份

页面 Prompt 与中英文发行文本由 [cli-install-prompt.ts](../web/lib/cli-install-prompt.ts) 生成，共用 [cli-release.ts](../web/lib/cli-release.ts) 的固定发行信息。页面增加上下文时只补明确 server/project，不改变包和安装器的摘要；通用发行文本无用户凭据或预设项目。

| 项目 | 保持的固定身份 |
| --- | --- |
| CLI 版本 | `0.1.0` / `cli-v0.1.0` |
| CLI 源 Git | `d02ab1dd893200eb2eee398d795f9b96a41ab768` |
| 安装器 SHA256 | `20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95` |
| CLI 包 SHA256 | `c96c8bb0380658d9eee2efd890eee6de95e9fbec11ec6d3255ba49448334713e` |

完整安装 Prompt 是给用户主动交给 Agent 的操作说明，不是自动执行入口。安装器保持受管命令/版本冲突检查，已有自定义命令或被修改 Skill 文件不覆盖；私有配置、旧版本、journal 与未决 key 保留。Codex 使用现有全局 Skill 安装命令，其他宿主必须明确已核实的技能目录，不推定已通过宿主验收。

安装 Prompt 不申请 Operator key、不替用户批准网页授权，不创建任务、执行测试、上传产物或安装旧 MCP/Hooks/bridge/常驻进程。已有旧配置清理由用户另行发起。SENT、UNKNOWN、失答和 NOT_FOUND 仍只按原 request ID/key 查询；无法确认的配对不能换 key 重发。

## 定向检查与部署记录

- Web 定向回归 `archive-ui`、`local-mode-guide`、`local-task-creation`、`cli-install-prompt-ui`：37 项通过；涵盖入口、复制成功反馈及剪贴板失败后的全文回退。
- `cli-install-prompt`：4 项通过，覆盖双语固定发行身份、非法 HTTPS origin/项目参数拒绝、未发行/无效元数据拒绝、公开文本与页面单一文本源的一致性。
- `npm run typecheck` 通过；文本生成器 `--check` 与 `git diff --check` 通过。静态设计扫描无 findings；未开展浏览器视觉或真实用户安装验收。
- 公开 Prompt 附件核验与 Web 固定 Git/image 身份在发布和部署后补充。

仅做受影响页面/Prompt 契约检查及部署健康，不重复归档业务全量回归，不创建用户验收项目、任务、凭据或测试产物。
