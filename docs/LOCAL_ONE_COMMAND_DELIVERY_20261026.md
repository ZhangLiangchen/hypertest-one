# Local 一条命令 / Prompt 安装与升级（2026-10-26）

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

本页将分别记录代码回归、候选公开资产和 Web 部署的实际结果；在这些步骤完成前，不将源码实现写成已经公开安装或部署成功。
