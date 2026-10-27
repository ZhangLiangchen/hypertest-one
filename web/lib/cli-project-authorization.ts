import type { CliGrant } from "./cli-authorization";

export type CliClientGroup = {
  key: string;
  client_instance_id: string;
  actor_ref: string;
  client_name: string;
  projects: { project_id: string; grants: CliGrant[] }[];
};

/** A display name is not an identity; retain every grant within each project. */
export function groupCliGrants(grants: CliGrant[]): CliClientGroup[] {
  const clients = new Map<string, CliClientGroup>();
  for (const grant of grants) {
    const key = JSON.stringify([grant.client_instance_id, grant.actor_ref]);
    let client = clients.get(key);
    if (!client) {
      client = { key, client_instance_id: grant.client_instance_id, actor_ref: grant.actor_ref, client_name: grant.client_name, projects: [] };
      clients.set(key, client);
    }
    let project = client.projects.find((item) => item.project_id === grant.project_id);
    if (!project) {
      project = { project_id: grant.project_id, grants: [] };
      client.projects.push(project);
    }
    project.grants.push(grant);
  }
  return [...clients.values()];
}

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
type PromptOptions = { server: string; clientInstanceId: string; actorRef: string; projectId: string; locale: "zh" | "en" };

/** Only public, validated identifiers enter this prompt. No default profile is assumed. */
export function cliProjectAuthorizationPrompt({ server, clientInstanceId, actorRef, projectId, locale }: PromptOptions): string {
  if (!uuid.test(clientInstanceId) || !uuid.test(projectId) || !actorRef.startsWith("interactive:") || !uuid.test(actorRef.slice(12))) {
    throw new Error("CLI_PROJECT_CONTEXT_INVALID");
  }
  let parsed: URL;
  try { parsed = new URL(server); } catch { throw new Error("CLI_PROJECT_SERVER_INVALID"); }
  if (/\s/.test(server) || parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash
    || !/^(?:[a-z0-9.-]+|\[[a-f0-9:]+\])$/i.test(parsed.hostname)
    || (server !== parsed.origin && server !== `${parsed.origin}/`)) throw new Error("CLI_PROJECT_SERVER_INVALID");
  const context = `server: ${parsed.origin}\nclient_id: ${clientInstanceId}\nactor_ref: ${actorRef}\nproject_id: ${projectId}`;
  const bind = `hypertest auth bind --server '${parsed.origin}' --profile 'MATCHED_PROFILE' --project-id '${projectId}' --wait-seconds 0 --json`;
  const doctor = `hypertest doctor --profile 'MATCHED_PROFILE' --project-id '${projectId}' --json`;
  if (locale === "en") return `Add access to one project for my existing HyperTest CLI on its original local machine. This is an explicit new authorization intent. Keep the existing installation, identity, project grants, credentials and pending records.

Match these public identifiers exactly (Web client_instance_id is CLI client_id):
${context}

1. Run hypertest profile show --json. Match an active profile by all three fields: server, client_id and actor_ref. Do not read private credential files or match by hostname alone. If no active profile matches, stop and report that I need the original client/profile; do not create or reactivate a profile. If multiple profiles match, ask me which to use. Preserve existing CA settings, including SSL_CERT_FILE; keep TLS verification enabled.
2. Check your conversation and known pairing records for this same project-addition intent. Resume its original request if already started. For a genuinely new intent, replace MATCHED_PROFILE below with the matched profile name, safely shell-quoted, and run once:
${bind}
3. Show the authorization URL, short code and original request_id. I must match the short code and approve only the selected project, archive:read/archive:write and expiry on the Web page. A project hint is not permission. Do not approve for me or request an Operator key. PENDING / exit 4 is a normal wait for approval.
4. After I approve, continue the original request with hypertest auth bind --resume --request-id ORIGINAL_REQUEST_ID --wait-seconds 0 --json. For UNKNOWN, lost responses or NOT_FOUND, use hypertest auth reconcile --request-id ORIGINAL_REQUEST_ID --json and query only the original key; never create another request to retry an uncertain operation. On identity conflict, stop without overwriting or changing profile.
5. Once BOUND and saved, verify the same profile identity and retained grants with hypertest profile show --json, then run (replace MATCHED_PROFILE):
${doctor}
Report the added project and result. Do not reinstall, log out, revoke old grants, install MCP/Hooks, create tasks or upload artifacts during authorization.
`;
  return `请在原本已绑定的本机上，为我的既有 HyperTest CLI 新增一个项目的权限。这是一次明确的新授权意图。保留现有安装、身份、项目授权、凭据和未决记录。

请精确匹配以下非秘密标识（网页 client_instance_id 对应 CLI 的 client_id）：
${context}

1. 执行 hypertest profile show --json，按 server、client_id、actor_ref 三项匹配处于 active 状态的既有 profile。不要读取私有凭据文件，不要仅凭主机名称匹配。没有匹配的 active profile 时停止，说明需要在原客户端/原 profile 操作，不要新建或重新启用 profile；有多个匹配项时请我选择。沿用现有受信 CA 配置，包括 SSL_CERT_FILE，保持 TLS 校验开启。
2. 检查对话与已知配对记录中是否已启动本次新增项目授权；若已启动，只继续原请求。确认为新的授权意图时，将下方 MATCHED_PROFILE 替换为匹配的 profile 名称并安全地进行 shell 引用，只执行一次：
${bind}
3. 展示授权链接、短码和原 request_id。由我在网页核对短码，仅批准所选项目、archive:read/archive:write 及有效期。项目预选不是授权，不要代我批准或索取 Operator key。PENDING / 退出码 4 是正常等待批准。
4. 我批准后，用 hypertest auth bind --resume --request-id ORIGINAL_REQUEST_ID --wait-seconds 0 --json 继续原请求，将 ORIGINAL_REQUEST_ID 替换为原 request_id。遇到 UNKNOWN、失答或 NOT_FOUND，只用 hypertest auth reconcile --request-id ORIGINAL_REQUEST_ID --json 查询原 key，不要新建请求重试未知操作。遇到身份冲突停止，不覆盖或切换 profile。
5. BOUND 且保存成功后，用 hypertest profile show --json 核对仍为原身份且旧授权保留，再执行（替换 MATCHED_PROFILE）：
${doctor}
报告新增项目和结果。授权过程中不要重新安装、logout、撤销旧授权、安装 MCP/Hooks、创建测试任务或上传产物。
`;
}
