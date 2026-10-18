# 受控依赖与服务型 API 环境验收

依据白皮书 §20/25、领域模型 §9、TMP §9.1、技术架构 §26 与 [ADR-012](architecture/ADR-012_CONTROLLED_API_ENVIRONMENTS.md)。范围为单 Operator、Python/pytest 和无外部依赖服务的单 ASGI 应用；不将该路径泛化到任意 requirements、远端 SIT、多服务/数据库或秘密管理。

## 实现边界

创建向导为源码 → PRD → 执行环境 → 策略 → 确认。环境目录只允许 `python-pytest-v1` / `python-api-v2`；API host 镜像检查与 Worker/服务就绪明确分开。原 configuration_text 仍按原字节保存，不解释成 Shell 或依赖安装。bootstrap 冻结实际镜像与依赖/launcher身份；重复请求返回原绑定，不重新解析 tag。迁移 `0011_execution_environments` 仅加 nullable JSONB，不回填旧 Source 或修改原指纹/FINAL hash。

可信镜像使用 digest-pinned base 和全传递依赖的版本/SHA256 binary wheel锁。运行阶段不 build/pull/install，固定 imageID 缺失或清单不符就停止。服务入口为受限 `module:attribute`，health 仅本地相对 path；不接受任意镜像、命令、URL、挂载、端口或凭据。Runner 内真实服务及 HTTP pytest 共享 loopback，保持 network none、nonroot、只读源/根、capdrop、CPU/内存/PID限制。服务启动/健康/退出/清理及有界日志进入可信 Evidence；就绪不替代 Case PASS。

首版自动化记录（`bc842e1`，保留原版本结果；API-v2 当前检查见后节）：

| 检查 | 已实证结果 |
|---|---|
| 后端必需检查 | Ruff、独立 testDB Alembic0011、**464 passed / 8 opt-in skipped / 3 existing warnings，45.59s**；112 输入 manifest `7b9f0b11ae21b171620bb43a68ba1611ab3d42e498c505ca2e14b4119f0edae3` |
| 独立 Runner 检查 | **55 passed**：47 unit + **8 显式真实 Docker**；真实HTTP PASS、业务断言FAIL、启动异常、health404/302、服务早退、总超时、受控pytest及所属资源清理 |
| 真实隔离 | Docker中UID65534、源不可写、无外网route；同名asyncio/json/pytest/uvicorn源文件不能替换可信 bootstrap；固定proof缺失/损坏不允许PASS |
| Web | 独立 fresh npmci、**53 tests**、typecheck、build、audit0；42输入 manifest `fe24ed97952b0971185944b9bf570374cd14d02da6d9900932218dc08845ca71`；本功能唯一机械扫描 `[]` |
| 绑定与并发 | 26真实PG/API回归；7运行边界回归，覆盖锁外inspect、检查中入队/取消后重新admission、环境错误即使有passingJUnit仍不能PASS；契约替身不计作模型验收 |
| 本地升级 | 已停止空闲 API/Worker，配对备份后 0010→0011 **5 checks 全通过**；33旧表1395行原列保留、132旧文件原字节保留，6旧Source保持SQLNULL |
| 独立恢复 | 新保留数据库 `hypertest_env_restore_20261018t104107z_0cad40` **19/19 checks**；61个DB产物引用验证，旧真实FINAL state hash/manifest只读复算保持 |

独立审阅发现并修复了 SQL NULL/JSON null、旧Gate新增空键，以及锁外检查后直接调用入队/取消竞争窗口；对应回归已通过。环境错误可以进入基于证据的诊断，但不预判模型根因，也不把 NEW Finding 视为人工确认。

[后端日志](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-backend-full-2026-10-18.log) · [Web检查](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-web-checks-2026-10-18.md) · [Runner检查](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-runner-implementation-2026-10-18.md) · [本地迁移](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-local-migration-2026-10-18.json) · [独立恢复](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-migration-rehearsal-2026-10-18.json)

## API v2 集成修复与复验

首轮两个真实 Web/Codex 运行均已完成正式 Docker 服务就绪（HTTP200、cleanup true），但仓库 `tests/conftest.py` 的 dotenv 导入导致 pytest 收集失败。它们真实保留为 ERROR/INCONCLUSIVE、ENVIRONMENT_FAILURE Finding 和 FINAL BLOCKED，不能算业务失败诊断通过，也不删除或回写。

新增不可变 API-v2 profile，固定 `-c /dev/null --noconftest --rootdir=/repo`，生成模块的 fixtures 自包含；依赖锁保持批准闭包，未为偶然仓库依赖扩包。API-v1 / pytest-v1 使用原字节归档 launcher `7f2c37e97c21c118eeca1cf929a338f9c97b26e50cbbf31a575ed855616e3815` 与原镜像身份。0012 仅扩 profile CHECK。

| 复验 | 结果 |
|---|---|
| 全量后端 | Ruff、testDB0012、474 passed /18 opt-in skipped /3 existing warnings（49.76s） |
| 真实 Docker | 67 passed =49 unit +18真实Docker；双污染pytest.ini/pyproject与conftest下均验证HTTP成功及业务FAIL |
| Web | 全量55 tests、环境定向14、typecheck、build通过；当前42文件manifest e40e8f7712edcc1fd6acd6d977d31916f015f3f5d5be28be6a3dd62e5a111de2 |
| 历史保全 | 新停机配对备份后本地0011→0012，7/7检查通过，161产物字节及所有原表行保持；独立0011→0012恢复19/19通过，33表2197行、161files/97DB产物引用及旧FINAL hash保持 |
| 绑定兼容 | 33真实PG/API检查：旧v1原key重放不resolve、跨版本同key409零写、newkey新Snapshot、旧fingerprint/Gate语义保持 |

## 真实产品验收登记

真实 Web 已完成两个独立 Project、相同 PRD/源码/Policy 的 API-v2 创建与服务选择。输入及运行源码固定 `08799a4f3ad5db809015c8dafe7f6f5dfa1f801f`；新模型输出由 HyperTest 验证提交，未注入模拟提案。成功链和独立业务故障链各28/28只读核验全部通过。原 stdlib 与问答链保留原身份，不代替本轮服务型实测。

成功 Run `01a14eba-5bff-7cd6-b643-001537135187`：7Req /9Risk /17Case /3Impl /1Exec /5Evidence /0Finding，真实 JUnit91PASS，正式执行 PASS/exit0；Gate FINAL RELEASE_READY `01a14ebf-804b-704b-b324-9bf075e9ebd4`。服务 health200、earlyexit false、cleanup true；原始证据hash/size、完整关系链、Audit/Outbox、state hash/manifest、固定干净源码和真实Agent会话均已只读核验。

业务失败 Run `01a14ebc-2b3b-7472-b064-1c8aa7170d06`：6Req /8Risk /8Case /8Impl /1Exec /5Evidence /1Finding，实际 JUnit52实例=30PASS+22FAIL，Execution COMPLETED/FAIL/exit1，非环境错误；服务 health200、earlyexit false、cleanup true。真实 DIAGNOSE_FAILURE 完成，形成 NEW PRODUCT_DEFECT/MAJOR `01a14ec5-2788-71bd-96d7-a566df97ca33`，精确定位 a−b 替代 a+b，并关联3份可信Evidence；没有人工确认/解决。Gate FINAL RELEASE_BLOCKED `01a14ec5-27ef-724e-829b-595b84fa6e3a`。

| 白皮书 §20/25 本轮项目 | 实际验收 |
|---|---|
| Environment snapshot | Source 固定 API-v2 image `sha256:79122954ba2ebc2bb55b30ca3a9533f94423f2ac85beb3693b9a442c1b138634`、21依赖、lock `67b4693d830ec8127bf2164acbcc4a5044d6e9997173656186f31655dce337df`、launcher `3aeb0c7c96458046830239c640aa970fbcfd0b76c1e2bad329475319360e9c9e`；执行按ID复核 |
| Agent intelligence → Canonical | 正常/故障各4/5个真实Codex Mission；接受提案后由平台提交关系链。3/8份生成源码逐字节及AST核对，均使用httpx+HYPERTEST_BASE_URL真实HTTP，无mock/直接SUT调用 |
| Runner facts | 同容器ASGI+pytest、真实HTTP200、91PASS与30PASS/22FAIL独立产生；各5类RUNNER/VERIFIED证据含service LOG，hash/size均匹配 |
| Failure diagnosis | 22个业务断言失败解释为减法缺陷；NEW Finding引用正式Evidence，未夸大成独立并发故障 |
| HyperTest decision | 两条FINAL分别RELEASE_READY/RELEASE_BLOCKED；statehash、manifest、同Run Job归属和Audit/Outbox配对均匹配 |
| 可操作Web | 真实创建独立Project→固定SHA/同PRD→API-v2服务选择→后台周期→执行身份/服务日志/JUnit→Finding证据→FINAL；中英界面实际核对，刷新不重提任务 |
| 历史保全 | 迁移/恢复保留33表2197行、161files；新双链后再以恢复库作只读subset验证，排除revision/心跳后32表2182旧行及全部161旧files无修改，包含两条v1失败历史 |

成功 FINAL state `8ea0d30411f86e82f4226b0b73b2ad0522cdad459a6ba5aff22ea84a8216282f` / manifest `9ad0a5fd684146b4a59b734005076a5b132fc091d170f16c74d4961804bd17d8`；失败 FINAL state `0232b97a4d30f180f15f5194f419c352f74af676912b65ad9f56f27f0327ef8f` / manifest `45d643c629d03b66907dac75f5123d2ab825b89f74b28817aa329b6965a21e01`。Canonical Case 与JUnit参数化实例数量不同，不能相互替代。

本地迁移已保留两次配对备份。服务器本轮未访问或修改，现有数据、45.76.149.233/32 双层白名单、SSH隧道及OAuth不变。实现提交为 `bc842e1` / `08799a4`，真实运行固定后者；最后仅补录验收文档。PR [#8](https://github.com/ZhangLiangchen/hypertest-one/pull/8) 接续尚未合并的 #7，不自动合并或部署。

[双链原始汇总](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-v2-acceptance-summary-2026-10-18.json) · [成功28项](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-v2-ready-final-2026-10-18.json) · [业务失败28项](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-v2-blocked-final-2026-10-18.json) · [独立恢复19项](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-v2-migration-rehearsal-2026-10-18.md) · [最终历史保全](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-v2-final-preservation-retry-2026-10-18.json) · [115后端输入清单](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-v2-backend-source-2026-10-18.json)



## 后续部署步骤与边界

本轮仅本地开发与验收，PR #8 接续未合并的 #7；没有服务器变更。同步时先确认现有备份与无活跃任务，再备份数据库和产物、部署合并后的代码并升级 Alembic head。按 README 在目标机器显式构建 `python-pytest-v1` / `python-api-v2` 两个批准镜像，API/Worker 使用一致的 `HYPERTEST_RUNNER_CONTROLLED_IMAGE` / `HYPERTEST_RUNNER_API_V2_IMAGE`；保留原 legacy/API-v1 镜像和配置以供历史绑定复核。运行阶段不负责构建、拉取或安装。

部署必须保留 PostgreSQL/产物/OAuth、现有回环绑定、45.76.149.233/32 的 UFW/nginx 双层白名单与 SSH 隧道；目录检查通过只证明 API host 镜像可用，不能替代 Worker、服务和真实业务就绪。多服务、外部数据库、凭据、远端 SIT、其他框架/语言和任意依赖仍需单独批准的 profile 与相应协议，不据此宣称全范围第一阶段完成。
