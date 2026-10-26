# Local 接入 Skill 与候选包更新（2026-10-26）

本轮根据本地接入实战提交的 [PR #25](https://github.com/ZhangLiangchen/hypertest-one/pull/25) 更新 Local 包。原 PR 的三项 CI 通过，内容经 CLI、MCP、协调器及 ADR-024 核对后，于 `2026-10-26T04:34:08Z` 合入 main，merge commit 为 `76e78dcb9e27c04f1f20747db6391477f21bf651`。

## 实现

`skills/hypertest-local-task-onboarding/` 是唯一维护源码，包含入口、Agent 元数据及 setup、sync-contract、troubleshooting 三份参考文档。Local wheel 将这五份文件原样放入 `hypertest/local_sync/assets/skills/hypertest-local-task-onboarding/`；固定源码摘要、wheel RECORD 及 release manifest 覆盖其字节。通过 Git 源码安装生成的 wheel 也包含相同资源，不维护第二套指南。

新增显式命令：

```sh
"$local_python" -m hypertest.local_sync install-skill \
  --directory "$local_install_directory" \
  --skills-directory "$local_agent_skills_directory"
```

三个变量均取当前已选的绝对路径；`local_python` 是新 Local runtime 的解释器，`local_install_directory` 复用私有安装收据目录，`local_agent_skills_directory` 是 Agent 的技能父目录。Codex 常用 `~/.codex/skills`；完整技能会写入其 `hypertest-local-task-onboarding/` 子目录，随后调用 `$hypertest-local-task-onboarding`。安装器记录所有权、允许未改动的受管文件升级、拒绝同名自定义技能或文件冲突，保留无关文件，并复用可恢复文件事务。命令不默认修改全局技能、宿主信任、凭据、Task 或同步账本。

现有 Local runtime 配置升级仍用 `upgrade-owned`，保留原 host/client/Hook、产物策略及私有 state；再单独运行上述技能安装命令。原生 MCP 绑定所需真实 SessionStart 和逐调用 caller 规则不变，详见[安装与兼容](LOCAL_MODE_RELEASE_AND_INSTALLATION.md#adr-024绑定能力与发行兼容)。新版候选不是自动更新其他机器或当前聊天 runtime 的指令。

## 发行范围

[local-v0.1.1-rc.1](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.1-rc.1) 已于 **2026-10-26 12:40:55（Asia/Singapore）**公开，`draft=false / prerelease=true / latest=false`。固定源码为 `b51e3c51cc3bf4f847667242534100f3698e9f29`，Local source digest 为 `6f95d2b9f8e68c5af4e5c35fecc8c94f03d543831e38435bd8f302eb5157496b`。由现有 GitHub Actions 在 `linux-x86_64-py312` 与 `darwin-arm64-py313` 上构建。候选构建不读取旧正式发行验收作为新资格，所有宿主保留 `NOT_ACCEPTED`；稳定 tag 仍要求精确 tag/source/target 的原生验收。生成的安装命令带 `--allow-candidate`，不生成已验收自动 Hooks 命令。Hooks 需要另行明确配置及真实宿主核验。

完整固定摘要安装命令及独立技能安装步骤见公开资产 [LOCAL_INSTALL.md](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.1/LOCAL_INSTALL.md)，机器可读目标见 [catalog](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.1/local-install-catalog.json)。只替换用户实际选定的绝对路径，不替换版本、完整源码或摘要。已有 runtime 配置应使用 `upgrade-owned`；bootstrap 的默认关闭 Hooks 安装模板不替代保留原配置的升级。

| 目标包 | Bundle SHA-256 | 包内 manifest SHA-256 |
| --- | --- | --- |
| [Mac arm64 / Python 3.13](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.1/hypertest-local-v0.1.1-rc.1-darwin-arm64-py313.zip) | `9e88df899bae9c00dc31de18b6cf8bc9a9580f4a27e34adf2fcde14aa77ab2ba` | `71c40970594d112bc13db91eb47d97fe6b85754f9ca4e53fda65bcb7c0f9899a` |
| [Linux x86_64 / Python 3.12](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.1/hypertest-local-v0.1.1-rc.1-linux-x86_64-py312.zip) | `0466aac1d8440ad8d7b55feb481331cd837fd2dff335b591074af5fa008b381f` | `f9e2f7c4fab0f8898d3c18abf1bcba80ff2ed39fb70da558b53e0d21b230964e` |

两个目标的 Local wheel 相同，SHA-256 为 `49b13b88339b3d9e8b14ce5ef367c84f26978afae1d0b0dc566944d1bc39f622`。bootstrap 字节未变化，SHA-256 仍为 `cd8a2757e3019d6945f697dc1c8db8b650c2744a6e421bae5ba420b7ef25927a`。

候选包含当前 Local 源码中的 ADR-024 绑定工具与独立可选 Memory 客户端；不打包 Cloud SDK、Worker 或 Memory Gateway，不新增任何权限。新 BIND 和手动绑定 Task 的显式新 SYNC 仍只支持已实现的 Codex CLI `0.144.6` caller 路径；Claude Code / DeepSeek 不因此获得新绑定资格。旧 auto Task 恢复、授权 GET 与原 key 对账仍保留。

原 `local-v0.1.0` tag、四份公开资产、摘要及三宿主历史验收不改写。Web 的正式安装入口继续固定旧正式版；本轮候选通过本页链接显式选择。它没有升级为正式推荐版本，也不以旧包补写新工具。

## 回归与发布记录

定向回归 `test_local_release.py`、`test_local_installation.py`、`test_local_skill_installation.py`：**80 passed / 0 failed，0.71s**。覆盖五文件原字节打包、摘要变化、缺件/链接拒绝、幂等安装、受管升级、用户修改保全、失败回滚和恢复；Ruff、skill quick_validate、TOML/YAML 静态解析及 diff 检查通过。构建器还会对每个目标真实离线安装后的 wheel 执行 `install-skill`，核验实际资源加载及 CLI。

首轮误混入无关 legacy `test_local_bootstrap.py`，其6项数据库 fixture 因默认测试连接认证失败而未执行；同轮80项通过。随后缩回上述三个相关无数据库测试文件并全部通过。没有用业务库准备或 reset fixtures，认证失败的连接未写入数据。

[固定源码 CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40270050960) 的 `test`（含 lint、迁移、完整 pytest）、`web` 与 `memory-api-profile` 均成功；[候选发行 Actions](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40270085200) 的 plan、Mac/Linux 两个 build 和 draft 均成功。两目标真实离线安装及 `install-skill` CLI 检查通过。发布前下载两个目标包，各34份 manifest 资产全部核对大小与摘要，wheel RECORD 全部匹配，五份 Skill 与固定 Git 源码逐字节一致；公开后五个资产均匿名 HTTP 200。复核修正了 Mac 自建临时目录的 `/var` symlink 路径解析，仅对构建器自有目录 resolve，不放宽用户目录拒绝规则。

构建和公开下载检查不代表真实宿主绑定/同步 E2E、SUT 执行或用户功能验收；真实宿主验收保持 `USER_OWNED / NOT_OBSERVED`。

本轮不修改 API、数据库 schema 或 Web 源码，不触发服务器应用构建、迁移或重启，不创建平台项目/任务/凭据，不调用模型或业务 SUT。仅复用已有 Python 测试环境执行相关自动化回归。
