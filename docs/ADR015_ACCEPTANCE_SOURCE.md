# ADR-015 源码采集与传输验收记录

隔离源码预验日期：2026-10-19，Asia/Singapore。后续正式生产接收与线上周期见[生产部署记录](ADR015_PRODUCTION_DEPLOYMENT.md)，不复用本文探针结果替代生产核验。私有目标身份与内容摘要已脱敏，完整原始记录在本机私有目录保全。对应 [ADR-015](architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md) 与 [TMP §22.3](protocol/TEST_MISSION_PROTOCOL.md#223-本地授权复用与固定源码artifact-传输adr-015-目标)。

已通过真实私有 Git 授权复用与固定对象包的本地独立校验；源码相关 26 项自动化测试通过。本文记录本地源码采集预验、独立接收器测试与资源边界，不将本地 `ACQUIRED` 当成平台 `ACCEPTED`、正式 Execution 或 Evidence。真实 Connector → HTTPS → 平台接受由完整链路验收另行记录，不复用本文探针产物绕过该链路。

## 真实私有仓库与认证复用

经操作者指定，使用 `glab` 1.123.0 与既有登录只读查询 GitLab API，并通过本机已有的 Git credential helper 获取精确 SHA。GitLab 及 Git 凭据没有复制到服务器、写入源码包或写入此记录。

| 项目 | 实际核验结果 |
|---|---|
| 私有 GitLab 仓库 / 固定提交来源 | 已按操作者批准范围真实核验；具体身份仅本机保全 |
| GitLab 统计 | repository size 31,805,567 bytes；commit count 3,608 |
| 本地认证路径 | 当前 host 的 Git helper 委托 `glab auth git-credential`；系统已有 `osxkeychain` 保留 |

GitLab 统计大小不是包大小，也不是解压后对象大小。实际采集仍按批准 origin / 完整 SHA，在独立任务目录调用 Git；不读取用户日常 checkout 的 dirty 或 untracked 内容。原始授权留在本机，包内只有目标 commit 与完整 tree / blob 闭包，不包含父 commit 历史、`.git/config` 或认证目录。

## 尺寸边界与重新采集

初始 16 MiB 单对象上限按规则拒绝该固定 tree，受控错误为 `source object exceeds bounds`。只读对象尺寸核验发现，一个合法 tracked 二进制对象为 23,673,491 bytes；没有通过删除该文件、过滤 tree 或选择其他 SHA 绕过拒绝。

在本次已授权的源码集成范围内，将单对象上限调整到 **24 MiB**，保留 **32 MiB 总原始 payload**、**48 MiB JSON 包**与既有暂存 / 本地缓存配额。以相同固定 SHA 重新通过实际 Git helper 获取和打包，结果：

| 项目 | 重新采集结果 |
|---|---:|
| 本地适配器状态 | `ACQUIRED`，经 `verify_bundle` 独立重算 Git 对象链 |
| tracked 文件 / blob 对象 | 1,431 / 1,431 |
| commit / tree 对象 | 1 / 305 |
| 对象合计 | 1,737 |
| blob 原始 payload 合计 | 32,744,886 bytes |
| 全部对象原始 payload 合计 | 32,840,412 bytes |
| 最大单对象 | 23,673,491 bytes |
| 完整 JSON 包 | 44,271,128 bytes |
| 私有包摘要 | 已独立校验；原值仅本机保全 |
| 获取、构包与本地校验耗时 | 62.148 秒 |

该包包含同一固定 tree 的全部 1,431 个 tracked 文件，未过滤。当前实现的禁止凭据文件 / 私钥标记 / 已知 token 格式规则未触发；submodule、LFS、symlink 与特殊模式同样未触发。未修改第三方仓库、分支或 commit。首次被拒绝的 fetch 裸仓库已清理；成功的受管包保留用于本地原 workspace 的校验恢复。

对象 Hash 和包 Hash 分别说明内容关系与传输完整性；它们本身不证明 origin。平台接收仍必须核验经设备认证的 receipt、Project 显式 `source_acquisition` 角色、批准 origin / policy / 请求 / 节点归属，并在文件 I/O 后重新核对授权。

## 自动化与兼容性核验

在独立可丢弃 PostgreSQL 数据库 `hypertest_adr015`（迁移 head `0018_harness_selection`）运行：

```bash
python -m pytest tests/test_source_transfer_api.py tests/test_source_transfer_bundle.py -q
```

结果：**26 passed in 10.38s**；涉及本次源码文件的 Ruff 检查通过。

覆盖真实 Git 对象、带父 commit 的无父历史包、dirty / untracked 隔离、禁止秘密 / LFS / submodule / symlink、对象 / manifest / origin 篡改、路径与本地受管目录边界、精确恢复拒绝重建，以及真实 PostgreSQL + HTTPS ASGI 接收器的设备 / 项目 / 请求 / policy 归属、幂等冲突、新键重试、撤权与 append-only SQL 约束。另以受控暂停验证长文件 I/O 期间撤销设备后不能凭 ORM 缓存旧身份接受源码。

新增资源边界测试验证：单对象 **24 MiB 恰好通过、增加 1 byte 拒绝**；所有对象 payload（包含 commit / tree）合计 **32 MiB 恰好通过、增加 1 byte 拒绝**；完整 JSON 包 **48 MiB 恰好通过、增加 1 byte 拒绝**。暂存配额、崩溃残留清理和本地授权期限亦有回归覆盖。

公开仓库 `https://github.com/ZhangLiangchen/hypertest-one` 的固定 commit `9a4871ce336bfff9a1b87c7bd7b5b41e89f06110` 亦经过真实获取、闭包校验与物化；336 文件、383 对象、7,049,733 bytes，包 SHA-256 为 `4e36e3d6264583afa819645dd46d60c19f2305f32bd0b2dd9723456b07c3aa50`。将该平台物化副本设为只读后，现有 Runner 的独立 `validate_checkout` 校验通过。

## 当前实现范围

精确资源上限见 TMP §22.3。源码包使用无压缩 JSON / Base64 原始 Git 对象；首版只支持 `100644` / `100755`，拒绝所有 symlink、submodule 与 LFS。物化不运行 hooks、smudge filter 或仓库脚本。恢复时必须验证原 workspace，缺失返回 `WORKSPACE_UNAVAILABLE`，固定内容 / 身份改变返回 `WORKSPACE_INTEGRITY_REJECTED`；暂时性 Git 进程或连接错误保持可观察恢复状态。

本记录没有修改 live 数据库、已完成 Run、Canonical Snapshot、正式 Evidence 或 Verdict，也不声称私有 Java 项目已经在当前 Python Runner 上完成正式测试。

后续生产 source-only 接受补验已通过，可公开的包字节 / 对象 payload / 文件数 / 对象数与0业务 Run、0问题单操作见[生产记录](ADR015_PRODUCTION_DEPLOYMENT.md)。这项独立生产结果不改写上述隔离预验，也不证明私有项目业务已经经过正式测试；私有来源、内容指纹和项目 / Transfer 身份继续只作本机保全。
