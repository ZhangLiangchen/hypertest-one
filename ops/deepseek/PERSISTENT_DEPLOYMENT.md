# 常驻 Cloud Git release（部署准备）

工具从 pushed Git 固定SHA构建持久 Worker RootDirectory，并补齐测试服务器已有 API/Web 的 Cloud 管理配置。历史source30/source29执行及source31快照验收不是本次部署证据。脚本不安装、启动、enable、迁移或创建Task；实际动作由授权运维者逐步执行。默认Cloud关闭。已有Compose `worker` 是legacy Bridge Worker，新Cloud Worker为独立host systemd服务，镜像、身份、入口分开。

## 固定源码与构建

服务器新建独立干净Git checkout，fetch已推送origin后detached checkout最终SHA，不从Mac复制工作树或登录。`--remote-ref origin/<branch>`、HEAD、`--commit`须三者完全相等。基础镜像必须是已核验registry digest。

```bash
python3 -B ops/deepseek/build_worker_release.py \
  --checkout /opt/hypertest/git/hypertest-one --commit <FINAL_40_HEX> \
  --remote-ref origin/<PUSHED_BRANCH> --python-image python@sha256:<REVIEWED_BASE_DIGEST> \
  --output /opt/hypertest-cloud/releases/<FINAL_40_HEX>
```

前置账户固定 `hypertest-cloud` 997:988。父目录root-owned且无group/world写权限；新release0700，保留rootfs发行版权限但不暴露为宿主可执行安装。archive先核路径/链接祖先，后写普通文件、hardlink、最后symlink，拒设备节点/逃逸。仅导出从未启动的临时构建容器，不把它当Agent运行容器。默认Docker userns拒绝不绕过。当前2CPU/4GiB，构建串行，不并行运行Web与Worker build。

镜像提供Python3.12、SDK/runtime exact `0.2.1rc2`、git、非setuid bwrap、SSH client及997:988 NSS。包含SSH client不启用SSH。SDK pair wheel核对lock hash，其余Python/APT依赖记录实际清单和最终imageID，不声称传递依赖完全锁定。source/rootfs/venv archive持久保存，不依赖旧`/tmp`验收venv或停止的隔离PG/API。可选Codex须显式给官方完整payload和独立可信manifestSHA，由真正admission再核完整闭包；不复制Mac登录。

## 私有凭据与当前数据库

API实际999:989不能读原root0600 wrapping key。工具只新建**同一密钥**的999:9890600副本、Web1000:10000600原Operator副本及公共CA0444副本，不旋转key、不改变原权限，不打印秘密值/长度/hash：

```bash
python3 -B ops/deepseek/provision_server_credentials.py --allow-private-copies \
  --wrapping-key /etc/hypertest/cloud/acceptance/wrapping-key \
  --platform-env /etc/hypertest/container/platform.env \
  --public-ca /opt/hypertest/deployments/adr015-forward-20261019/ingress-ca.crt \
  --output /etc/hypertest/cloud-platform/<FINAL_40_HEX>
```

Worker仍由PID1 LoadCredential读取原wrapping/model文件，API仅RO bind副本，两端key-id须一致。工具只提取已有 `HYPERTEST_CONNECTOR_OPERATOR_KEY`，不签发/扩授权；浏览器不得得到该key。CA是服务器公共issuer证书，2026-10-23实际验证现leaf及IP SAN通过，SHA `9647d9a2b33572f328e225910aafe276756a6acb90f44427db37a793b4389396`；不读或部署CA私钥，不拿非selfsigned leaf替代issuer。

运维另准备root0600 `worker.env`，从服务器现有私有平台配置复用当前DB身份，指向现有loopback PG端口（当前5432），不用容器内 `postgres` DNS或旧隔离PG地址。完整URL不放CLI/日志。按 `cloud-worker.env.example` 显式填写两个Cloud开关true、模型/截止和正保守费率；credential路径、Codex开关由unit/drop-in拥有，不能再放EnvironmentFile。API配置的Worker/Codex布尔值须与此env/drop-in一致，仅是配置声明，不是健康证明。

## 渲染与两个doctor层次

预先创建持久runtime为997:9880700；源、venv、payload和release保持root-owned只读，跨升级保留原key/UNKNOWN/HELD。DNS只bind核验后的canonical resolv单文件，不挂整个host `/etc`。

```bash
python3 -B ops/deepseek/render_worker_service.py render \
  --release /opt/hypertest-cloud/releases/<FINAL_40_HEX> --release-sha256 <ACTUAL_RELEASE_JSON_SHA> \
  --env /etc/hypertest/cloud/worker.env --runtime /var/lib/hypertest-cloud/runtime \
  --wrapping-key /etc/hypertest/cloud/acceptance/wrapping-key \
  --deepseek-key /etc/hypertest/cloud/deepseek-api-key --resolv-conf <CANONICAL_RESOLV_FILE> \
  --output /opt/hypertest-cloud/rendered/<FINAL_40_HEX>
python3 -B ops/deepseek/render_worker_service.py doctor --output /opt/hypertest-cloud/rendered/<FINAL_40_HEX>
```

静态doctor仅检查公共完整性，不读认证、不调用SDK/DB/模型；PREPARED不是startup admission通过。另输出 `hypertest-cloud-worker-doctor.service`，保持真实RootDirectory/RO binds/997:988/cap0/NnP/2GiB/0swap/256pids/私有exec tmp/%d/LoadCredential，只把长期ExecStart换成true并PrivateNetwork=yes。运维显式安装启动后，真实ExecStartPre的worker_admission才可给ADMITTED，无DB/claim/模型。`%d`只在unit文件展开，D-Bus systemd-run参数不会替换。

Codex opt-in使用renderer的 `--codex-oauth` / `--codex-manifest-sha256`，admission核OAuth完整attempt窗口时效，不自动登录或刷新。真正Worker无Install、Restart=no；实际admission通过、配置一致且确认没有待执行任务后才显式start。首次完整admission早于DB import，每claim前复核credential；idle readiness不证明模型或SUT执行，本部署不自动创建模型周期。

## Cloud Web私有HTTPS socket

`HYPERTEST_CLOUD_WEB=enabled`显式加载 `ops/container/compose.cloud.yml`。保持现有origin（当前 `https://155.138.206.106:8080`）、SAN、VPN /32、端口与FORWARDED_ALLOW_IPS；不增加TCP，不伪造XFP。nginx只新增 `/run/hypertest-cloud-web/api.sock ssl`，限Cloud typed路径和只读Project task-directory。Web严格验CA及hostname/IP，唯一transport为UDS。

按 `ops/container/hypertest-cloud-web.tmpfiles.conf` 显式建立socket目录101:10000710；nginx RW、Web RO，目录不混秘密。Web显式1000:1000，部署核真实镜像NSS。公共CA为新0444副本，leaf key仅nginx有。不得扩大parent到0777。必须记录实际api.sock stat，并从Web容器实际严格TLS GET证明可connect；静态Compose不替代实际连接。stack validate核公开CA链/SAN、私有文件服务owner和socket目录。

更新公开compose.env的Cloud路径/开关并render新nginx配置，沿原guarded stack部署，不覆写accepted nginx原件。正常迁移前备份当前库，0023向前升级到head，重启受影响API/Web/nginx；legacy Worker image不主动升级。新Worker与API必须同库、同wrapping identity，不使用Mac env_password/OAuth/SSH key。

## 有限验收和回退

远端执行本次ops测试及原container TLS/deployment测试；Ruff范围限本次工具/stack/tests。API镜像需有crypto而无SDK/runtime；Web完整Node suite、typecheck和build按独立远端计划。Worker实际build/admission保留SHA与日志。先独立临时PG验证迁移和相关API测试，常驻库再向前升级，不能清空旧库。常驻仅readiness、Cloud setup、自有Project草稿管理；不自动dispatch或跑新模型/SUT。

任何archive/unit/CA/NSS/mount/admission拒绝都保留输出与固定错误码，不自动重试未知Task。Cloud故障优先停止新Cloud Worker并关闭Cloud入口/overlay，保留当前schema兼容的API/Web与Local同步。迁移及新增UNBOUND之后，不能默认退回旧API/Web；只有已独立核验兼容当前schema/状态的pinned镜像才可回退。不降级或覆盖DB，不删除runtime/原件，不改旧reported result/UNKNOWN/HELD。本工具不自动安装、enable或后台更新。
