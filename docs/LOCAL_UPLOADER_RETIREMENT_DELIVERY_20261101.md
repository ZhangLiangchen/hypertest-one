# Local 任务上传身份清理（2026-11-01）

## 实现

实现提交 `9face9518a0c8581f85f60e7dcda13f0b73347f7` 清理项目任务列表中的旧上传身份列和客户端查询。任务详情的上传身份管理入口已在此前提交 `45e0c48` 移除，真实归档提交者仍保留在记录中。

新任务和子任务不再指定任务级上传身份；新建任务时显式指定非空 owner、任务级 AUTHORIZE 与旧 actor 列表返回 410。已接受的原 key 仍可精确对账；历史定向授权依旧检查原 owner 和子任务授权，不扩大访问范围。现行 CLI 全项目授权与真实认证上传者保持独立。

## 自测

- 相关 Python 测试最终 88 项通过；其中 87 项在一次运行通过，剩余一项修正测试中已删除的旧列表调用后单独通过。覆盖合成 CLI 配对、全项目授权、任务根空间及子任务归档和完整读回、旧定向授权拒绝和原 key 恢复。
- Web 相关测试 29 项通过；Ruff、文档差异检查和 Web 镜像构建的类型检查通过。临时专用 PostgreSQL 测试容器已删除，未向业务库写入测试数据。

## 本机部署

API 与 WireGuard Web 均运行上述提交。API `hypertest-mac-api:9face95`，镜像 `sha256:48045bf913d2c391792208dc1c9d7c1b40a50203c21ded79a481f6fcecdc437d`；Web `hypertest-mac-web:9face95`，镜像 `sha256:42d206b2b29aa82b3906a38a44b4d0d93559d38d4f620f3dd5bc3a1a0b08a605`。API 镜像基于原 `1b7b3ff` 镜像替换本提交变更的两个应用文件，保留原依赖；两版之间无其他 API 源码、依赖或迁移差异。未执行业务库迁移。

两容器健康，API 健康接口及项目页面 HTTP 200。本机既有 `hypertest-mac` CLI profile 对用户项目的只读 `doctor` 为 READY，显示全项目授权。此检查不表示实际上传已发生。

## USER_OWNED 验收

任务页面显示及其他设备的实际使用体验仍待用户验收。历史仅有项目定向授权的客户端对新任务或新子任务不再获得任务级指定权限，需使用现行有效的全项目 CLI 授权。

## 用户授权的真实 CLI 验证（2026-11-01）

用户明确要求使用现有授权实际验证；选择已有 `cli-validation-20261101` profile，CLI 0.1.2 对 Project `01a181ac-ba63-7c24-b695-bfb498829b63` 的 doctor 返回 READY 和全项目授权。创建标注 SYNTHETIC 的 Local Task `01a195eb-e180-78bd-99c1-1b362d004a89` 和 Subtask `01a195eb-f70e-7e9f-8f3f-9df0e6d76330`，两者任务级 uploader 均为空。

- Task 根空间：request `959ba0eb-f2a6-408e-8fca-379088db6419`，submission `01a195ec-73c7-74fa-8aa8-c0d15ee2e8f4`，ARCHIVED，版本 2，CLI `readback_complete=true`。
- Subtask：request `d6301073-69a2-4c10-8a24-d79eade38513`，submission `01a195ec-84f2-764a-be08-58012a9a9f81`，ARCHIVED，版本 2，CLI `readback_complete=true`。

通过 Web 只读接口按各 submission 获取固定快照，核对 Project、Task、目标类型、Subtask、版本、原文、submission ID、认证上传 actor 和 `NOT_RUN` 均符合预期。两份报告仅含合成标识，未运行 SUT 测试，归档成功不代表 SUT PASS。首次本地执行因 macOS `/var` 符号链接触发清单读取拒绝；该次未发送归档请求，改为同一文件的 `/private/var` 真实路径后完成。
