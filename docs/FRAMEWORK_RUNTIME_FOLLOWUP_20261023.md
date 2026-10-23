# 框架离线冻结基线（2026-10-23）

`src/hypertest/cloud/framework_runtime.py` 提供 `FRAMEWORK_LOCKED_V1` 的纯输入验证与 before-prompt 离线核对。它不安装依赖、不连接网络、不运行仓库脚本或测试入口，也不声称约束 SDK 之后的全部 shell 行为。API 准入、Worker 调用点和受控 HTTPS 的整合由本轮主交付统一记录。

```json
{
  "profile": "FRAMEWORK_LOCKED_V1",
  "lockfiles": [{"path": "requirements.lock", "sha256": "<64 lowercase hex>"}],
  "tools": [{"name": "python", "version": "3.13.5", "sha256": "<64 lowercase hex>"}],
  "entrypoints": [{"key": "python -m pytest", "argv": ["python", "-m", "pytest", "-q"]}]
}
```

`validate_runtime_spec` 只解析严格字段，不做 IO。`inspect_framework_runtime(framework, spec, framework_entrypoints)` 要求 entrypoint key 集合与原任务输入完全一致，核对至多 16 个锁文件、总计不超过 1 MiB。路径仅限 canonical 相对路径；拒绝 `.git`、认证/秘密路径、父级穿越、symlink、hardlink、非普通文件及核对中变化的文件。摘要不匹配立即阻塞，不先运行工具。

工具限 Python 与 Node。Python 从当前 `sys.executable` 解析，Node 只从固定宿主路径解析，不查询仓库提供的 PATH、shim 或 `node_modules`。实际可执行文件及父目录必须 root-owned 且不可由 group/other 写入，不能落在框架目录中。先核 SHA-256，再以绝对路径运行唯一固定参数 `--version`；使用干净环境、`cwd=/`、有界输出与 5 秒超时。版本字段是去除 `Python ` 或 `v` 前缀的确切版本，不是兼容范围。

返回元数据包含实际锁文件摘要/字节数、工具版本/摘要与入口声明，并明确 `entrypoint_execution`、`dependency_installation`、`network_access` 均为 `NOT_RUN`。没有 spec 时返回 `None`，保留旧任务行为；新准入哪些任务必须携 spec 由 API/Worker 合同拥有，不由此模块隐式替旧任务补造基线。

本模块定向自动化回归 **35 项通过**，覆盖纯 schema、secret/traversal/symlink/hardlink/体积拒绝、锁摘要和工具摘要前置、精确入口集合、真实固定 Python 版本读取、PATH 注入无效、固定命令/环境以及入口只声明不执行。Ruff 通过。以上是变更范围回归，不是业务 SUT 执行、框架依赖已安装或真实 HTTPS 用户验收证明。
