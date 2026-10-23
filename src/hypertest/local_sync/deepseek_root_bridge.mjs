/** HyperTest Local adapter for the DeepSeek Harness 0.1.5-rc.1 registry API.
 * Native event observations are reduced before any child process or file write.
 * No chat, reasoning, raw tool payload, platform token, or model credential is read.
 */
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { isAbsolute } from 'node:path';

export const name = 'hypertest-local-root-events';
export const inject = ['agents'];

function validCommand(argv) {
  return Array.isArray(argv) && argv.length === 7 && argv.every(value => typeof value === 'string')
    && isAbsolute(argv[0]) && argv[1] === '-I' && argv[2] === '-m' && argv[3] === 'hypertest.local_sync'
    && argv[4] === 'hook' && argv[5] === '--config' && isAbsolute(argv[6]);
}

export async function apply(ctx, config) {
  if (!validCommand(config.handlerCommand) || !isAbsolute(config.workspace)
      || !isAbsolute(config.createMessageModule) || typeof ctx.agents.roots !== 'function'
      || typeof ctx.agents.get !== 'function') {
    ctx.logger.warn('HYPERTEST_DEEPSEEK_ROOT_BRIDGE_CONFIGURATION_REJECTED');
    return;
  }
  const { createUserMessage } = await import(pathToFileURL(config.createMessageModule).href);
  const starts = new WeakMap();
  const contextsDelivered = new WeakSet();
  const live = new Set();
  let disposed = false;

  function root(agent) {
    if (!agent || ctx.agents.get(agent.id) !== agent || !ctx.agents.roots().includes(agent)) return false;
    const header = agent.session?.header;
    return header && header.id === agent.id && header.cwd === config.workspace
      && header.parentSession === undefined && header.origin !== 'subagent';
  }

  function metadata(agent, event, toolName) {
    const value = { session_id: agent.session.header.id, hook_event_name: event, cwd: config.workspace };
    if (typeof toolName === 'string' && toolName.length <= 256) value.tool_name = toolName;
    return value;
  }

  function invoke(event) {
    if (disposed) return Promise.resolve(undefined);
    const env = {};
    for (const key of ['PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR']) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    return new Promise(resolve => {
      const child = spawn(config.handlerCommand[0], config.handlerCommand.slice(1), {
        cwd: config.workspace, env, shell: false, stdio: ['pipe', 'pipe', 'ignore'],
      });
      live.add(child);
      let output = '', oversized = false, settled = false;
      const finish = code => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        live.delete(child);
        if (code !== 0 || oversized) { resolve(undefined); return; }
        if (event.hook_event_name !== 'SessionStart' || !output.trim()) { resolve(undefined); return; }
        try {
          const block = JSON.parse(output).hookSpecificOutput;
          const context = block?.hookEventName === 'SessionStart' ? block.additionalContext : undefined;
          resolve(typeof context === 'string' && context.length <= 16384 ? context : undefined);
        } catch { resolve(undefined); }
      };
      const timer = setTimeout(() => { child.kill('SIGKILL'); finish(null); }, 15000);
      child.stdout.on('data', data => {
        if (oversized) return;
        output += data.toString('utf8');
        if (Buffer.byteLength(output, 'utf8') > 65536) { oversized = true; output = ''; child.kill('SIGKILL'); }
      });
      child.stdin.on('error', () => {});
      child.once('error', () => finish(null));
      child.once('close', finish);
      child.stdin.end(JSON.stringify(event));
    });
  }

  ctx.on('agent/session-start', ({ agent }) => {
    if (!root(agent) || starts.has(agent)) return;
    // This promise exists only after the actual native lifecycle event. The
    // pre-step gate below never invents a missing SessionStart or a session ID.
    starts.set(agent, invoke(metadata(agent, 'SessionStart')));
  });

  ctx.on('agent/pre-step', async ({ agent, messages }, next) => {
    if (!root(agent) || !starts.has(agent) || !Array.isArray(messages) || messages.length === 0) return next();
    const context = await starts.get(agent);
    const decision = await next();
    if (!context || contextsDelivered.has(agent) || decision?.kind !== 'enter') return decision;
    contextsDelivered.add(agent);
    const message = createUserMessage({
      content: [{ type: 'text', text: context }],
      source: { kind: 'plugin', plugin: name },
    });
    return { ...decision, messages: [...decision.messages, message] };
  });

  ctx.on('tools/post-execute', async (exec, result, next) => {
    // Do not inspect or persist arguments, result, output, or child session text.
    if (root(exec.agent) && starts.has(exec.agent)) {
      await starts.get(exec.agent);
      await invoke(metadata(exec.agent, 'PostToolUse', exec.name));
    }
    return next();
  });

  ctx.on('agent/turn-stopping', async ({ agent }) => {
    if (!root(agent) || !starts.has(agent)) return;
    await starts.get(agent);
    await invoke(metadata(agent, 'Stop'));
  });

  ctx.effect(() => async () => {
    disposed = true;
    for (const child of live) child.kill('SIGKILL');
  }, 'hypertest-local-root-events: stop bounded metadata handlers');
}
