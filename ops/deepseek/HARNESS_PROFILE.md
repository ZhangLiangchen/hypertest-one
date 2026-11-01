# 云端 Harness SDK 原生配置

云端使用独立 Docker volume 保存 DeepSeek Harness 的 `sdk` profile。Worker 以只读方式挂载该 volume，并在每个新 Attempt 中复制 `profiles/sdk`（含插件包树）到独立的可写 `DSH_HOME`。不会复制个人 `~/.dsh`、根目录凭据文件或其他会话；已运行的 Attempt 不因后续编辑改变。当前只接通 `deepseek-official` 模型 provider 的既有受限 host relay，其他 provider 会明确拒绝。默认 profile 不预装或默认启用 Ralph、Agent Teams 等插件；其安装和实际能力需要单独验证。

## 创建管理镜像和专用 volume

以下命令需在提供 Docker 的云端宿主运行。`WORKER_IMAGE` 必须指向本次固定提交构建的 Cloud Worker 镜像；`PNPM_DIR` 指向本机已安装的官方 pnpm 包目录（包含 `bin/pnpm.cjs`），可复用现有可信安装。构建使用既有 Node 镜像并复制该目录，不把 pnpm 目录提交仓库，也不会在每个测试任务安装依赖。

```sh
export WORKER_IMAGE='hypertest-mac-cloud-worker:<commit>'
export PNPM_DIR='/absolute/path/to/node_modules/pnpm'
export HYPERTEST_CLOUD_HARNESS_VOLUME='hypertest-cloud-harness-profile'
export HYPERTEST_CLOUD_HARNESS_CLI_IMAGE='hypertest-cloud-harness-cli:<commit>'

docker build -f ops/deepseek/Dockerfile.harness-profile \
  --build-arg WORKER_IMAGE="$WORKER_IMAGE" --build-context "pnpm=$PNPM_DIR" \
  -t "$HYPERTEST_CLOUD_HARNESS_CLI_IMAGE" .
docker volume create "$HYPERTEST_CLOUD_HARNESS_VOLUME"
docker run --rm --network none --user 0 --entrypoint /bin/sh \
  --mount "type=volume,source=$HYPERTEST_CLOUD_HARNESS_VOLUME,destination=/var/lib/hypertest-cloud/harness" \
  "$HYPERTEST_CLOUD_HARNESS_CLI_IMAGE" \
  -c 'chown 997:988 /var/lib/hypertest-cloud/harness && chmod 700 /var/lib/hypertest-cloud/harness'
```

上述初始化只适用于新建的专用 volume；不要对现有其他数据卷运行。使用 [Compose 模板](compose.cloud-worker.yml) 时，将同一 volume 以只读方式挂载至 `/var/lib/hypertest-cloud/harness`；`docker-service.json` 的期望挂载列表必须包含该精确 volume、目标路径和 `writable: false`，示例见 [docker-service.json.example](docker-service.json.example)。修改后仍须通过 Worker 服务准入，配置文件本身不证明服务已部署或可以执行。

## 配置模型和插件

启动官方 CLI 时 `DSH_HOME` 指向该 volume，且显式选择 `sdk` profile。查看默认配置或交互式编辑 Harness 原生 patch：

```sh
ops/deepseek/harness-profile --profile sdk --dump-default-config > /dev/null
VISUAL=vi ops/deepseek/harness-profile edit-sdk-patch
```

编辑器由宿主调用；指定 `VISUAL` 或 `EDITOR` 为单个可执行程序路径。文件经私有临时文件编辑，以原始摘要检查并原子替换，编辑过程中请勿并发运行其他 profile 写操作。示例值仅为说明，实际选择以云端账号可用的模型和该版本 Harness 为准：

```yaml
- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-v4-pro
    reasoningEffort: max
```

不要把 API key、OAuth 或其他秘密写进 patch。此 patch 与其他 SDK 插件配置同属 Harness 自身的 profile；需要保留既有行。`--dump-config` 输出的是完整组合配置，**可能包含敏感信息**：仅在受信环境中查看，不要写入日志、Git 或分享。插件可通过官方命令按需安装，例如 `ops/deepseek/harness-profile plugin --profile sdk add <trusted-package>`；安装可能访问网络及包注册表，只在操作者显式调用时发生。Worker 不会替用户安装或默认启用插件。插件在云端隔离网络、可执行文件和凭据范围内的实际可用性须分别验证。

当前模型服务密钥仍由原有宿主 broker 管理，不进入 profile。SDK 初始化使用 profile 实际声明的 provider、model 和可选推理档位；租约心跳、工作区隔离、停止与受限网络仍由 Worker 管理。新任务不生成 HyperTest 任务预算或请求次数上限；旧任务与未知操作按原合同处理。
