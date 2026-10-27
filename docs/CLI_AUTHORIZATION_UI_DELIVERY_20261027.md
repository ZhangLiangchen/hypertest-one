# CLI 新增项目与授权树交付（2026-10-27）

已为既有 CLI 增加项目授权入口，并将平铺 grant 表改为客户端父节点、项目子节点的折叠列表。绑定完成显示客户端名称与绿色「已绑定」，原大块成功背景已移除，短码、指纹及配对期限收进详情。APPROVED 明确显示「等待 CLI 确认」，与完成绑定区分。

## 行为与边界

- 客户端「添加项目」展开项目选择和中英文授权 Prompt。排除已有有效授权及已删除项目；过期或撤销的项目可重新明确申请。复制失败时展开只读文本供手动复制。
- 本地 Agent 按服务器、client ID、actor ref 精确匹配 active profile，以同 profile 发起本次新项目配对。CLI 复用客户端并在批准、兑换后追加 grant，无需重装。选择项目或复制 Prompt 本身不授予权限，用户仍须核对短码并批准项目、权限和期限。
- 待批准表单读取请求中的 `requested_project_id` 作为初始项目提示，不在刷新时覆盖用户选择。项目提示不能代替批准。
- 树按 client instance ID 与 actor 分组，同名客户端不混并。同一项目的所有 grant、到期/撤销状态、期限及独立撤销/原 key 恢复入口保留。项目有效数按唯一项目计算，不按 grant 条数累加。
- 沿用领域 §56.5 与 TMP §51.4 的既存追加授权合同；没有新 API、数据库迁移或 CLI 包变化。凭据、历史和未决操作保持。

具体操作见[CLI 授权指南](CLI_AUTHORIZATION_GUIDE.md)。

## 定向验证

- `archive-ui`、`archive-operation`、`cli-project-authorization` 共 **14 项通过**：包含中英文状态、请求项目预选、显式短码批准、身份分组、多 grant 历史保留、Prompt 输入校验和原 key 恢复。
- TypeScript 检查、Web 正式构建、差异检查及 UI/CSS 设计静态扫描通过。调试时发现并移除了不符合 Next 页面导出约束的额外组件 export，最终类型检查及构建通过。
- 一轮 1600px PC 浏览器检查通过：中英文、鼠标/空格折叠、项目筛选、复制成功/拒绝回退及 PENDING 预选。全部业务 API 使用合成 fixture，仅 GET，无业务批准/撤销。虚构域名的 dev HMR WebSocket 报错不影响页面功能，未发现产品修补项。
- 截图在工作区 `output/playwright/cli-auth-ui/`；临时浏览器和 loopback dev 已停止。未扩展移动端或全量回归。

## 部署

Web 从已推送 Git `fc9de8665fac15d8b63e92de6b1198ccfd3d1fd9` 的干净复用 checkout 构建，并按固定 ops 更新 Web 容器。

| 组件 | 当前身份 |
| --- | --- |
| Web | `sha256:798c5d809b1eece602cc2819e11b4c07a28bbe6cb64baf937e04376b1d9eb6c2` |
| API | 保持 Git `006100788751a416b0d6f1dbe8d78c96d3155a5f` / `sha256:2fd7d36542f90f4961b87a958e2576cb509db29d48378516df83e39d17045002` |
| schema / 固定 ops | 保持 `0032_cli_archive_uploader` / Git `1512d11f99c5e500e4fc56c685410ffa9e533530` |
| CLI | 保持公开 `cli-v0.1.0`，无需重装 |

五容器 healthy，网络守卫 protected；API health、授权页、CLI grants 读取均 HTTP 200，CLI setup configured。其他容器镜像保持，未重启 API/数据库/Worker 或改动 TLS、CA、SSH/VPN 与数据卷。部署日志和镜像记录在 `/opt/hypertest/container-builds/cli-project-tree-20261027/`。

**USER_OWNED：真实新增项目批准、CLI 兑换与归档验收未执行。** 上述组件与浏览器检查不代表用户业务验收。
