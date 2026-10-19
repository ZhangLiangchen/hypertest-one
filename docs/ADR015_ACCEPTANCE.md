# ADR-015 实现与真实验收记录

日期：2026-10-19（Asia/Singapore）。依据 [ADR-015](architecture/ADR-015_DUAL_MODE_HARNESS_AND_LOCAL_CONNECTOR.md)。

本公开记录保留公共 fixture 的身份、结果和摘要。私有仓库、GitLab 目标、负责人及外部 Issue 的原始身份已脱敏；完整原始记录另存本机受保护的私有保全目录，不随公开仓库发布。

## 验收拓扑与范围

本分支实现保留 `SERVER_HOST`，新增 `LOCAL_CONNECTOR`。本次独立环境使用真实 PostgreSQL、启用证书与主机名验证的本地 HTTPS API / Worker、独立进程的本机 Connector 与原生 Codex，以及通过既有严格 SSH 公钥入口连接的**远端服务器 Docker Runner**。控制平面运行于本机隔离环境；这不是生产平台切换，也不是用本机 Agent 自报结果代替 Runner。

生产服务、数据、Provider / OAuth 配置、Artifact、SSH 登录与 VPN 白名单没有修改。生产 `ops/check-remote.sh` 巡检健康，当前部署仍为 `9a4871ce336bfff9a1b87c7bd7b5b41e89f06110`；本分支尚未提交、推送或部署。Web 已增加双模式、设备操作和固定源码接收入口；真实周期通过相同 API 提交，界面单独做可见表单检查。

## 已实现内容

- 设备配对 / 轮换 / 撤销、独立 Operator 管理入口、设备随机 bearer 的平台 hash，以及 Project 的 `harness` / `source_acquisition` / `issue_executor` 分权。
- 主动 WSS、PostgreSQL durable mailbox、短期 dispatch grant、不可变 Run 选择与 Binding 放置；连接恢复不重发已送请求、不自动换节点或服务器 Harness。
- 原生 Codex 登录、本机 Git helper / SSH agent 与受控 `glab` 集成复用。平台没有收到 Provider、GitLab 或 Git 凭据。
- 固定完整 SHA 的独立 Git 采集、HTTPS 有界整包上传、平台独立 Git 对象链验证、只读源存储、原 workspace 初装和恢复校验。首版不支持分块续传、symlink、LFS 或 submodule。
- GitLab Operation 与固定 executor、创建前本地持久账本、结果未知只读对账、可信外部读取确认目标 / correlation / 负责人。
- 原 Runner 先收尾、旧 owner fencing、显式 Binding epoch 恢复、原 Job retry 与原会话 / workspace 复用。
- `0015`—`0018` additive migrations；现有快照、会话、事实和历史不回填、不改写。全新空库升级至 head 成功，已运行测试库与全新迁移 head 比较一致：594 列、325 约束、175 索引、35 trigger、32 个 SQL guard 函数。

操作方式见 [本地 Connector](LOCAL_CONNECTOR.md) 和 [受控 GitLab 提单](LOCAL_CONNECTOR_GITLAB.md)。

## 私有 Git：真实本机授权与 HTTPS 接受

使用操作者明确批准的私有 GitLab 仓库，通过现有 `glab auth git-credential` helper 获取固定完整提交；没有复制授权到远端服务器。私有 origin、commit / tree / 包摘要与外部项目身份仅保留在本机私有证据中。

| 项目 | 实际结果 |
|---|---|
| 私有 Git 授权复用与 HTTPS SourceBundleTransfer | **PASSED / ACCEPTED** |
| 文件 / 对象 | 1,431 / 1,737，包含固定树内的全部 tracked 文件 |
| 对象原始 payload / 传输包 | 32,840,412 / 44,271,128 bytes |

平台重新验证设备 / Project / 请求 / origin / policy、包摘要和 Git 对象链后接受，区别于本地 `ACQUIRED`。来源信任授予受控采集器及其主机，不宣称包 hash 可证明 origin。此项只验收私有仓库的授权与源码交付，不宣称其业务测试已经完成。尺寸预验、首版支持范围和 26 项源码测试详见 [源码记录](ADR015_ACCEPTANCE_SOURCE.md)。

## 真实周期与故障恢复

两轮均使用公开 fixture 的固定提交 `9a4871ce336bfff9a1b87c7bd7b5b41e89f06110`、实际 `examples/api_sut/PRD.md`、`python-api-v2` 环境与真实模型生成的 Proposal / 测试 Implementation。源码包 7,049,733 bytes，SHA-256 `4e36e3d6264583afa819645dd46d60c19f2305f32bd0b2dd9723456b07c3aa50`，经本地 Connector → HTTPS 平台接受后用于原生会话及远端 Runner。

| 链路 | 固定身份 | 当前验收状态 |
|---|---|---|
| 正常 Sum API + 真实断线恢复 | Run `01a153ef-2106-7fc4-b164-ef5ebfdcc85e` | **PASSED**：唯一原 Execution `COMPLETED / PASS`，7 个 Canonical TestCase 均 PASS，5 份可信 Evidence；恢复后 Job 成功、Binding CLOSED、正式 `RELEASE_READY` 与报告已接受 |
| 故意有缺陷的 Sum API + GitLab | Run `01a153ef-8937-7080-bba0-e96796b8e97e` | **PASSED**：正式 Execution `COMPLETED / FAIL`（1 个 TestCase PASS、3 个 FAIL、0 ERROR），5 份可信 Evidence，接受 1 个 PRODUCT_DEFECT Finding；本地提单成功，最终 `RELEASE_BLOCKED`，报告已接受 |

正向轮次只暂停指定 Connector 进程，API / Worker / 原生 Provider 与远端 Runner 保持运行。UTC 11:36:11 开始暂停；平台观察设备离线且全部本地 dispatch grant 已过期时，原 Job 与 Binding 仍保持有效，以便原 Execution `01a153f0-f22a-722c-a153-b295d69da83b` 收尾。该 Execution 于 11:38:11 完成 `PASS`，之后原 Job 才失败、Binding 进入 `RECOVERY_REQUIRED`。11:38:52 恢复 Connector，旧 call 为 `OUTCOME_UNKNOWN / stopped=true`；连接恢复没有自行开始工作，epoch 仍为 1。

随后调用正式 `/bindings/{id}/recover`，原 Binding `01a153ef-58ae-7e0f-955f-f501f38e2b84` 从 epoch 1 递增至 2，原主 AgentSession `01a153ef-58ac-73c3-afdc-d08c0f94d96c`、原生会话与 workspace 核验不变；通过正式 Job retry 创建 `01a153f5-294d-78fe-a065-ca4ab8f72c85`，保留 `retry_of_job_id=01a153ef-2132-790b-bad8-c3220865b826`。不修改数据库来强行成功，不新建 Run 绕过恢复。

恢复后的 Job 已 `SUCCEEDED`，报告 `01a153f9-e771-76dd-b7bd-3a9611a0b5d0` 引用正式 FINAL Verdict `VER-01A153F9C0B47307BECD80AB9DE5DDCF`（`RELEASE_READY`）。重新读取报告内容并独立计算 SHA-256，与平台记录 `7ac79236fe6386700230501ae0861fdf8c06dbaed75ca41636911d2d19f1e633` 一致。最终再次查询 Execution，仍只有原 ID 一条，没有恢复触发的重复 Runner 测试。

## GitLab 测试 Issue 授权

真实写入仅针对操作者明确批准的私有 GitLab 项目及负责人。测试 Issue 标注 `[HyperTest ADR-015 acceptance]`，说明是故意有缺陷的 Sum API fixture 集成验收，不将它误称目标项目业务缺陷。只通过被接受 Finding → `request_gitlab_issue` → 平台策略 → 本地受控 `glab` 路径创建一次，再独立读取核验。

真实 Issue 已成功创建并指派，原始 URL、IID、项目和负责人身份仅在本机私有证据中保留。平台操作 `01a15400-0be9-7be1-ac78-24bc653a8c00` 已 `SUCCEEDED`，关联已接受 Finding `FND-01A153FFCF837D1F936CBEC80C38DF66`；Finding 保持 `NEW`，提单没有自动确认或解决它。

通过独立 `glab api` 只读核验：目标项目与唯一负责人均匹配批准范围，原 correlation、Finding 和其 3 份关联 Evidence 引用匹配，description 明确说明故意缺陷 fixture 验收。按验收标题查询只有 1 个 Issue，验收前查询为空；没有通过 CLI 绕过平台新建 Issue。外部 Issue 保持原状态，供操作者查看。

该 Run 的正式 Execution 为 `01a153fc-1364-7ade-84d9-cf8bbbb42394`，恢复 Job `01a153f9-2ed7-721b-8255-00ea695aa4ff` 已 `SUCCEEDED`；正式 FINAL Verdict 为 `VER-01A1540036F3711AA9F2236013A750B5`（`RELEASE_BLOCKED`）。报告 `01a15400-7144-7dc7-9cf1-1af4b032bb13` 已接受，独立读取内容重算 SHA-256 与 `12287dfbff40cd8abb2948610222ac90601273f797e6f218cf963c4d6b042ac8` 一致，Binding CLOSED。首次无效业务参数造成的失败 Job / Attempt 保留，通过正式恢复 API 在原 Run / 主会话中继续，没有新建 Run 绕过失败。

UNKNOWN、超时、丢失响应及本地账本重启 / 丢失的“只查询、不重复 POST”分支已有自动化回归；不将这些隔离测试称作全部完成真实外部故障注入。非秘密元数据及摘要保存在[验收证据 JSON](evidence/adr015-20261019.json)。

## 验收发现并修复的问题

1. 真实远端 `docker cp` 耗时约 35 秒，超过原 30 秒控制命令超时。首次 Run `01a153de-856d-7bfd-a35a-80e4a2973bcd` 的 Execution 保留 `ERROR / INCONCLUSIVE`，未作为通过证据。仅为有界源码复制增加按大小计算的 120—360 秒超时，不改变测试本身超时，也不把报告提交成功当成测试通过。
2. Connector 响应校验错误地用完整业务参数 schema 拒绝 `get_call` 中的无效工具参数，导致 Agent 无法收到正常 typed rejection。改为只在传输边界检查已批准工具、ID、JSON 形状与字节上限，由平台 `HarnessTools` 返回业务拒绝，管理查询可继续。
3. 恢复后的任务领取仍限定服务器 host ID，已绑定本地 Run 停在队列。调度器现在核对原 Selection / Placement / node / source 身份后领取本地 Run，保留异服务器宿主的原 fencing，并增加 PostgreSQL 正反回归。
4. 超过 256 条活动事件的 call 在管理查询中可能因窗口淘汰被误判 cursor gap。管理查询现在返回经过完整 typed 校验的状态 / 耗时快照，抑制事件和待办工具；正常执行轮询继续要求连续事件，不用对账重放活动或执行工具。
5. API 硬退出或 caller 丢失后，过期 SENT / QUEUED 可能长期占据 256 项队列。新增有界回收：只转 `UNKNOWN`，绝不重新排队；配额检查、WSS 重连 / 循环和迟到响应都处理过期状态。模拟遗留消息、满队列与重连的真实 PostgreSQL / WSS 回归验证不会重投副作用。

## 自动化、界面与未宣称的范围

- 全套 Python：**866 passed、18 skipped**（140.26 秒）；18 项均为要求显式开启的 controlled Docker smoke。本次另外完成上述两条实际远端 Docker Execution。最后 mailbox 硬退出回收修复后，对独立数据库运行 Connector / WSS 与管理快照相关回归 **23 passed**；本地续跑领取与服务器兼容相关组合 **52 passed**。
- Web：104 tests passed，typecheck 与 production build 通过；双模式表单经真实浏览器可见检查，Impeccable detector 在全部变更前端文件上返回 0 findings。该检查未通过浏览器授予额外权限。
- 源码与关键授权范围、撤权 race、不可变选择、UNKNOWN 提单对账、服务器 Harness 兼容均有独立回归。Ruff、diff 与文档链接 / 锚点检查通过。独立复核发现的问题已修复并补回归，无剩余必修阻断。

真实长断线、TTL 到期、Runner drain 和原会话恢复已有上述实际记录；全部操作系统休眠、`WAITING_INPUT` 离线、设备撤销 / 离线取消、原会话丢失的真实设备组合矩阵尚未逐一执行。现有单元 / 集成覆盖与真实验收范围分别陈述。生产部署还需依操作指南配置既有受保护入口的 WSS Upgrade / 源码大小与超时，并执行备份、迁移和新运行时验证；本次没有进行生产切换。

## 可复现记录与保留

隔离驱动为 `scripts/adr015_live_cycle.py`。必须使用新建可丢弃数据库并升级至 head，状态目录新建为 `0700`；例如：

```bash
PYTHONPATH=src python scripts/adr015_live_cycle.py \
  --state-dir /private/tmp/hypertest-adr015-new \
  --database-url '<disposable PostgreSQL asyncpg URL>' \
  --port 18416 --docker-host ssh://hypertest-one \
  --private-origin 'https://gitlab.example.invalid/approved/private-repository.git' \
  --private-sha '<approved full commit SHA>'
```

`--broken --gitlab-test-issue --gitlab-config <本机私有配置文件>` 会触发真实外部写入，仅在另获明确测试目标 / 负责人授权时使用，不能为重跑验收而重复创建已存在 Issue。配置须为本机 `0600` 普通 JSON 文件，仅固定获准目标（不包含 token）：

```json
{
  "base_url": "https://gitlab.example.invalid",
  "project_id": 1,
  "assignee": "approved-developer",
  "assignee_id": 1,
  "integration_id": "approved-acceptance"
}
```

示例目标和 ID 均为占位符，运行前替换为操作者批准的实际范围。驱动仅在所有正式 Execution 完成、预期 Gate、报告及请求的外部结果均核验后标记 `acceptance_status=PASSED`；Job 成功本身不足以通过。

本机原始证据、设备 token / Operator 文件和 Provider journal 保存在受保护的本地私有目录，不能提交、作为报告附件或整体上传。公开仓库仅保留经过脱敏的记录以及公共 fixture 的身份与摘要。停止进程前核对这些目录的 PID 与命令，禁止依据陈旧 PID 盲目终止进程；清理仅限本次隔离环境，不删除生产 Artifact / 数据或用户原生认证。

验收结束后已撤销三个隔离测试节点的设备授权，按 PID / 命令身份核对后停止本次 API、Worker、Connector 和 Web dev 进程；仅停止本次 `hypertest-adr015-pg` 容器，保留其可丢弃验收数据库与本机私有证据。临时 `web/node_modules` 链接已移除。生产服务和本机既有 Codex / Git / glab 登录均未变更。
