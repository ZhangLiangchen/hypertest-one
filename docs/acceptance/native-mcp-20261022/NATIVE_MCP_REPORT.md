# Codex原生MCP加载与直接管理调用（2026-10-22）

**客户端原件和服务端对照PASS：当前Codex原生工具目录已出现并实际调用HyperTest管理工具，原任务完整读回与幂等同步回查成功。** 今日没有启动独立MCP SDK/stdio、直接HTTP客户端或SUT测试；root通过已加载原生工具调用，functions.exec只编排调用与私有结果落盘。

## 实际调用与HTTP语义

| 层次 | 今日实际结果 |
| --- | --- |
| 当前原生目录 | mcp__hypertest_management__hypertest_get_task / mcp__hypertest_management__hypertest_sync_task 两项 |
| 原生工具调用 | get8次、sync1次；所有实际结果isError=false |
| 实际公网HTTP | 9 GET、0 POST，全部200；3次原key回执GET、两组固定v1的3页GET |
| sync含义 | 本Mac原intent已ACKED，同完整payload digest，经官方_write分支在线GET原receipt并返回原ACCEPTED/v1；没有新增POST |
| 存储对象 | 原Task/v1，15cases/2reports/1receipt，全字段/历史/IDs/revisions/timestamps不变 |
| 测试结果 | IN_PROGRESS/FAIL，10PASS/2FAIL/3UNKNOWN；两原报告自动10P2F与独立业务11P1F分别保留 |

Task：[实际XBlock任务](https://155.138.206.106:8080/tasks/01a15de5-9aca-76b4-bd57-c673112f2e92)。Project01a15de2-205e-76e6-bfad-7468a724f886，sourceSession01a143f4-4ec0-7451-ab23-8e59c6deb223。这是旧真实SUT来源引用，不是把本开发会话改名成源聊天。

原body从昨日受控SQL快照receipts[].request_payload保存为original-sync-payload.json；expected_version=0和原keyuc18-real-session-current-20261021-v1不变，canonical digest a3be2c5222fb7ac223297bc25f9907da60d1f06de2194d9a1453dd508395d10f。逐字段等于冻结bundle按官方schema补默认后的数据，并与昨回执/SDK观测一致。只读SQLite mode=ro确认ACKED、同digest和原receipt；未清Journal、未换key/签token或改配置。见PREPARATION_METADATA.json和SCHEMA_AND_CALL_GUIDE.md。

原生sync调用成功与新的HTTP POST是两件事。官方service.py199-207的ACKED分支查询原receipt；今日实际0POST符合预期。2026-10-21曾明确授权并实测一次原ACK key真实POST幂等重放，该日原件与结论保持独立，不冒称今日再次POST上传，也不为拍证据清缓存造POST。

## 原生返回与完整原文核对

root原始材料在 `/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022`，全部保留原envelope及structuredContent。准备/文档执行者没有调用任何MCP/API/SDK。

- [原生catalog与首get](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/root-native-catalog-and-initial-get.json)
- [原生sync真实返回](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/root-native-sync-call.json)、[最后原keyget](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/root-native-final-original-key-get.json)
- root-native-before/after-page-0/1/2.json：两次均固定version1，从0按实际next_offset24000/48000续读，最终complete=true；每次重建61,137 Unicode字符。
- [客户端独立材料核对](CLIENT_NATIVE_ARTIFACT_REVIEW.json)：所有Task输入字段、15case全部输入字段、两report全部字段与Markdown UTF8原字节相同；前后整个current-only JSON相同，也等于昨完整Task。额外ID/revision/timestamp/source均未变化。

原envelope content重建的wire JSON text前后完全相同，SHA256 da2d204b6bccc4bf7fda9fb25292534d7133fb21ab2e6b3ff25e6a67aad25010。root用apply_patch导出的*-full-task.txt自动多一个末尾LF，导出SHA为4e8c5c665a70e920e7971f4773e4dc27ce5eb2a56eb333abe9c5aad7b0d6a9a6。已核对导出恰为wire text+一LF，两个用途分开；原件不重写，不能声称导出文件hash等于wire原text。这里hash仅辅助序列化/存储完整性，不是SUT执行证明。报告Markdown字段原字节仍exact，LF差异在外层导出文本。

首get结果捕获上界02:48:27.937Z是在并行native GET和官方文档open均返回后登记，不能当精确请求或get完成时刻；实际请求时刻以Nginx原日志为准。完整首次分页窗口02:50:13.477→02:50:55.400Z，原生sync紧邻await窗口02:52:26.256→02:52:28.052Z，最后调用结果登记02:53:02.442Z。原root timeline字段和值原样保留，此处补充其计时范围。

## 服务端独立对照

[服务端报告](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/SERVER_NATIVE_MCP_OBSERVATION_REPORT.md)、[RR前后快照比较](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/server-before-after-comparison.json)、[既有公网Nginx/API日志](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/public-nginx-api-log-observations.json)。

before2026-10-22T02:48:35.522843Z→after02:54:42.851713Z：数据库identity/schema相同，完整Task/case_history/report_history/receipts全字段相等，原created_at/last_synced_at/digest/v1相同。76表counts零delta，75表原PK/全行列对照一致，仅worker_heartbeats一条last_seen_at正常运行观察值变化；Audit/Outbox全行相同。没有新Task、case/report revision、receipt、Job、执行或结论记录。

实际日志窗口02:48:10→02:53:15Z，既有VPN peer45.76.149.233：9GET/0POST全200，当前API source5c03，临时远端TLS socket不存在。服务端日志证明网络方法/路径/状态；原生目录与调用身份由本轮root工具原件证明，不能用服务端日志单独冒充native身份。未新增进程/CA采集来补拍证据，配置/证书与昨日成功链路的历史材料分开引用，不将昨日进程PID当今日运行证明。

## 保全与界限

本轮仅管理验证，没有本地SUT/pytest/lint/build/browser测试，没有源码/部署/认证/VPN/CA改变，没有新Task/session/key/v2，未刷新活跃SUT文件或秘密。源材料冻结2026-10-21T15:33:54.750222+08；平台created/last_synced_at仍2026-10-21T09:58:10.890320Z。原失败、3项UNKNOWN与两个报告口径保持，native管理PASS不改写业务结论。

新会话继续用真实自身session创建自己的Task并文本关联旧Task；本次是授权验证现有Task，不创建新任务。UNKNOWN仍只原keyGET，不自动POST/newkey/newtoken。Mac授权仅task:sync，30日到期2026-11-20T09:54:23.105383Z，续期保持原actor/client/project。

此前“Mac只配置未验”“SDK链路已验但native未证明”等报告是当时事实，原文与失败保留；今日实际工具目录和直接调用已补上native可用/调用证据。未单独观察加载触发机制，不推断为无需重启的热更新。

本地原件读者首次误把Promise.allSettled的initial_get包装当直接MCP envelope，触发KeyError:isError；仅材料读取停止，没有任何外部/配置/Journal动作，已按status/value实际结构修正，记录在REVIEW_FORMAT_OBSERVATIONS.json。独立UI/运输/持久化评审已完成APPROVE，无P0/P1/P2。

## 最终交付

[INDEPENDENT_NATIVE_MCP_REVIEW.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/INDEPENDENT_NATIVE_MCP_REVIEW.md) 已最终APPROVE；[SERVER_NATIVE_MCP_OBSERVATION_REPORT.md](/Users/zhangliangchen/.local/share/hypertest/session-sync-dev-20261021/native-mcp-20261022/SERVER_NATIVE_MCP_OBSERVATION_REPORT.md) 最终PASS。客户端/原生调用、服务端网络与数据库对照分别有原件，用户本轮目标全部完成，无待审批或待验证项。不再调用工具、API、SDK或补测试。旧材料与本次格式读取/末LF观察原样保留。
