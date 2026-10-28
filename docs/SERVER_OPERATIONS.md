# HyperTest One 测试环境操作

## 当前环境与默认交付流程

用户于 2026-10-28 明确：**本 Mac 就是当前单人测试服务器**，应用运行于本机 Docker 容器；不存在需要通过 `ssh hypertest-one` 连接的测试服务器。旧远端 SSH、systemd 和 nginx 指令属于[历史记录](SERVER_OPERATIONS_HISTORY.md)，不适用于当前环境。

当前 Compose 项目为 `hypertest-mac`，配置位于 `~/.local/share/hypertest-mac/`；独立 PowerContext 为 `hypertest-mac-powercontext`。实际配置、镜像、数据库 schema 和运行状态操作前检查，不以历史记录代替现场核实。本机详细操作见 `~/.local/share/hypertest-mac/README.md`。Web 使用既有 WireGuard 入口；API 与 BFF 的本机入口、TLS 和受信配置按现值维护，不开放额外入口或复制凭据。

用户要求代码部署时，默认在本仓库完成修改及相应检查 → commit/push 并固定完整 Git SHA → 停止受影响容器 → 根据该提交构建需要的镜像 → 执行所需迁移 → 启动 → 检查健康及本次关键路径。服务中断允许，无需重复询问。纯文档只需差异检查和 commit/push，不触发容器部署。

常用只读状态命令：

```sh
docker compose -p hypertest-mac -f "$HOME/.local/share/hypertest-mac/compose.yml" \
  -f "$HOME/.local/share/hypertest-mac/bff.compose.yml" \
  -f "$HOME/.local/share/hypertest-mac/wireguard.compose.json" ps
docker compose -p hypertest-mac-powercontext \
  -f "$HOME/.local/share/hypertest-mac-powercontext/compose.yml" ps
```

部署前核对维护 profile、镜像引用和实际 Compose overlay；只更新受影响服务，保持 WireGuard 地址、BFF、API 授权、TLS、现有凭据及独立 PowerContext。迁移在维护容器内执行；不使用宿主虚拟环境直接操作业务库。

### 复用现有环境与最小隔离（2026-10-24 增补）

复用已有干净 checkout、依赖与构建缓存，不重复创建全栈环境。自动回归只可使用明确专用的 test DB；破坏性迁移测试需要时可创建最小临时合成测试库，完成后清理，不将 fixtures 写入业务数据库。

[ADR-028](architecture/ADR-028_PROTOTYPE_LEGACY_REMOVAL.md) 允许定向移除被替代且不兼容的旧实现及对应旧数据；明确范围和依赖，不以此清空整个业务库、删除数据库卷、现行数据、无关服务、用户源文件或凭据。删除旧账本不证明未知外部操作未发生，不自动重发。执行结果、迁移和镜像身份如实记录；功能验收仍由用户执行。

<a id="ssh-access"></a>

## 历史远端访问

此锚点仅为兼容旧文档链接保留。当前环境在本机，无需 SSH；过去的远端地址、SSH 别名及当时结果见[历史运维记录](SERVER_OPERATIONS_HISTORY.md)。
