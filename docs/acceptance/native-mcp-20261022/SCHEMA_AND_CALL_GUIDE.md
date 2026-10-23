# 今日原生工具参数与实际HTTP语义

仅由root调用原生工具；准备者不调用MCP/API/SDK，不清Journal、不换key、不签token、不改配置。

## 文件

- original-sync-payload.json：原完整平铺sync参数；原expected_version=0，不改为当前v1；原key不变。来源是2026-10-21服务端RR快照原request_payload，逐字段等于冻结bundle按已发布schema补默认值后的数据。
- original-accepted-receipt.json：原ACCEPTED/v1回执。
- get-parameters.json：原key回执与分页参数。PREPARATION_METADATA.json记录只读核对结果。

原inputdigest a3be2c5222fb7ac223297bc25f9907da60d1f06de2194d9a1453dd508395d10f。报告和body留在私有文件，不向公开GitHub推送或把完整body打印为stdout；token不在任何参数文件内。

## 原生get

调用mcp__hypertest_management__hypertest_get_task时，回执分支仅project_id+idempotency_key；不得同时带provider/session/version/offset/limit。分页分支须project_id/provider/session_id，可带version/offset/limit，没有task_id入参。

固定版本查询首片version=1/offset=0/limit=24000；后续严格使用响应next_offset与同一version。offset按Unicode字符计数，非UTF8字节。昨日3页offset0/24000/48000,total_chars61137，只作对照，不替代今日实际响应。页envelope应含task_id/version/format=application/json/offset/total_chars/next_offset/content/complete/source=AGENT_REPORTED。全部content拼接完整后解析为task/cases/reports，核对原TaskID/sourceSession/owner和每个输入字段、全部case/report及Markdown原字节；不能只读第一页。

## 原生sync与HTTP区分

只读SQLite核对本Mac该intent已ACKED，digest与原payload/receipt相同。官方0.2 service.call(sync)调用Journal.intent校验完整payload digest；_write中state!=PENDING便HTTP GET原receipt，验证后返回原回执。今日预期native sync工具确实被调用，但HTTP POST数为0；不得清Journal制造POST，也不以GET回执声称“今日重新POST上传”。昨日2026-10-21才是授权的原key真实POST幂等验收，两日证据独立。

代码依据（干净release worktree main@5c03e4d90bed69b6420238849cbb3a8bae2f4c42）：
- src/hypertest/interactive_client/service.py:124-138同步分支与compact journal；195-228状态分支；ACKED走201-207 GET；仅PENDING走213-228 POST。
- src/hypertest/interactive_client/journal.py:29-54，同key不同完整input digest冲突；不覆写已有ACKED身份。
- src/hypertest/api/task_schemas.py:42-63，sync唯一业务keys、expected_version>=0、extra forbid、总2MiB；Case字段见17-30，Report字段见33-39。
- src/hypertest/api/task_schemas.py:66-90，get两个互斥查询形状、limit<=24000、offset>0必须version。
- src/hypertest/application/session_tasks.py:74-78，服务端相同actor/project/key且digest相同也只返回原receipt，不递增版本；本次如客户端ACKED分支仅GET则不会进入这个POST handler。

失败/UNKNOWN只原keyGET对账，不自动POST、新key、新token或重跑SUT。任何保存结果均为AGENT_REPORTED，不把原FAIL改UNKNOWN、不把管理验收PASS当SUT通过。
