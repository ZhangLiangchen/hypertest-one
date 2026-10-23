# Mac 原生测试框架开发接续记录（2026-10-21）

本记录接续 [2026-10-20 交接](MAC_NATIVE_TEST_FRAMEWORK_HANDOFF_20261020.md)。本轮原生框架实跑与随后平台材料接入是两个顺序阶段，没有重跑 SUT 来伪造平台事前下发。

## 已完成与实际结论

- 已按交接顺序阅读 AGENTS / 四基础文档 / ADR-013/015/016 / MCP 交付与验收边界，形成 [ADR-017](../architecture/ADR-017_NATIVE_FRAMEWORK_EVIDENCE_AND_HANDOFF.md)；四基础规范同步至白皮书 v1.5（保留 v1.4 职责纠偏）与架构 / TMP / 领域 v0.7。
- 真实 SUT 既有框架取得 XBlock consumer-parity **17/17 场景断言 PASS**（25 个 step），Blockchain 原生 Maven/JUnit **60/60 PASS**（4 suites），另有 XBlock selfcheck PASS；均 exit 0。完整范围、版本、环境与原件见[原生测试报告](../acceptance/native-framework-20261021/REPORT.md)。没有新建样例 SUT、框架、平台 Runner 或链交易。
- `native-framework-intake/v1alpha1` 为新的独立原生轮次 / 计划 / 用例 / 执行材料 / 验证 / 保守结论 / 顺序贡献交接切片。使用既有 PostgreSQL、Artifact、Audit / Outbox，原受管 Harness / Runner / Gate / 数据 / 授权和历史不改写。
- 首次真实本机 HTTP 验收接受 2 个 Project、2 原生轮次、77 用例、2 执行记录及 10 份原件；每份通过 GET 读回并核验 byte count / SHA-256。两个 Verifier 为 CHECKED / CONSISTENT，但执行来源仍 **UNVERIFIED**；原生 Gate 均先为 **UNKNOWN**。这些是平台材料治理结果，**没有正式 native PASS / RELEASE_READY**。
- 独立 HTTP 客户端进程 PID 22808 / 22870 完成顺序交接，两个轮次 generation 1→2；旧 capability 即使使用新 contributor/generation 也返回403，已接受状态与原件保留。contributor session label 是操作者登记元数据，不证明跨真实 Provider 聊天恢复。
- 明确标注的本机治理 control-only UNKNOWN（没有发送任何外部请求）使 XBlock 后续 handoff 返回409，Gate 追加 BLOCKED；它不是 SUT 失败或产品缺陷，也不改变17个本机断言结果。

最终源码服务重启后的27次HTTP核验、产品CLI实际evaluate/get/operation、持久配置下21次纯GET已完成。11份材料（10原+1control）及2份handoff快照读回一致；旧capability拒绝、NOT_FOUND保UNKNOWN与原状态保全均已核验。首次纯GET脚本预期403而实际401的TEST_EXPECTATION_ERROR原样保留，修正预期后只重查GET。最终精确API / PG已停止且数据保留，详细证据见[平台验收报告](../acceptance/native-platform-20261021/REPORT.md)。

实现回归单独记录：最终native接入 / CLI 22项通过；相关82项组合回归包含当时9项native与73项已有测试，不能与22简单相加为104，也不是82项纯legacy。Ruff / diff检查通过，独审剩余P1/P2为0；[验证记录](../acceptance/native-platform-20261021/IMPLEMENTATION_VERIFICATION.json)附原命令与工具chunk/session，明确原始本机pytest日志未捕获、此文件仅为transcript-derived材料。这些代码控制验证不是正式SUT Evidence。

## 身份与保留位置

| 对象 | 固定身份 / 位置 |
| --- | --- |
| HyperTest 本轮起点 / 工作分支 | `5a68dd1bd6375fad0b271b2b86af48bdf857fe31` / `codex/native-framework-evidence`；本轮未创建新Git提交、未push或发行，是工作树开发结果，以baseline + branch + 11文件运行时源码manifest识别 |
| Blockchain SUT | `https://gitlab.charprotocol.com/blockchain/blockchain.git`，`dev@0914459b323b82d8f794145247c4627625a6c87b`，clean；本机物化74文件逐blob核验，不上传源码 |
| XBlock 来源引用 | GitLab project127 `xblock/xblock-service-asset` 可读；JAR 183426836 bytes / SHA256 `8d53f8db68856feefacf3585f3c7f55d8ce500d043b2027cd4a5b3cd8478129e`，源码关联 UNVERIFIED；历史 `cdb9686e` 不能当构建证明 |
| 原生框架 | `hypervise_pure` 主目录 dirty `master@83a1568905a9ac73852bd4749eeeea540b91b0b5`；所用 worktree `zealous-williams-51bed9@d4bd46e5daee8f5b4906deb5c8a2aadc7f34e584`，所选4项 tracked测试资产无修改；原工作区 / 12 worktree均保留 |
| XBlock 平台轮次 | Project `01a15d34-358c-71f3-8d91-05a8d5ca4251`；NativeRun `01a15d34-35d5-7199-8b78-4d6327053b4b`；Execution `01a15d34-35f5-7d10-826b-6e5a8ae34f56` |
| Blockchain 平台轮次 | Project `01a15d34-3630-7656-938a-0ec893e41352`；NativeRun `01a15d34-3637-7b59-9057-5bebc5ccc4fc`；Execution `01a15d34-364b-7468-b35b-afcfe478f1d9` |
| 原始材料 / 接入验收 | `docs/acceptance/native-framework-20261021/` / `docs/acceptance/native-platform-20261021/`；派生 JSON、摘要和 hash 不替代各原始 JSONL/XML / 日志 |
| 本机 API / 数据库 | 回环 API `http://127.0.0.1:8097/api/v1`（最终PID29428已停止）；精确隔离容器 `hypertest-native-qa16-20261021`，PG16、`127.0.0.1:55439`、数据库 `hypertest_native_qa`、schema `0021_native_intake`；容器已exited，未删除 |
| 本机私有运行数据 | `/Users/zhangliangchen/.local/share/hypertest/native-dev-20261021/` 下持久私有配置、Operator key、Artifact Store与 `acceptance-client/` 客户端状态 / writer key；目录0700 / 文件0600。原tmp和仓库ignored副本保留。不是正式发行或生产凭据 |

原生实际执行发生于 06:23–06:25 UTC；平台真实接受时间为 06:44:25 UTC，observed start/end 与 accepted/submitted 时间分别保存。新 native 接入尚无发行；已发布的 `mcp-v0.1.0` / wheel 身份仍按原 MCP 交付记录解释，不包含本轮开发路径。

## 下一轮的明确入口

先阅读 ADR-017、架构 §43、TMP §44 和领域 §49，再读取上述 NativeRun 的最新状态 / 原 key 回执、handoff 冻结状态及剩余工作，不重新执行已完成的77个测试来“补证”。本轮 profile 仅 Operator 受控 HTTP / 本机 CLI，尚未接入 Web 或现有 MCP 工具。

源码开发安装仅面向已审阅的本机 checkout（Python 3.12+），保留已有虚拟环境；若新建环境，请使用新的明确路径：

```sh
python -m pip install -e '.[native]'
python -m hypertest.native_client --help
```

不要以移动 main 或这个开发安装替换原 MCP 固定发行。启动 API 所需配置变量名：`HYPERTEST_DATABASE_URL`、`HYPERTEST_ARTIFACT_ROOT`、`HYPERTEST_NATIVE_INTAKE_ENABLED`、`HYPERTEST_NATIVE_PROJECT_KEYS`、`HYPERTEST_CONNECTOR_OPERATOR_IDENTITY`、`HYPERTEST_CONNECTOR_OPERATOR_KEY`。只批准 `NATIVE_XBLOCK_20261021` / `NATIVE_BLOCKCHAIN_20261021` 两个隔离 Project；默认 native intake 关闭。Operator 值从本机 owned `0600` 私有文件读入进程环境，不写命令参数 / MCP / 报告。

若本轮精确容器已停止，先核对容器名 / 挂载仍为本轮资源，再 `docker start hypertest-native-qa16-20261021`；不要重新建空数据库或删卷。API 在相同已审阅源码、工作目录及 `/Users/zhangliangchen/.local/share/hypertest/native-dev-20261021/server-config.json` 固定配置下重启，保留原 Artifact Root；禁止将它指向生产。

已存在本机私有配置时，以下启动方式不把 key 放入 argv：

```sh
cd /Users/zhangliangchen/PycharmProjects/hypertest-one
.venv/bin/python - <<'PY'
import json, os, sys
from pathlib import Path
private = Path.home() / '.local/share/hypertest/native-dev-20261021'
os.environ.update(json.loads((private / 'server-config.json').read_text()))
os.environ['HYPERTEST_CONNECTOR_OPERATOR_KEY'] = (private / 'operator.key').read_text().strip()
os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'hypertest.main:app', '--host', '127.0.0.1', '--port', '8097'])
PY
```

配置 / Artifact / key已持久复制并逐文件核验，原tmp副本只保留迁移前历史。若持久目录在接续时仍缺失，先报告具体缺项，不猜秘密、不取得生产key、不重新POST旧创建意图。跨新Mac的本机授权不会随Git迁移；恢复按实际数据与操作者安排核对。

普通读取示例（key只通过文件路径引用）：

```sh
.venv/bin/python -m hypertest.native_client \
  --api-url http://127.0.0.1:8097/api/v1 \
  --operator-key-file /Users/zhangliangchen/.local/share/hypertest/native-dev-20261021/operator.key \
  --journal /absolute/private/native-read/journal.db \
  get --run-id 01a15d34-35d5-7199-8b78-4d6327053b4b
```

`operation --key <原key>` / `material --key <material-id>` 使用同一窄客户端。写前先生成审阅的 JSON payload、指定私有 `--writer-key-file` 与 journal；`submit` 只提交已有报告，不执行command。create / handoff 的新 capability 只交付一次，GET / 重复回执不重签。响应失答 UNKNOWN 只能按原 key 查询；NOT_FOUND 不能授权自动 POST、换 key 或另建轮次。不要重复运行验收脚本 phase one / two；读取现存结果。

## 未完成、UNKNOWN 与后续授权

1. 独立 CI / SCM 可信来源 verifier、正式 native PASS、完整 Requirement/Risk 语义覆盖和 Web/MCP 未实现。下一轮按 ADR-017 §8，以真实批准 pipeline/job/attempt、source/test/environment 和原件独立查证契约实现 / 验收，不再加通用 Runner。
2. XBlock JAR→源码 / 当前部署身份未证实；77项是组件隔离断言，不是共享 staging/dev166 E2E、活链、真实交易或发布门禁。没有真实失败执行；失败接收路径的控制回归不代替真实产品失败材料验收。
3. XBlock 有刻意保留的 control-only `control-only-unknown`。它阻断新执行 / handoff；仅经 Operator 管理 reconcile，绑定原操作、具体查证材料、attestation 与 reason 后处理。NOT_FOUND / 摘要不解除；它没有任何外部请求要重发，不将该治理测试当成产品缺陷。
4. 顺序贡献者 handoff 已验证，真实原生会话身份 / 跨 Provider 接管未证明。不得伪造旧 session、复制认证 / 对话或向 Agent 分发全局 Operator key；平台只能隔离其 API 写入。
5. GitLab 本机只读身份 / TLS 已验；Provider 登录、生产 SSH / 平台授权迁移和问题单写权限未检查，不因旧 Mac 或 CLI 存在推定可用。生产部署 / schema迁移 / Issue / 共享链写 / 私有源码外发均未执行，也不包含在本轮开发默认授权。
6. 旧 ADR-013/015/016、27项隔离 / 33项生产周期、共享环境其他会话中的成功与失败历史继续独立存在；本轮77项不能覆盖它们或关闭其缺陷。

已精确停止本轮 API PID29428 和 `hypertest-native-qa16-20261021`，保留容器 / 数据 / Artifact / 原始材料 / 私有journal；停止结果见平台验收报告。不执行 `docker rm -v`、`compose down -v`、worktree 删除或全局进程清理。
