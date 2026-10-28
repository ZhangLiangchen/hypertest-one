# Local 一条命令 / Prompt 安装与升级（2026-10-26）

> **历史资料与兼容范围：** 本文描述旧版本、旧工作流或特定交付时点，文中“当前”仅指原记录时点。新 Local 接入使用 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md) 和 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)；未完成事项见[当前 TODO](TODO.md)，实际部署须现场核实。旧合同与历史记录仍适用于各自范围。

正式发行后续：本页 rc.2 的功能已按用户指令以 `local-v0.1.1` 正式公开，GitHub Latest 与 stable 更新入口已指向新版；见[精确状态、下载与摘要](LOCAL_STABLE_RELEASE_20261026.md)。以下 rc.2 源码、资产与部署仍保留原轮次身份，不重写为正式版构建或新宿主验收。

用户要求已将 [PR #26](https://github.com/ZhangLiangchen/hypertest-one/pull/26) 合入 main，合并提交为 `2262bf3ecba256644b8f6910314679b6340d0b22`。本轮在该基线上改进 Local 分发和接入入口；ADR-026 的任务语义、权限和历史保持。

## 实现范围

统一入口发现所选 GitHub Local 发行渠道，固定所选 tag / source / 目标和校验材料，再交给离线锁定依赖的 bootstrap。首次安装复用已授权的私有 `task:sync` 配置；已有安装以受管收据升级，保留 Hooks、策略、身份和未决账本。私有运行检查核对实际 daemon 来源，不将配置指针更新误报为运行升级。网页提供同一安装 / 升级 Prompt，以及高级命令入口。

`stable` 仅选正式发行，`candidate` 显式纳入候选。旧正式 `local-v0.1.0` 和旧候选 `local-v0.1.1-rc.1` 不改写；当前统一更新协议由新版候选交付。候选包含 ADR-026，但不继承旧包三宿主真实验收；新显式绑定 / 协作写入仍受 Codex CLI `0.144.6` caller 适配限制。

发现目录使用官方 GitHub HTTPS 渠道，动态目录本身不宣称有独立签名；选中后验证固定资产摘要再执行。安装不创建平台项目、任务、凭据，不启用新权限、不调用模型或业务 SUT。功能验收保持 `USER_OWNED / NOT_OBSERVED`。

## 使用入口

项目页“接入本地模式”及任务详情“一条 Prompt 安装或升级 Local”生成同一个 Prompt。Agent 在本机确认已知安装收据或已有授权配置后执行；不要求用户准备新 venv、完整 Git SHA 或手动运行多步升级命令。

以下为 Codex 候选渠道的同一条命令，首次安装需追加既有 `--client-config /绝对私有路径/client.json`；非标准旧安装追加 `--directory /原收据目录`。Claude / DeepSeek 替换 `--harness`，DeepSeek 首装另需原 home/profile；这些路径均不含 token 内容。再次运行即检查并更新，不另换命令。

```sh
python3 -I -c 'import hashlib,sys,urllib.request,urllib.parse; r=urllib.request.urlopen('"'"'https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.2/update-local.py'"'"',timeout=45); u=urllib.parse.urlsplit(r.url); (u.scheme=='"'"'https'"'"' and u.hostname in {'"'"'github.com'"'"','"'"'release-assets.githubusercontent.com'"'"','"'"'objects.githubusercontent.com'"'"'} and u.username is None and u.password is None) or sys.exit('"'"'BLOCKED: updater redirect'"'"'); b=r.read(1048577); r.close(); (len(b)<=1048576 and hashlib.sha256(b).hexdigest()=='"'"'daec79d1e65c1fc455dc12b40faa502ecb74713c7af264bdb7a7771276dc3da7'"'"') or sys.exit('"'"'BLOCKED: updater digest'"'"'); exec(compile(b,'"'"'<verified HyperTest Local updater>'"'"','"'"'exec'"'"'))' --harness codex --channel candidate
```

可加 `--check` 只读检查版本、已发布目标和缺失的 Python 前提。默认根目录为 `~/.local/share/hypertest-local/<host>`；已有非标准收据可显式定位。仅识别 `local-vBASE-source.<完整40位SHA>` 的源码安装允许在候选渠道显式 `--replace-source`，这是替换源快照，不宣称按 SHA 比较版本先后。未知版本停止，已发布高版本不自动降级。首次仍需已有私有 Project 授权，缺失时明确报告，不能用安装命令签发授权。

## 交付状态

[PR #27](https://github.com/ZhangLiangchen/hypertest-one/pull/27) 承载本轮改动。应用与候选发行源码固定为 `df5155ba587c1a4acb32c805691c231b571cc866`；后续 `62f8ba0ce7d3a23bb0d95cba99ada6ef683e24e4` 只修正 Memory 锁测试的旧空配置 fixture，应用和发行源文件字节不变。PR #27 尚未合入 main，不与已合入的 PR #26 混淆。

### 自动回归

- updater / release 相关回归 **83 passed**，运行升级 / 安装 / 客户端相关回归 **38 passed**，Web 相关回归 **32 passed**；范围有交叠，不相加。完整 Ruff、Web typecheck、Skill quick_validate 及差异检查通过；中英文 1440px 合成页面检查通过。
- [修正 fixture 后的 CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40276528629) 三项成功：完整后端 **2257 passed / 21 skipped**，Web（含测试、typecheck、正式构建）、最小 API 依赖轮廓均成功。
- [首次 CI](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40276094932) 为 **2256 passed / 1 failed / 21 skipped**：新增运行身份要求真实配置，旧 Memory 锁测试传入 `None`；修正测试 fixture 后定向通过，再完成上面的 CI。未为迁就 fixture 放宽产品运行身份检查。

### 公开候选

[local-v0.1.1-rc.2](https://github.com/ZhangLiangchen/hypertest-one/releases/tag/local-v0.1.1-rc.2) 已于 **2026-10-26T05:52:05Z** 公开，`draft=false / prerelease=true / latest=false`。[发行构建](https://github.com/ZhangLiangchen/hypertest-one/actions/runs/40276094588) 的 Mac/Linux 和 draft 均通过。六个资产匿名 HTTP 200，updater 公共下载与固定摘要一致；两个目标的目录、manifest、全部 manifest 资产及源码身份已核对。

| 目标 | Bundle SHA-256 | Manifest SHA-256 |
| --- | --- | --- |
| darwin-arm64-py313 | `fd7a17a038004d8a4f922876eb61eaf17e2d6d896ff530c18553877d24330df1` | `3ab6d03750df106f23562af1eb9196a550ca2c378027d5fe1ea2818f17dbaf82` |
| linux-x86_64-py312 | `02b1cb4d3dd487c464cbd6231a8acb3c1517eb4d47321496e658daaa5f2c08e6` | `9377ba18860d6d797c1e0392b25fc78ddd9f76179da9cb9afd00d0e484ec16e6` |

[完整命令](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.2/LOCAL_INSTALL.md)及[机器可读目录](https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.2/local-install-catalog.json)。updater SHA-256 为 `daec79d1e65c1fc455dc12b40faa502ecb74713c7af264bdb7a7771276dc3da7`。两目标所有宿主均为 CANDIDATE / NOT_ACCEPTED；旧 stable 与 rc.1 的 tag、资产、摘要和资格不改写。

公开入口的 Linux / CPython 3.12 合成安装回归已通过：首次 `INSTALLED`，相同命令再次执行 `ALREADY_CURRENT` 且收据字节不变；从真实公开 rc.1 安装及其运行中 daemon 升级得到 `UPGRADED / runtime MATCH`，旧 daemon 退出，新进程报告 rc.2 / 固定源码。原 SQLite 中 UNKNOWN 原 key、FAIL payload、token、配置及无关宿主字段保留，包内 Skill 同命令安装成功。所有配置与授权内容均为回归 fixture，无真实平台授权、Agent、模型或 SUT 执行。

这项回归首次受测试 tmpfs 默认 `noexec` 阻塞；补充错误捕获后确认挂载属性，改为本轮合成容器私有 `exec` tmpfs 后通过。失败日志保留，不改称首次成功。测试容器自动移除，临时下载副本核对后清理；没有对业务库写 fixture 或新建全栈环境。

### Web 部署

复用干净 Git checkout，fetch 后固定上述 df5155b 完整 SHA，只停止 / 构建 / 替换 Web，并重启 nginx 刷新解析。Web 镜像为 `sha256:92b6f2c349766015b32243474a9bf5296ef2fb02ea61a6f2a77588126b2c8560`；API 仍为 66f69f1 来源 / `sha256:6077cd442245aabbe19c86fa76515ed54801152175bd3ffd42729d7edf023ea2`，schema0029；独立 Cloud Worker、legacy Worker、数据库与访问配置保持原身份，无迁移。

服务 healthy，API health、Web 根页和既有项目接入页均 HTTP200；该项目加载的共享 chunk `260-a0dd1f097b545829.js` 包含已发布 updater 的固定 URL / 摘要。初次检查错误要求客户端页面 SSR 文案，继而仅检查 page chunk 也未覆盖共享拆包；改为核对该页加载的共享 chunk 后通过，没有再次重建或重启。此为部署健康与静态入口检查，不是用户功能验收。

交付回执位于 `/var/lib/hypertest-cloud/delivery/20261026-local-update-df5155ba/`，保留构建、发布、安装回归、首轮 CI 失败与部署记录；受保护配置快照不进入仓库。构建后根盘余约4.6GiB，保留已有历史和镜像。真实宿主接入、绑定及同步功能验收继续 `USER_OWNED / NOT_OBSERVED`。
