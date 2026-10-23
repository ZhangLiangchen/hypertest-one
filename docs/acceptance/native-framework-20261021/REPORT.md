# 真实 SUT 原生测试盘点与本轮结果

2026-10-21，Asia/Singapore。本轮测试执行已完成：Blockchain 原生 Maven/JUnit **60 PASS**，xBlock 既有 Java/Node consumer-parity **17 个场景 PASS**（25 个被断言步骤），另独立 selfcheck PASS。三次进程均为首次运行、exit 0，没有覆盖失败日志或重试。结果范围为真实产品组件的隔离协议测试；当前部署、共享 staging/dev166 业务、活链和正式平台质量结论均未因此证明。

## 1. 身份、仓库与授权盘点

| 对象 | 本机核验身份 | 使用边界 |
| --- | --- | --- |
| Hypervise 既有测试框架主目录 | `/Users/zhangliangchen/PycharmProjects/hypervise_pure`，`master@83a1568905a9ac73852bd4749eeeea540b91b0b5`，dirty，12 个现有 worktree | 保留已有修改；旧 README 的174/210数量属于历史，静态盘点当前248个`test_*.py`文件，未把文件数当测试用例数 |
| 本轮 xBlock 测试资产 | 同仓既有 `zealous-williams-51bed9` worktree，`claude/xblock-async-energy-vendor-d7fefe@d4bd46e5daee8f5b4906deb5c8a2aadc7f34e584` | 只有既有无关未跟踪技能目录；所用4个入口/断言资产已跟踪且无修改，逐文件SHA在inventory |
| xBlock SUT | 既有 `.tronsave-work/asset-jar/app.jar`，183426836 bytes，SHA256 `8d53f8db68856feefacf3585f3c7f55d8ce500d043b2027cd4a5b3cd8478129e` | 历史记录为dev166资产服务JAR；没有git.properties/build-info，JAR到完整源码SHA/当前部署的绑定**UNVERIFIED** |
| Blockchain SUT | `hypervise_pure/docs/raw/source_code/blockchain`，真实独立Git clone，clean，`dev@0914459b323b82d8f794145247c4627625a6c87b`，origin `https://gitlab.charprotocol.com/blockchain/blockchain.git` | 本轮用该固定提交的原生starter模块，74个tracked文件经本地git archive物化后逐blob比对；未改用户checkout |
| xBlock 常规源码快照目录 | `docs/raw/source_code/xblock-service-asset` 本身不是独立Git clone；向上解析会落到Hypervise | 不能把测试框架SHA冒作asset SUT源码SHA；没有以其作为本轮源码执行身份 |
| GitLab 本机访问 | glab 1.106.0；`gitlab.charprotocol.com` keyring登录用户`zhangliangchen`（id115，active）；GET核验project231 `blockchain/blockchain`/dev与project127 `xblock/xblock-service-asset`/dev可读 | 默认HTTPS校验成功，没有TLS绕过；没有请求写权限、创建问题单或修改仓库 |

GitLab存在历史缩写`cdb9686e`对应完整提交`cdb9686ec1c743143a285eae748bb46e7980a841`，但仅说明该提交存在，**不证明本地JAR由其构建**。MD5与旧脚本固定值一致也只支持二进制完整性。

完整上下文见[inventory.json](inventory.json)、[environment.json](environment.json)、[blockchain源码物化记录](blockchain-source.materialization.json)。平台native actor授权、Provider登录和生产SSH访问均为`NOT_CHECKED`；CLI存在或GitLab登录不推导这些授权。

## 2. 已有框架、入口、依赖与报告

| 既有路径 | 原生入口/报告 | 依赖和环境 | 本轮选择 |
| --- | --- | --- | --- |
| Hypervise Python API/E2E | 根`Makefile`→`python`目录pytest；`pytest.ini`/conftest/原有fixtures；Allure、pytest stdout，可加原生JUnit XML | `.venv` Python3.13.3/pytest9.0.2；requirements含requests、PyYAML、cryptography、web3、tronpy、Allure、Playwright；`XBLOCK_ENV`区分dev/staging/internal环境 | 未运行共享API/E2E；不能因Makefile排除onchain就假设没有其他副作用 |
| xBlock TronSave消费端 | `deploy/localchain/tronsave-mock/consumer-parity/run.sh selfcheck`和`local scenarios --only ...`；原生JSONL | JDK21+、Node22+、已有asset JAR、unzip；本机JBR21.0.10、Node26.8.1；`JAVA_HOME`、`TMPDIR`；本地wrapper生成短期测试凭据并通过环境变量传递 | 本轮17场景；真实asset类+既有Node供应商HTTP/内存链；无Spring/DB/MQ或共享远端服务 |
| Blockchain独立RPC starter | Maven原生`test -Dtest=EvmBroadcastClassificationTest,EvmBroadcastOkHttpClassificationTest,TronBroadcastClassificationTest,TronBroadcastOkHttpClassificationTest`；Surefire XML/txt | Java21、Maven3.9.16；JUnit5、AssertJ、MockWebServer4.12.0、Surefire3.2.5；原POM和CI已有Maven工具链；本轮`-o`离线，使用隔离克隆的本机m2缓存与无认证settings | 本轮4 suites/60断言；真实产品客户端类，loopback MockWebServer |

测试分析先于执行保存为[TEST_PLAN.md](TEST_PLAN.md)。选择标准是本机可复现、真实产品行为断言、没有共享写副作用；不新建样例应用或HyperTest Runner。没有升级/安装SUT依赖，没有运行资源创建、资金操作、故障注入到共享环境或清理旧工作区。

## 3. 实际执行与原始事实

| 独立运行 | 本地时间（SGT） | exit | 实际原生结果 | 原始材料 |
| --- | --- | --- | --- | --- |
| xBlock selfcheck | 14:23:13.022→14:23:15.578 | 0 | PASS，5个本地参数拒绝检查；72场景schema problems0；实际类POLL_BUDGET=12s，POLL_INTERVAL=1s，read10s/call15s，retryOnConnectionFailure=false | [process](xblock-selfcheck.process.json)、[JSONL](xblock-selfcheck.stdout.jsonl)、[stderr](xblock-selfcheck.stderr.log) |
| xBlock consumer-parity 17场景 | 14:23:47.441→14:24:26.730 | 0 | passed17/failed0/errors0/skipped0；25个step断言 | [process](xblock-scenarios.process.json)、[JSONL原件](xblock-scenarios.stdout.jsonl)、[stderr](xblock-scenarios.stderr.log) |
| Blockchain Maven/JUnit | 14:25:48.158→14:25:54.334 | 0 | EVM JDK18/OkHttp18；TRON JDK12/OkHttp12；总60，failures/errors/skipped均0 | [process](blockchain-maven-01.process.json)、[stdout](blockchain-maven-01.stdout.log)、[stderr](blockchain-maven-01.stderr.log)、[Surefire目录](blockchain-surefire/) |

process记录完整真实argv、cwd、UTC起止、exit、环境变量名称、原始文件字节/hash。Blockchain执行cwd是本轮隔离物化的真实源码模块，并非用户原checkout；运行原有POM、源码和测试文件，执行前逐文件比对固定Git blob。编译输出、短期服务状态、JAR提取cache和本机m2副本仅在忽略的`private-runtime/`，没有外发源码或二进制。

xBlock正向含正常购能、延期查询、精确余额扣款、已激活地址。负向含400/401/429、缺失订单ID、socket断开、金额64000/64001边界、重复未完成订单、余额不足、split delegates、错误订单ID、非法地址与TRON_TEST本地门控。429直接观察为`acceptanceConclusion=UNKNOWN`/`BUY_ENERGY_RESULT_UNKNOWN`，断言PASS。split delegates直接观察为已接受订单仍`ORDER_PENDING`，其断言PASS仅表示消费者现有行为与既定oracle一致；不能据此宣布该业务行为质量通过或新增缺陷已确认。

Blockchain正向验证ACCEPTED和ALREADY_KNOWN，负向验证明确REJECTED和传输/协议不确定的ACCEPTANCE_UNKNOWN，保留本地交易标识、`safeToReplay=false`及single-send。超时/断连等由原有loopback MockWebServer测试控制，无真实链广播。stderr有6条MockWebServer“connection didn't make a request”警告，原件保留；最终报告没有测试failure/error。

本轮没有失败执行，也未人为制造失败来补充验收。负向业务断言通过不等于failed execution；产品缺陷、失败材料接收与正式可信来源接受仍需其各自验收。

## 4. 事实、推断与待验证材料分层

- **直接观察**：三次进程exit0、各框架原始结果、已有文件/源码身份、GitLab元数据可读、本机工具版本、精确模块tracked blob比对，以及本轮前后Git commit/branch/dirty清单一致。
- **Agent推断**：JSONL和Surefire XML足以具体约束首个原生结果接入的数据需求；`case id + 原生report + exit + 冻结输入 + 独立来源核验`需要分别入账。该推断不是正式Evidence。
- **待验证**：本地shell/JUnit/JSONL的可信采集来源、平台actor授权、案例/计划绑定、独立Verifier签收；xBlock JAR来源到commit的证明；任何当前部署、链上finality、共享环境E2E和发布门禁。

所有本轮材料登记为`LOCAL_EXECUTION_MATERIAL`/`PENDING_VERIFICATION`，平台来源仍`UNVERIFIED`，`formal_evidence=false`。本地有限范围断言结果为PASS；正式Gate结论应保持UNKNOWN（或按实际缺口BLOCKED），没有执行签名/独立可信采集时不得凭摘要、字节数或hash升级为正式执行事实。[NATIVE_RESULTS.json](NATIVE_RESULTS.json)提供逐用例索引；它是派生索引，不替代原始JSONL/XML。

本机已通过Memory Bus只读读取最新UC-TX-18活动上下文；其20261021-r1的12笔共享环境业务结果属于另一个会话/轮次，未纳入本轮77个原生场景/断言计数或质量结论。本轮不领取其共享钱包/供应商管理写权，不更改其问题单和日志。

## 5. 保全、材料隐私与未完成项

[preservation.json](preservation.json)核对三个既有目录的commit、branch和dirty清单均与执行前相同；此检查不证明所有未跟踪文件内容的完整性。没有reset/checkout/删除现有worktree，没有远端写入、部署、数据库迁移、Issue、链交易或源码上传。原JAR不复制进版本控制，编译cache不提交。

公开候选原件仅含loopback地址、测试场景结果、本机路径和JVM属性；扫描JSONL credential字段仅发现boolean `apikey2`，Surefire属性未发现凭据命名项，Maven使用离线/无认证settings；未捕获任何认证值。原始JSONL、XML和stdout/stderr按字节保留；没有清洗文件后冒称原件。hash用于完整性核对，不提供执行来源信任。

未完成：独立平台来源验真、当前部署绑定、真实SUT业务E2E/活链、失败执行接收验收及发布决策。此轮选择无共享副作用路径，未因这些缺口中止可独立完成的真实原生组件验证。若下一步需要共享环境业务测试，应另行核验该环境当前健康/部署、固定资源owner与授权；不复用本轮隔离PASS推导。
