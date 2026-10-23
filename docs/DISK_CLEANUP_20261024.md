# 测试服务器磁盘清理与环境复用规则

日期：2026-10-24（Asia/Singapore；执行窗口 UTC 2026-10-23 17:13–17:15）。

按用户授权清理明确弃用、可由保留输入重新构建的历史 Docker 镜像及临时构建目录。
未改应用代码、配置或 schema，未构建、迁移、停服或重启；功能验收仍为 `USER_OWNED`。

## 清理前核对与范围

执行前复核 211 个进程的 cwd、exe、root、命令行、maps、mountinfo 和打开文件，
以及 13 个 HyperTest systemd 单元配置和 5 个容器挂载，未发现候选临时目录引用。
镜像核对覆盖全部 559 个 Docker 镜像对象、全部容器、tag / RepoDigest、6 个 Cloud
release，以及仓库文档和启动配置中的镜像引用；保护其引用和完整祖先链共 310 个对象。

删除 249 个未标记、无容器/发行/回滚/启动引用的旧 Docker 构建对象，其中 47 个原为
顶层镜像、202 个为 legacy builder 中间对象。逐个按先子后父顺序执行
`docker image rm --no-prune <完整ID>`，无强制删除、无失败或跳过。镜像 history 均符合
Dockerfile 构建步骤；保留 Git 源码、Dockerfile、基础镜像及发行输入，可进行新的功能构建，
不声称能够逐字节重建旧镜像。未使用任何 image / builder / system / volume prune。

只删除以下 4 个可再生目录，合计清理前分配块约 1.209 GiB：

| 精确路径 | 清理前分配字节 | 保留的重建输入 |
| --- | ---: | --- |
| `/var/tmp/ht-impl-mvjb1zvp/source/web/node_modules` | 520,626,176 | 同目录 package.json、package-lock.json 与源码 |
| `/var/tmp/ht-impl-mvjb1zvp/source/web/.next` | 312,700,928 | 同目录 Web 源码与锁文件 |
| `/var/tmp/ht-impl-mvjb1zvp/npm-cache/_cacache` | 115,343,360 | npm 锁文件和包完整性摘要；缓存可重新下载 |
| `/var/tmp/hypertest-cloud-execution-20261022-7f75957a/delegate-staging/node_modules` | 349,511,680 | delegate-staging 的 package.json、package-lock.json |

两份 npm 锁文件均与声明依赖一致，非根包均有 integrity；候选目录根不是 symlink、
不是挂载点，未观察到常规文件多硬链接。未删除父目录或源码。

## 实际容量与健康

| 指标 | 清理前 | 清理后 |
| --- | ---: | ---: |
| 根盘已用字节 | 76,032,561,152 | 63,549,886,464 |
| 根盘可用字节 | 548,757,504（0.51 GiB） | 13,031,432,192（12.14 GiB） |
| Docker 顶层镜像 / 全部镜像对象 | 96 / 559 | 49 / 310 |
| Docker 镜像去重逻辑大小（engine 报告） | 21.52 GB | 11.07 GB |
| 容器 / 数据卷 | 5 / 6 | 5 / 6 |

根盘已用减少、可用增加均为 **12,482,674,688 字节（11.63 GiB）**。这是上述操作窗口的
文件系统实测差值；Docker 逻辑层估计、目录分配块与文件系统元数据口径不同，不能将
镜像虚拟 size 相加作为回收量。`/tmp` 是独立 tmpfs，本轮未清理，可用约 233 MiB；
根盘余量不代表 tmpfs 余量，后续操作仍需分别检查。

清理后一次最小检查：5 个原容器均 running / healthy，镜像身份保持；独立
`hypertest-cloud-worker.service` active / running。API health、Web 根页、Cloud BFF
capabilities、Memory setup 均 HTTP 200。未创建项目、Task、凭据或触发模型 / SUT。

应用部署身份保持：API / 独立 Cloud Worker Git
`76edb01a985b484bb1d1e1a88fcadd44b7a3532b`，Web Git
`e28d23cd58cd868a9a672be9f9ab6f608416c5c7`，legacy Worker Git
`55de50e215961ee4a1061b32f86670bd23259324`，schema `0028_cloud_http_operations`。
具体镜像身份继续见[最近应用交付](FOLLOWUP_DELIVERY_20261023.md)；独立 Worker 镜像
`sha256:2ec7dc863f544fe64ea41cdb6ef65c010218b96ace85704998f01eb62473adc3`
虽无 Docker 容器引用，仍与当前 rootfs 一并保护。

## 保留内容与后续规则

保留全部运行/下次启动/历史发行引用镜像、6 个数据库卷、数据库历史、所有 `/opt`
发行和源码目录、未提交内容、SDK 会话/runtime、journal/key、报告及源产物、凭据、
备份、宿主配置和 swap。没有截断日志或扩大到系统、npm、pip、APT 等其他缓存清理。

以下混合环境的用途或独有内容未充分确认，已列出询问用户，本轮不删除：
`/var/tmp/ht-impl-mvjb1zvp/venv`、其 `release-inputs/resolver-venv` 与 `wheelhouse`，
以及旧 Cloud 执行目录中的 rootfs、delegate-freeze 和运行归档。旧验证 tmpfs 目录
`/tmp/hypertest-cloud-validation-20261022-f0c1c1c2` 的环境与原件也保留。
不能将名称含 temp、test、release 或 Docker 所称 reclaimable 视为删除授权。

清理精确 ID、保护理由、引用检查和逐项结果保存在本机私有目录
`/var/lib/hypertest-cloud/delivery/20261024-disk-cleanup/`，不含凭据或请求正文。

现行规则已合并到 [AGENTS.md](../AGENTS.md) 和[服务器说明](SERVER_OPERATIONS.md)：
普通开发、构建、相关回归默认复用已有环境与缓存；仅为具体依赖冲突、破坏性测试或
安全边界采用最小隔离，说明原因及生命周期，完成后清理本轮新增且明确可再生的资源。
测试库只可重置合成数据，不向业务库灌入 fixtures；权限、数据保全、必要测试和
`USER_OWNED` 验收边界保持。
