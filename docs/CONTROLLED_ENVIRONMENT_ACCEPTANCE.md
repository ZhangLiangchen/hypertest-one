# 受控依赖与服务型 API 环境验收

依据白皮书 §20/25、领域模型 §9、TMP §9.1、技术架构 §26 与 [ADR-012](architecture/ADR-012_CONTROLLED_API_ENVIRONMENTS.md)。范围为单 Operator、Python/pytest 和无外部依赖服务的单 ASGI 应用；不将该路径泛化到任意 requirements、远端 SIT、多服务/数据库或秘密管理。

## 实现与自动化

创建向导为源码 → PRD → 执行环境 → 策略 → 确认。环境目录只允许 `python-pytest-v1` / `python-api-v2`；API host 镜像检查与 Worker/服务就绪明确分开。原 configuration_text 仍按原字节保存，不解释成 Shell 或依赖安装。bootstrap 冻结实际镜像与依赖/launcher身份；重复请求返回原绑定，不重新解析 tag。迁移 `0011_execution_environments` 仅加 nullable JSONB，不回填旧 Source 或修改原指纹/FINAL hash。

可信镜像使用 digest-pinned base 和全传递依赖的版本/SHA256 binary wheel锁。运行阶段不 build/pull/install，固定 imageID 缺失或清单不符就停止。服务入口为受限 `module:attribute`，health 仅本地相对 path；不接受任意镜像、命令、URL、挂载、端口或凭据。Runner 内真实服务及 HTTP pytest 共享 loopback，保持 network none、nonroot、只读源/根、capdrop、CPU/内存/PID限制。服务启动/健康/退出/清理及有界日志进入可信 Evidence；就绪不替代 Case PASS。

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
| 历史保全 | 新停机配对备份后本地0011→0012，7/7检查通过，161产物字节及所有原表行保持；独立恢复复验另记 |
| 绑定兼容 | 33真实PG/API检查：旧v1原key重放不resolve、跨版本同key409零写、newkey新Snapshot、旧fingerprint/Gate语义保持 |

## 真实产品验收登记

真实 Web 创建/环境选择、真实 Codex 生成 HTTP 测试、Docker服务/业务成功，以及独立业务故障的真实诊断链尚在本轮继续验证；本段不预写通过。原有 stdlib 与问答活动链保留各自执行身份，不能代替新服务型环境实测。

本地升级已保留[配对备份](/Users/liangchenzhang/PycharmProjects/hypertest-one-handoff/controlled-environment-local-backup-2026-10-18.json)。服务器仍为 a48bc96/schema0009，本轮未访问或修改服务器；现有数据、45.76.149.233/32 双层白名单、SSH隧道与OAuth保持。PR #7 尚未合并，新分支接续其提交；最终运行SHA、真实Run、PR和CI会在完成后登记。
