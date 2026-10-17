# HyperTest One 服务器操作交付

核验日期：2026-10-17，Asia/Singapore。本文中的“交接目录”指本机 `/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff`，可移交证据副本见 [第一阶段验收](FIRST_PHASE_ACCEPTANCE.md)。目标：155.138.206.106，root SSH/22。实际主机是 Debian13.7 x86_64、2CPU/3915MiB，已有7.7GiB swap保留。此部署面向一个可信操作者，使用SSH认证作为访问边界。

## 当前版本与目录

- 当前应用提交：`89d15aeb73230d313809296de2343b8eddc6d6b6`。
- 当前选择：`/opt/hypertest/current` → `/opt/hypertest/releases/89d15aeb73230d313809296de2343b8eddc6d6b6`。
- 上一可启动版本：`/opt/hypertest/releases/5b1b7ce6920624e2724172431c7879f9f2fa10fd`。
- 服务账号及实际home：`hypertest`，`/var/lib/hypertest`。
- 共享配置：`/etc/hypertest/hypertest.env`（root:hypertest0640）；PG初始化凭据：`/etc/hypertest/postgres.env`（root0600）。
- Canonical Artifacts：`/var/lib/hypertest/artifacts`；测试仓库：`/var/lib/hypertest/workspaces`；Codex正常可写runtime：`/var/lib/hypertest/.codex`。
- Python3.12.15；Node22.23.3；官方Codex0.163.0；Docker26.1.5；PostgreSQL17.11容器`hypertest-postgres`、volume`hypertest_pgdata`。
- 数据库head：`0008_job_ownership`。首次完整0001→0008升级已通过；89d补丁未改变schema，没有降级/清库。
- 可信Runner：`hypertest-runner:py312`，image ID `sha256:a8f6f769b6b6a34ed6e6968b6c9816c17d860fbb38445c2473d3544addd20b56`。已由服务用户实际运行禁网/只读/nonroot/cap-drop/512MiB/1CPU容器验证。

应用服务均已enable；API与Worker共用正式数据库、Artifact Store和Workspace Root：

```bash
systemctl status hypertest-api hypertest-worker hypertest-web nginx
systemctl is-active hypertest-api hypertest-worker hypertest-web nginx
journalctl -u hypertest-worker --since today
curl -fsS http://127.0.0.1:8080/api/v1/health
curl -fsS http://127.0.0.1:8080/api/v1/capabilities
```

unit文件在`/etc/systemd/system/hypertest-{api,worker,web}.service`。使用一进程API、一个独立Worker、Next生产服务器，无reload/dev服务器。nginx站点为`/etc/nginx/sites-available/hypertest.conf`。

## 访问与现有隧道

远端仅SSH22公网监听；nginx8080、API8000、Web3000、PG5432均绑定127.0.0.1，UFW未新增应用或数据库端口。

当前本机浏览：http://127.0.0.1:8080 。已建立的SSH隧道PID为`92044`，日志为本交接目录`server-tunnel-2026-10-17.log`；停止只关闭隧道：

```bash
kill 92044
```

以后在本机终端重新建立（终端保持打开）：

```bash
ssh -p 22 -N -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8080:127.0.0.1:8080 root@155.138.206.106
```

原有known_hosts与远端Ed25519公钥指纹已一致核验：`SHA256:PoYUrSTDnN10A010My98ydOX3HQq/FynK/VxU9T5AqI`。

## 由操作者亲自完成OAuth

用户已亲自完成OAuth；2026-10-17最新只读检查返回 **Logged in using ChatGPT**（exit0）。安装/验收Agent没有执行login，没有读取或复制任何auth内容。以下保留日后需要重新认证时的精确操作；当前无需重复登录。

先从本机进入你已经验证过的服务器终端：

```bash
ssh -p 22 root@155.138.206.106
```

再在服务器root终端执行，让CLI在正确服务账号下完成device OAuth；按CLI提示在自己的浏览器完成授权：

```bash
runuser -u hypertest -- env PATH=/opt/hypertest/node/bin:/opt/hypertest/codex/bin:/usr/bin:/bin \
  codex login --device-auth
```

只读检查：

```bash
runuser -u hypertest -- env PATH=/opt/hypertest/node/bin:/opt/hypertest/codex/bin:/usr/bin:/bin \
  codex login status
```

日后重新认证完成后，可从Web继续提交真实模型任务。API/Worker使用同一hypertest账号runtime，不需要复制凭据或改root账号。服务已启用`HYPERTEST_CODEX_IGNORE_USER_CONFIG=true`；适配器显式使用read-only沙箱和结构化结果契约。

未认证HTTPS探测已证实TLS可达；api.openai.com/v1/models返回401，chatgpt/auth主页返回403。这不等于真实模型调用验收，也不能据此判定凭据失效。随后用户完成OAuth，真实Codex/Docker通过与失败诊断双链均成功，已经建立服务端模型可用证据。

## 备份与已验证恢复

脚本：`/opt/hypertest/deploy/backup.sh`。定时器：`hypertest-backup.timer`；每天03:30UTC加0–20分钟随机延迟，即新加坡11:30–11:50。已enable且persistent。历史备份不自动删除。

```bash
systemctl list-timers --all hypertest-backup.timer
systemctl start hypertest-backup.service
systemctl show hypertest-backup.service -p Result -p ExecMainStatus
```

脚本在空闲窗口短暂停止API接收新工作，检查queued/running任务；有工作则跳过，空闲时暂停Worker，配对备份数据库和Artifacts并恢复先前服务。保护锁防止与部署并行。密码/OAuth/源checkout不进入这两份数据档案。

最新已完成备份：`/var/backups/hypertest/20261017T110027Z`，包含生产Web真实创建的Project与Run及PRD Artifact；`database.dump`、`artifacts.tar.gz`的SHA256均通过。核对命令：

```bash
cd /var/backups/hypertest/20261017T110027Z
sha256sum -c SHA256SUMS
```

最新真实数据备份已执行实际隔离恢复：DB`hypertest_restorecheck_20261017110028`，恢复head0008_job_ownership；Artifacts解包到`/var/lib/hypertest/restore-check/20261017T110027Z/artifacts`。恢复SQL核实2Project/2Run/2Execution/8Evidence/3FINAL/1Finding/3Job，activeJob=0。Python从这个解包目录实际读取字节，验证15个引用、12个唯一Artifact，涵盖Evidence SHA/size、所有Implementation source_sha256、PRD/config input hash。正式库及正式Artifact目录未被恢复覆盖。证据为`server-final-restore-2026-10-17.json`；数据库/Artifacts必须使用同一时间戳配对。

## 升级、保留与回滚边界

原始HANDOFF及原始归档保持不变。适配Debian13的最新可重跑材料在服务器`/root/hypertest-deploy-final-89d15ae`及本机`hypertest-one-89d15ae-debian13-deploy.tar.gz`。该归档SHA256：`04a53491b72ea3ba4da36485f0090c13b99e5fc5f4e09f024a70a9d956b6b3c8`。先核验目录内SHA256SUMS；其源码bundle固定89d。prepare与ACTIVATE分阶段，不能把准备完成当成已激活。

升级应先核实完整SHA、独立库测试、当前配对备份及没有活跃任务，再选择新release并重启服务。保留旧release、配置、数据库volume、Artifacts和OAuth；不在current覆盖源码，不执行强制reset/clean，不降级或删除canonical历史。

本次89d只改Python/TMP/tests。Web所有tracked源码/配置/lock与5b完全相同，经git差异与文件树hash核对复用了已通过npm ci/typecheck/build的生产产物；.next产物树SHA256：`25c0e566293a27b651b1fdce2ffcf8b0a7b335acb26dcc94e25a7d18c161a174`。新Python环境独立构建。

应用回滚仅选择已保留且验证可启动的旧release、恢复之前活跃服务；不自动回滚schema。存在活跃任务时先审查并受控停止，不能静默重放执行。正式库需要恢复时，先在隔离库核验备份与同时间Artifacts，再由操作者决定正式恢复。

## 实际验收与当前状态

- 5b在服务器：ruff、独立空库0001→0008、**208 passed**、npm ci/typecheck/build均通过。
- 89d在服务器：ruff、另一独立空库0001→0008、**212 passed，3 warnings，142.49s**。Web输入无变化，复用上述验证产物；无新增正式迁移。
- 两版本实际检查health、数据库projects、Worker heartbeat、生产HTML。89d API/Worker/Web实际cwd均属于89d release，tracked源码clean；Worker available=true且active_workers=1。
- 生产Web创建的Project`01a14972-275a-7c29-a10d-9bb709e150d5`及Run`01a14972-ca09-7f60-9b75-a63ae8bdc74e`在升级后身份完整保留。前后快照在本交接目录`server-upgrade-preservation-{before,after}.json`。
- 已准备真实应用source，无预置测试或Agent结果；manifest为`server-live-fixture-2026-10-17.json`。正确commit3654e6b656b6ae70301de797a533382b210fd0e5，错误commit8baa49cbb67956e99bd8c6a9a732ff81db9105e2。
- **服务端真实Codex CLI→canonical→OFFICIAL Docker→Evidence→Verdict两条链均通过验收。** 正确source：7Req/7Risk/11Case/1Implementation/1Execution/4Evidence，Run COMPLETED，最终RELEASE_READY；旧BLOCKED FINAL保留，sequence2追加新结论。错误source：8Req/8Risk/12Case/2Implementation/1Execution/4Evidence/1Finding，DIAGNOSE_FAILURE实际完成，最终RELEASE_BLOCKED；Finding保留NEW供用户triage。
- 9个真实Codex Mission均Attempt1 ACCEPTED。SnapshotHarness是临时source wrapper，内部使用真实Codex CLI；没有预设Agent结果。两次OFFICIAL执行均由可信Docker Runner产生事实。
- SQL核心关系链JOIN为pass92/fail56，包含Finding的失败完整链JOIN15；pass62Audit/62Outbox、fail69/69，逐实体事件分组差异0。Outbox归属使用payload Run或Audit entity/action关系，避免漏掉没有payload.test_run_id的执行/证据事件。Attempt/Execution的durable_job同Run归属异常0，accepted Proposal缺entity=0。
- 两原始source checkout保持固定commit且git status为空，只含PRD.md/checkout.py；真实执行后的受控Docker容器和volume残留均0。

最终备份正常重启空闲API/Worker后，当前PID为API21637、Worker21639、Web14401；三服务NRestarts=0，实际cwd均属于89d。真实模型Jobs由此前Worker14947执行，历史记录保留。最后readiness为health ok、HTML200、Worker available=true/active_workers1、activeJobs0；Codex login status为Logged in using ChatGPT。主机最后可用约3GiB、盘余56GiB，近期服务ERROR/Traceback和内核OOM计数均0。结构化最终状态：`server-final-state-2026-10-17.json`。

详细阶段日志、hash和恢复证据见同目录`server-acceptance-2026-10-17.md`、`server-tests-89d15ae.log`、`server-readiness-89d15ae.log`、`server-final-backup-2026-10-17.log`。
