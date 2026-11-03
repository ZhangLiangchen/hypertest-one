# ADR-035：宿主原生完成后的任务管理

日期：2026-11-03（Asia/Singapore）。状态：Accepted；实现、部署与用户验收分别记录。

## 问题

ADR-032 的本机薄 Worker 只观察直接 SDK 进程退出，不具备宿主进程树和外部操作的完整观察能力。`COMPLETE_NATIVE_ATTEMPT` 因此保留其他进程 `UNKNOWN`、外部范围 `NOT_OBSERVED` 及 `external_operations_reconciled=false`。原复测、删除准入把该观察限制也当作已知未决操作，导致合法完成的任务无法复测或移出列表；而恢复操作仅用于 `RECOVERY_REQUIRED`，不应为解锁管理而改写已完成的测试结果。

## 决定

- 保持本机薄 Worker → 官方 SDK → Harness 的执行架构，不恢复每任务容器要求，也不新增平台智能体循环。报告接受、直接 SDK 进程退出、其他进程和外部操作的观察范围继续分开记录。
- 正常原生完成必须能由同 Task/Attempt 的已接受 `COMPLETE_NATIVE_ATTEMPT` 回执、最终报告、完成清单及直接 SDK 退出观察确认，且旧 writer 已 fence。只填写原生 marker 或把普通终态声明成原生完成，不取得例外。
- 对符合上述条件的当前 `COMPLETED` Attempt，广义 `UNKNOWN` / `NOT_OBSERVED` 本身不阻止管理。平台仍核对原 pending key、已知 SSH/HTTP/受控动作、容器和委派；任何已知未决项继续阻止新执行。旧隔离 profile 的 `external_operations_reconciled=false` 不适用本例外。
- 有权操作者可沿 ADR-033 为已完成任务创建独立的新 Attempt，重新填写并确认本次范围和授权；包括 `COMPLETED / reported FAIL`，不把“测试有失败”误作“任务未完成”。新尝试使用既有固定源码身份和独立执行快照，不复活旧 SDK 会话、不自动重发操作。
- 无已知未决项的正常原生完成任务可沿既有墓碑协议移出列表。删除不证明宿主其他进程或外部操作已经停止，不清除原件、原回执或旧结果。ADR-034 对已取消且 fenced 的待恢复任务的受限删除和对账路径继续有效。
- 不把原 `false` 改成 `true`，不要求用户为普通管理作不真实的“全部停止”声明，不通过改成 FAILED/CANCELLED 解锁已完成任务。`RECONCILE_ATTEMPT` 仍只处理待恢复状态，已知 UNKNOWN 仍按原 key 对账。
- 任务 live summary 提供当前管理准入与阻断原因；Web 只在该观察与固定任务版本一致时使用它。POST 在事务中重新核验原身份、版本、当前授权和准入，提示可用不等于操作已接受。

此决定细化 ADR-032/033/034 与领域 §51、TMP §46 中正常宿主完成后的管理条件；不改变报告真实性、已知未决操作禁止重放、旧预算保全或独立 Evidence 的要求。已接受的合法原生完成可直接按该条件管理，无需数据回填或迁移历史结果。

## 验证

在专用测试库验证原生完成后的独立复测、删除、固定版本读回和历史结果保全，以及无回执/伪 marker、未 fence、原 pending key、已知未结操作和旧 profile 的拒绝路径。复用现有 Worker handoff 回归，修正与 SDK 交互参数不一致的测试替身；合成回归和部署健康不等于真实模型或项目测试验收。
