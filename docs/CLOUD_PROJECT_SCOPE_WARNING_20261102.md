# 云端仓库与项目范围提示修正（2026-11-02）

## 实现

Cloud 任务创建页按项目范围与仓库的地址层级判断提示，不再仅对两段地址逐字比较。同一仓库的 `.git` 后缀、尾斜杠及支持的 HTTPS/SSH 写法可比较；GitLab `/groups/` 项目组及其他项目范围按完整路径段匹配子仓库，避免相似前缀误判。明确以 `.git` 结尾的仓库地址不作为父范围。

比较是本地地址判断，不证明远端权限或仓库存在。项目资料、Cloud 资源修订、已有任务和冻结版本均不因本次修改而写入或迁移。用户澄清了项目组与任务仓库的上下级关系，本轮没有实施此前讨论的仓库地址合并。

## 自测与部署

- 源码提交并推送 `6d83d37a89363ccfd436f01fcfd0b8f613b8e48c`。关联 Web 测试 35 项通过、类型检查通过、Web 生产构建通过。
- Web 镜像 `hypertest-mac-web:6d83d37` / `sha256:5fb4ed4fd028904a48cb712fd3edadb8490159712fa6ab363edadb780b78d7fa`，revision 为上述提交；容器 healthy。API 保持 `hypertest-mac-api:dafffd5` 并健康。本机新的 Web-only Compose overlay 为 `~/.local/share/hypertest-mac/web-6d83d37.compose.json`，应与已有 Worker/BFF overlay 一起使用。
- 在用户所给项目的云端创建页进行只读页面检查：显示现有被测仓库与测试框架地址，原差异提示不再出现；未填写或创建任务。此前 GitLab 只读核对显示被测仓库位于 xblock 组下，框架仓库在个人命名空间。
- 用户功能验收由用户自行确认；本轮未调用模型、运行被测系统或修改业务数据。
