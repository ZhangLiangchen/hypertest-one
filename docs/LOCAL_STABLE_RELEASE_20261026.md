# Local v0.1.1 正式发行与 Latest（2026-10-26）

> **历史资料与兼容范围：** 本文描述旧版本、旧工作流或特定交付时点，文中“当前”仅指原记录时点。新 Local 接入使用 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 和 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)；未完成事项见[当前 TODO](TODO.md)，实际部署须现场核实。旧合同与历史记录仍适用于各自范围。

用户明确要求将最新候选 `local-v0.1.1-rc.2` 升级为正式版，并更新 GitHub Latest。正式版本使用 `local-v0.1.1`，保留原候选 tag、资产、摘要及历史；不能仅把带 `-rc.2` 的 Release 改为非 prerelease，因为已分发的 updater 的 `stable` 渠道仍会排除该 tag。

## 本轮发行规则

正式发布状态与原生宿主验收分别记录。`distribution_state=RELEASE` 表示此固定版本由用户选择正式公开，GitHub `prerelease=false`；它不表示三宿主实际 MCP / Hook / 绑定 / 协作 E2E 已验收。无新真实证明时，各宿主继续 `NOT_ACCEPTED`，安装后的真实接入仍为 `NOT_OBSERVED`；不更改旧 `local-v0.1.0` 验收原件或测试结果。

此规则取代旧发行工具把所有宿主 `ACCEPTED` 作为每个正式 tag 前置条件的约束，不改变实际能力、caller 归因、Project 权限、幂等及原 key 恢复规则。提供验收文件时仍核对原 tag/source/target 与实际内容，禁止借用旧证明。稳定目标必须在固定源码目标表中明确选择 `RELEASE`，正式构建必须匹配实际 Git tag；不自动增加其他 OS/架构/Python 目标。

普通 MCP 安装与已有配置升级可使用正式版，已有升级继续保留原 Hook、policy、授权和未决账本。正式发行不自动启用新 Hooks；新增启用仍需明确选择产物策略、已验收宿主/版本及标准信任流程。绑定/协作的新 caller 适配仍仅已实现的 Codex CLI `0.144.6` 路径，Claude / DeepSeek 对应未实现路径继续拒绝。

## 正式资产与更新入口

发行目标与最新候选一致：`darwin-arm64-py313`、`linux-x86_64-py312`。现有 Local runtime、Skill 与同步功能以 rc.2 为基础，本轮只调整正式发布与宿主验收的区分，并重新生成版本、manifest、目录和摘要；不把候选文件改名冒充正式包。

[local-v0.1.1](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.1) 已于 **2026-10-26 16:07:29（Asia/Singapore）**正式公开，`draft=false / prerelease=false`，仓库 [Latest](https://github.com/ZhangLiangchen/hypertest-one/releases/latest) 已指向它。固定源码为 `ca6ece7c24fd7c98db316581f8ee71274b826a64`，Local source digest 为 `739f9ae6576fe375fbf2283669804dc38e0566d11c53c40ec796e931f33f1359`。

`stable` 和 `candidate` 两个 updater 渠道均可选择正式 `local-v0.1.1`；旧已分发 updater 的字节及摘要不变，可发现新的正式版，无需覆盖旧资产。完整命令见 [LOCAL_INSTALL.md](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1/LOCAL_INSTALL.md)，目标见 [catalog](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1/local-install-catalog.json)，另分发 `install-local-release.py`、`update-local.py` 及两个目标 ZIP，共六份资产。

| 目标包 | Bundle SHA-256 | 包内 manifest SHA-256 |
| --- | --- | --- |
| [Mac arm64 / Python 3.13](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1/hypertest-local-v0.1.1-darwin-arm64-py313.zip) | `60311ed1fcb592ffb19f8ef3587b1ac7ff6c357e6045e4a8bbfa0cb5f7d72bb0` | `58d1a3c965fb4dac9db3414b839db41c408b4f9e85f1779dc08b850d7faec1ed` |
| [Linux x86_64 / Python 3.12](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1/hypertest-local-v0.1.1-linux-x86_64-py312.zip) | `512796134e80d87f2a4ff44b4c75ee2d00d68991d3bb7f1a1911cc954e500b03` | `1e5eb43fc8a1e95927060000eb3a2e3190fb440b6d62ebb392eaa8e35d225293` |

两个目标的 Local wheel 相同，SHA-256 为 `d1918cc3e01ca2db26c3e64fca35589d37e3a0915a17b371084ce389284ed66a`。bootstrap 为 `9cf24804428f1da9d0c09cf8e0380122b1eb1e874e74712b34a8cfc0ca7bfba3`；updater 仍为 `daec79d1e65c1fc455dc12b40faa502ecb74713c7af264bdb7a7771276dc3da7`。

## 相关检查

- 发行/安装契约 `test_local_release.py` **70 passed，1.22s**；更新通道/只读检查/受管升级相关 **4 passed / 14 deselected，0.13s**。覆盖明确正式目标、保留未验收字段、错版证明拒绝、新 Hooks 资格/版本拒绝、已有 Hook/policy/UNKNOWN journal 保全；相关 Ruff、YAML 与 diff 检查通过。
- [正式发行 Actions](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40289902303) 的 plan、Mac/Linux build、draft 均成功，含真实离线安装及内置 Skill CLI 检查。依当前快速原型指导，没有额外触发手动全量平台 CI。
- 两目标下载包的 tag、`0.1.1` wheel 身份、固定源码、RELEASE 状态和各34份资产大小/摘要匹配，五份 Skill 原字节匹配 Git。客户端/Skill 源文件相对 rc.2 无差异；本轮变化为发行工具、版本身份和发行文档。六份公开资产均匿名 HTTP200。
- GitHub `/releases/latest` API 返回 `local-v0.1.1 / draft=false / prerelease=false`。原字节 updater 的 `--channel stable --check` 已发现 `local-v0.1.1` 及统一更新协议；本服务器默认 Python3.13 不匹配 Linux目标3.12，按设计报告 `PYTHON_REQUIRED`，没有创建安装目录或声称完成安装。该检查只验证发现/拒绝边界，不运行真实宿主接入。

本轮不创建平台任务或授权，不启动模型、SUT 或真实宿主验收，不修改 API、Web、schema 或部署镜像。只复用已有测试环境验证直接受影响的发行/安装契约，并执行必要的两个目标发行构建。
