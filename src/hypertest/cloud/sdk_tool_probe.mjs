// Dedicated keyless diagnostic only: real published Agent + public ToolsService.
// No model prompt, policy override, custom Session event, auth or arbitrary argv.
import { writeFileSync } from 'node:fs';

export const name = 'hypertest-sdk-tool-probe';
export const inject = ['tools', 'agents', 'permissionPresets'];
const codes = new Set(['SANDBOX_UNAVAILABLE', 'UNKNOWN_TOOL', 'INVALID_TOOL_OUTPUT', 'ABORTED', 'ABORTED_BEFORE_DISPATCH']);
const marker = 'hypertest-sdk-tool-probe-v1\n';

export function apply(ctx, config) {
  if (!/^tool-probe-[a-f0-9]{32}$/.test(config?.sessionId)) throw new Error('Invalid fixed probe session');
  let executed = false;
  ctx.on('agent/created', async ({ agent }) => {
    if (agent.id !== config.sessionId || executed) return;
    executed = true;
    const observed = { profile: 'hypertest-sdk-tool-probe/v1', tool_registered: false,
      executed: false, is_error: null, marker_match: false, error_code: 'OTHER',
      sandbox_mode: 'OTHER', approval_policy: 'OTHER' };
    try {
      const permissions = ctx.permissionPresets.resolve(ctx.permissionPresets.current(agent.session));
      if (['workspace-write', 'read-only', 'danger-full-access'].includes(permissions.sandbox)) observed.sandbox_mode = permissions.sandbox;
      if (['ask', 'never'].includes(permissions.approval)) observed.approval_policy = permissions.approval;
      observed.tool_registered = ctx.tools.get('bash') !== undefined;
      if (observed.tool_registered) {
        observed.executed = true;
        const result = await ctx.tools.execute({ agent, callId: 'hypertest-fixed-printf', name: 'bash',
          signal: AbortSignal.timeout(8000), arguments: {
            command: "printf '%s\\n' 'hypertest-sdk-tool-probe-v1'", description: 'Print fixed keyless capability marker',
            workdir: '/workspace', timeoutMs: 5000 } });
        observed.is_error = typeof result.isError === 'boolean' ? result.isError : null;
        observed.error_code = result.isError === false ? 'NONE' : (codes.has(result.error?.info?.code) ? result.error.info.code : 'OTHER');
        observed.marker_match = result.isError === false && result.value?.stdout?.text === marker && result.value?.exitCode === 0;
      } else observed.error_code = 'UNKNOWN_TOOL';
    } catch (error) {
      observed.is_error = true;
      observed.error_code = codes.has(error?.code) ? error.code : 'OTHER';
    }
    writeFileSync('/workspace/.hypertest-sdk-tool-probe.json', JSON.stringify(observed), { flag: 'wx', mode: 0o600 });
  });
}
