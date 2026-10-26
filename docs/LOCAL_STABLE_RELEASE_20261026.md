# Local v0.1.1 正式发行与 Latest（2026-10-26）

用户明确要求将最新候选 `local-v0.1.1-rc.2` 升级为正式版，并更新 GitHub Latest。正式版本使用 `local-v0.1.1`，保留原候选 tag、资产、摘要及历史；不能仅把带 `-rc.2` 的 Release 改为非 prerelease，因为已分发的 updater 的 `stable` 渠道仍会排除该 tag。

## 本轮发行规则

正式发布状态与原生宿主验收分别记录。`distribution_state=RELEASE` 表示此固定版本由用户选择正式公开，GitHub `prerelease=false`；它不表示三宿主实际 MCP / Hook / 绑定 / 协作 E2E 已验收。无新真实证明时，各宿主继续 `NOT_ACCEPTED`，安装后的真实接入仍为 `NOT_OBSERVED`；不更改旧 `local-v0.1.0` 验收原件或测试结果。

此规则取代旧发行工具把所有宿主 `ACCEPTED` 作为每个正式 tag 前置条件的约束，不改变实际能力、caller 归因、Project 权限、幂等及原 key 恢复规则。提供验收文件时仍核对原 tag/source/target 与实际内容，禁止借用旧证明。稳定目标必须在固定源码目标表中明确选择 `RELEASE`，正式构建必须匹配实际 Git tag；不自动增加其他 OS/架构/Python 目标。

普通 MCP 安装与已有配置升级可使用正式版，已有升级继续保留原 Hook、policy、授权和未决账本。正式发行不自动启用新 Hooks；新增启用仍需明确选择产物策略、已验收宿主/版本及标准信任流程。绑定/协作的新 caller 适配仍仅已实现的 Codex CLI `0.144.6` 路径，Claude / DeepSeek 对应未实现路径继续拒绝。

## 正式资产与更新入口

发行目标与最新候选一致：`darwin-arm64-py313`、`linux-x86_64-py312`。现有 Local runtime、Skill 与同步功能以 rc.2 为基础，本轮只调整正式发布与宿主验收的区分，并重新生成版本、manifest、目录和摘要；不把候选文件改名冒充正式包。

正式 tag、源码、六份资产、Latest 指向及相关检查在实际发行后补充。`stable` 和 `candidate` 两个 updater 渠道均可选择最新正式 `local-v0.1.1`；旧已分发 updater 仍使用原固定 URL/摘要，可发现新的正式版，无需覆盖旧资产。

本轮不创建平台任务或授权，不启动模型、SUT 或真实宿主验收，不修改 API、Web、schema 或部署镜像。只复用已有测试环境验证直接受影响的发行/安装契约，并执行必要的两个目标发行构建。
