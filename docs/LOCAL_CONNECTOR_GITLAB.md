# 本地 Connector 的受控 GitLab 提单

> **历史或兼容资料：** 本文中的实施计划、配置步骤和部署/验收状态仅适用于所述 profile 与记录时点，不代表当前部署。现行入口见[文档导航](README.md)和[当前 TODO](TODO.md)；新 Local 接入见 [ADR-027](architecture/ADR-027_EXPLICIT_LOCAL_ARTIFACT_ARCHIVE.md)及 [CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)。旧合同、事实和恢复边界按各自范围保留。

ADR-015 保留服务器提单，并增加本地受控执行器。Agent 仍使用 `request_gitlab_issue` / `get_issue`；平台核对同 Run 的 Finding、固定 SHA、可信 Runner Evidence 和责任人策略，先保存创建意图及固定 executor，再派发类型化操作。本地认证只由隔离适配器读取，不写入平台、不交给 Harness。

本实现的数据库、HTTP 注入和账本回归不代表真实 GitLab 验收。真实创建必须在操作者明确批准的 GitLab 项目及负责人上单独验证。

## 配置

先按 Connector 运维流程配对设备，取得稳定 `node_id`。为该设备、HyperTest Project 单独授予 `issue_executor` capability，其 `constraints` 必须与平台策略一致：

```json
{
  "integration_id": "work-gitlab",
  "base_url": "https://gitlab.example.com",
  "gitlab_project_id": 42,
  "assignee_ids": [7]
}
```

平台 Worker 的 `HYPERTEST_GITLAB_POLICY_FILE` 指向现有 v1 策略文件。以 HyperTest Project UUID 为键；这里的 `project_id: 42` 是 GitLab 的数值项目 ID。以下 UUID 是占位值，部署时替换成实际已登记的设备和项目。

```json
{
  "version": "hypertest.gitlab-policy/v1",
  "projects": {
    "00000000-0000-0000-0000-000000000001": {
      "base_url": "https://gitlab.example.com",
      "project_id": 42,
      "assignees": {"responsible-developer": 7},
      "allow_create": true,
      "executor_mode": "LOCAL_CONNECTOR",
      "executor_node_id": "00000000-0000-0000-0000-000000000002",
      "integration_id": "work-gitlab"
    }
  }
}
```

本地模式不允许平台策略包含 `token_file`。服务器模式仍默认 `SERVER_HOST`，使用原来的服务器绝对路径 `token_file`，不填写 `executor_node_id`。新操作会固定选择的执行器；修改策略不会迁移已有操作或产生第二次创建。

在本地 Connector 配置加入：

```json
{
  "issues": {
    "integrations": {
      "work-gitlab": {
        "base_url": "https://gitlab.example.com",
        "gitlab_project_id": 42,
        "assignee_ids": [7],
        "credential_kind": "glab"
      }
    }
  }
}
```

`glab` 模式通过固定的 `glab api` 调用复用本机已有登录。先用本机 CLI 确认能读取批准项目，浏览器登录不足以证明 API 可用。Connector 不导出或上传 glab 的 token，不加载个人 MCP 工具。`glab` 适配器要求 GitLab 安装在域名根路径；带路径前缀的安装应使用以下 API 认证方式。

也可使用 `credential_kind: "token_file"`，同时设置仅本机可读的绝对路径 `token_file`（常规文件、非符号链接、权限 `0600`）；或使用 `credential_kind: "environment"`，指定 `environment_name: "GITLAB_TOKEN"` / `"GLAB_TOKEN"`，复用本机进程环境已有凭据。这些选项只写在本地 Connector 配置，凭据内容不放入 JSON、平台策略、请求或报告。Provider 的环境白名单排除了这些 GitLab 环境变量。

`LocalIssueAdapter.probe()` 可以只读检查批准项目是否实际可访问、是否启用 Issues；它不证明具备创建或指派权限。真实写权限须通过批准的创建验收。

## 不确定结果和断线

服务器对每个 operation 只允许一个 `issue_create` mailbox 记录，先持久化 `SENT` 再发送，断线后不重投。适配器在 `state_dir/issues.sqlite3` 先持久记录 `UNKNOWN`，再执行一次 POST；相同 operation/digest 返回已有账本状态，不同输入拒绝。请保留该文件及服务器 operation 历史，不能通过删除文件、换幂等键、改节点或改模式请求重建。

POST 超时、ACK 丢失或响应无法核验时保持 `UNKNOWN`。后续只向固定原执行器派发 `issue_query`，按原 correlation marker 查询。找不到或找到多条匹配均保持未知，不自动再次 POST；本地账本丢失也只能查询。项目、Issue IID、HTTPS URL、marker、负责人和 delegation digest 均通过受控响应核对后才登记成功。成功提单不确认/解决 Finding，也不改变 Gate。

运行中的 Agent 可用 `get_issue` 对账。Run 已取消、旧 epoch 或设备执行授权已撤销时，操作者可使用单独的管理接口：

```text
GET  /api/v1/gitlab-issue-operations/{operation_id}
POST /api/v1/gitlab-issue-operations/{operation_id}/reconcile
Header: X-HyperTest-Operator-Key
```

管理对账只读取固定旧操作，并将经认证核验的结果写入该 operation 的历史及 Audit/Outbox；它不恢复 Job、不推进 Run、不改变 Finding。原设备重新连接后可接收此精确查询；撤权不能回滚已经发出的外部副作用。原本地认证不可用或来源无法核验时继续保留未知，交由操作者检查真实项目。

## 真实验收

准备一个明确批准创建测试问题单的 GitLab 项目、真实负责人映射、本机可用的 glab/API 授权，以及已产生可信 Runner Evidence 的接受 Finding。首次请求应创建且指派一个真实 Issue，平台应保存可访问的真实链接；重复相同逻辑请求、切换幂等键和重连均只能关联该 Issue。随后验证 ACK 丢失/POST 超时、Connector 重启、账本丢失、设备撤销及取消后管理对账；统计真实项目中的 marker，确认每个 operation 最多一条 Issue。不要把注入 HTTP 返回或本地模拟项目计为这项验收。
