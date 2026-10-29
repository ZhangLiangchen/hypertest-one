# Cloud Worker 首轮进展（2026-10-29）

## 源码与验证

Cloud Worker 在领取解析或 Attempt 前进行无模型、无项目数据的 bubblewrap namespace 基础探针；已有 lease 过期处理先执行。探针失败不领取新工作，Worker 输出有界诊断并退出；超时或取消时停止探针进程组。该探针不替代每次 Attempt 的工作区、SDK、凭据或实际执行检查。

Cloud 报告固定版本读回增加完整快照 SHA-256、Run 身份/执行/用例/报告关联和完成终态/结果/清单核对。读回失败保持待对账，恢复仅查询原接受版本，不重发原操作。

定向回归：Worker namespace、资源、SSH Worker、诊断和启动相关检查 108 passed；Cloud reporter、handoff 与数据库操作 76 passed / 1 skipped（本机虚拟环境未安装固定 DeepSeek SDK）；其他 reporter 相关检查使用短临时路径 86 passed。相关 Ruff 通过。首次 reporter 扩展回归使用 macOS 默认长临时路径出现 6 个 Unix socket 路径过长失败，改用短路径后复验通过；不把前次失败改记为通过。

框架回归在临时合成 Git 仓库实际运行 Python unittest 的 PASS / FAIL，再通过 Worker collector、reporter、原件与 Run/最终报告固定版本读回。PostgreSQL 使用新建的专用临时测试容器，完成后移除，不写业务数据库。本回归不启动 SDK、模型或隔离 namespace，不证明真实 SUT 运行或执行来源的独立认证。

## 本机环境与未完成事项

现场 Docker 为 OrbStack Linux ARM64 / cgroup v2，业务 schema 为 `0036_cli_global_authorization`；无独立 Cloud Worker 容器，API 的 Cloud / Worker 开关关闭。默认非特权容器在创建 user namespace 时返回 EPERM。以 Docker 29.8.2 官方 seccomp 默认 profile 作基线的临时诊断中，限定 user namespace 调用的规则可使简单 unshare 成功，但进一步的简化 bubblewrap 测试在挂载 `/proc` 时仍 EPERM；未确认唯一原因或形成验证通过的部署 profile。诊断期间另有一次误用 `seccomp=unconfined` 的无业务数据、无网络临时探针；它不作为方案或通过证据，临时资源均已清理。

本轮没有部署或启动 Cloud Worker，没有开启 Cloud 执行，也没有启动模型或真实 SUT 测试。需要完成实际 Docker 隔离准入、Cloud 专用模型身份与包装密钥、预算配置后再按固定 Git 提交构建和部署。测试服务器服务健康或源码回归不等于 Cloud 可用。

用户选定 XBlock MR 1146 和 `hypervise_pure` 框架，以 staging 的 TRON_TEST USDT→TRX DEX 为目标。MR 已合并不证明 staging 已部署对应版本。当前受控 HTTPS 仅支持公开、无认证、无副作用的固定 GET/HEAD；认证及兑换写操作尚不支持，XBlock 需要 SSH / 服务器操作的路径仍遵守 Local-only 路由。具体框架依赖、授权和目标观察需另行核实；没有发起兑换或推定测试结果。
