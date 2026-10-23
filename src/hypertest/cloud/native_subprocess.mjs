// Only the public official subprocess seam is adapted. The official Codex
// provider, JSON-RPC lifecycle, answer selection and process ownership stay intact.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const name = 'hypertest-native-subprocess';
export const inject = ['pluginPackages'];

const node = '/opt/hypertest-delegates/bin/node';
const codex = '/opt/hypertest-delegates/node_modules/@openai/codex/bin/codex.js';

export async function apply(ctx) {
  // This file is outside the profile tree. Bare imports here have no SEA
  // fallback; resolve from the actual profile through its public package API
  // instead of assuming a separate copy exists in /app/node_modules.
  const pkg = ctx.pluginPackages.packageOf('@deepseek-ai/dsh-subprocess-local', ctx.baseUrl);
  if (pkg?.name !== '@deepseek-ai/dsh-subprocess-local' || pkg.version !== '0.2.1-rc.2') {
    throw new Error('Pinned subprocess package unavailable');
  }
  const { LocalSubprocessRuntime } = await import(pathToFileURL(resolve(pkg.dir, 'lib/index.js')).href);
  class CloudNativeSubprocess extends LocalSubprocessRuntime {
    cloudNativeCodexShim = true;
    spawn(spec) {
      // The wheel's SEA executable is not a general Node script interpreter.
      // Remap only the exact pinned official wrapper's fixed app-server command.
      if (spec.argv.length === 4 && spec.argv[0] === process.execPath
          && spec.argv[1] === codex && spec.argv[2] === 'app-server'
          && spec.argv[3] === '--stdio') {
        return super.spawn({ ...spec, argv: [node, ...spec.argv.slice(1)] });
      }
      return super.spawn(spec);
    }
  }
  await ctx.plugin(CloudNativeSubprocess);
}
