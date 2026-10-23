// Official lifecycle plugin, metadata only. No custom session/log event, SDK
// wire extension, provider loop, task text, answer or credential processing.
import { accessSync, constants, readFileSync } from 'node:fs';
import { createConnection } from 'node:net';

export const name = 'hypertest-native-delegation-observer';
// The observer must remain available when a native capability fails to load.
// Hard-injecting that failed service would leave this diagnostic plugin pending
// and hide the specific missing capability behind a generic READY timeout.
export const inject = ['loader'];
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const reasons = new Set(['completed', 'error', 'aborted', 'max-tokens', 'refusal']);

export function apply(ctx) {
  let sequence = 0;
  let ready = false;
  let chain = Promise.resolve();
  function send(kind, data) {
    const frame = JSON.stringify({ sequence: ++sequence, kind, data }) + '\n';
    chain = chain.then(() => new Promise((resolve, reject) => {
      const socket = createConnection('/run/delegation-observer.sock');
      socket.setTimeout(3000, () => socket.destroy(new Error('Native metadata timeout')));
      socket.once('connect', () => socket.write(frame));
      let ack = '';
      socket.on('data', chunk => {
        ack += chunk.toString('utf8');
        if (ack === 'ACK\n') { socket.end(); resolve(); }
        else if (ack.length > 4) socket.destroy(new Error('Native metadata acknowledgment invalid'));
      });
      socket.once('error', reject);
      socket.once('end', () => { if (ack !== 'ACK\n') reject(new Error('Native metadata acknowledgment missing')); });
    }));
    return chain;
  }
  ctx.on('session/created', () => {
    if (ready) return;
    accessSync('/opt/hypertest-delegates/bin/node', constants.X_OK);
    const product = JSON.parse(readFileSync('/opt/hypertest-delegates/node_modules/@openai/codex/package.json', 'utf8'));
    const bundle = JSON.parse(readFileSync('/opt/hypertest-delegates/node_modules/@deepseek-ai/dsh-subagent-codex/package.json', 'utf8'));
    if (product.version !== '0.153.4' || bundle.version !== '0.2.1-rc.2') throw new Error('Native payload version mismatch');
    const subagents = ctx.get('subagents');
    const tools = ctx.get('tools');
    const subprocess = ctx.get('subprocess');
    ready = true;
    return send('READY', {
      profile: 'hypertest-native-codex-profile/v1', codex_version: product.version,
      bundle_version: bundle.version, provider_registered: subagents !== undefined && subagents.getProvider('codex') !== undefined,
      tool_registered: tools !== undefined && tools.schemas().some(tool => tool.name === 'subagent_codex'),
      subprocess_shim: subprocess?.cloudNativeCodexShim === true, node_available: true,
      model_started: false,
    });
  });
  function record(info, state) {
    if (info.local !== false || info.provider !== 'codex') return;
    if (!uuid.test(info.runId) || !uuid.test(info.id)) throw new Error('Invalid delegate lifecycle identity');
    const reason = state === 'RUNNING' ? null : (reasons.has(info.stopReason) ? info.stopReason : 'error');
    return send('DELEGATION', {
      profile: 'hypertest-native-delegation-observation/v1', run_id: info.runId,
      native_ref: info.id, provider: 'codex', state, stop_reason: reason,
    });
  }
  ctx.on('subagent/start', info => record(info, 'RUNNING'));
  ctx.on('subagent/end', info => record(info, 'TERMINAL'));
  ctx.effect(() => () => send('CLOSED', null));
}
