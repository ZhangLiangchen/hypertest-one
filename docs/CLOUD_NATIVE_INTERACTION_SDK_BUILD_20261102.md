# 宿主 Cloud Worker：SDK 实时提问配对构建（2026-11-02）

宿主 Worker 的实时提问需要独立的 `deepseek-harness-sdk==0.2.2a2` 与同版本 macOS arm64 runtime。它们从官方源码 `ce7073d51254c26cd63b22a60835b8f948deb447` 构建，**不是 PyPI 已发布版本**。旧路径继续使用原固定 0.2.1rc2；新配对单独安装，不能只替换一半。

官方源码的 legacy deploy 会重新解析依赖而偏离 `pnpm-lock.yaml`。[本仓库补丁](../ops/deepseek/native-sdk-locked-deploy.patch) 改用共享锁部署，将每个外部包的 resolution 与原锁逐项比较；保留锁内 integrity 校验。pnpm 对一个文件路径形式的 workspace 脚本未识别原 allowBuild 配置；补丁只手动运行核对过的 `ensure-spawn-helper.mjs`，该脚本仅恢复 node-pty helper 可执行位。不能据此放开其他生命周期脚本。

构建需 Node 24（含头文件）、上游指定的 pnpm 版本及 uv。以明确的临时源码目录执行，先校验完整 Git SHA，再使用 `pnpm install --frozen-lockfile` 和 `git apply --unidiff-zero` 应用上述补丁；运行上游 `pnpm exec tsx scripts/build-exe-for-python-sdk.ts` 和 `scripts/build-python-release.py` 分别构建 macos-arm64 runtime wheel 与 SDK wheel。固定上游文件、补丁、锁、平台和产物摘要随交付记录；不要假定不同构建的 wheel 字节必然相同。

本轮 wheel：runtime SHA-256 `7933e31a641550e65c169bd79bcf9d56a9d1490bcf469ce8ad743c50827a108f`；SDK SHA-256 `953e57ccc77eea412c709373c99f26e647986c1dced4ca707a6d8c440b975492`。正式部署使用前核验摘要与相同版本，按宿主配置安装到独立 Worker 环境，避免替换旧 SDK 的其他使用者。部署镜像、实际宿主环境、启动与用户验收另行记录。

本轮无模型握手和现有 SDK profile 解析通过；官方问答与本地模拟模型计划审阅共 10 项通过。HyperTest 的数据库/Worker 合成链路、实际云端用户验收及真实 SUT 结果分别记录，不由这些测试推断。
