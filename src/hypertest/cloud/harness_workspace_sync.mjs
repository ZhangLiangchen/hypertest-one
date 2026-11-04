/**
 * Group SDK sessions in the existing Harness host, which alone owns the native
 * workspace registry. Listing session headers does not restore an Agent or
 * read its conversation. Install this in the Web/desktop host, never in each
 * independent SDK process.
 */
import {lstat, readFile, readdir, realpath, stat} from "node:fs/promises";
import {createHash} from "node:crypto";
import {dirname, isAbsolute, join, resolve} from "node:path";

export const name = "hypertest-framework-workspaces";
export const inject = ["workspaceRegistry", "sessionPersistence"];

export async function frameworkProjects(config) {
  if ((!Array.isArray(config?.projects) || config.projects.length === 0) && !config?.managedRoot) {
    throw new TypeError("Framework workspace projects are required");
  }
  if (config.managedRoot !== undefined && (typeof config.managedRoot !== "string" ||
      !isAbsolute(config.managedRoot) || resolve(config.managedRoot) !== config.managedRoot)) {
    throw new TypeError("Managed framework root must be an absolute canonical path");
  }
  if (config.projects !== undefined && !Array.isArray(config.projects)) {
    throw new TypeError("Framework workspace projects must be an array");
  }
  const configured = config.projects ?? [];
  const discovered = config.managedRoot ? await managedProjects(config.managedRoot) : [];
  if (configured.length + discovered.length > 256) throw new TypeError("Too many framework workspaces");
  const projects = [];
  const paths = new Set();
  for (const project of [...configured, ...discovered]) {
    if (typeof project?.path !== "string" || !isAbsolute(project.path) ||
        typeof project.title !== "string" || !project.title.trim()) {
      throw new TypeError("Framework workspace path and title are required");
    }
    const path = await realpath(project.path);
    if (path !== project.path || !(await stat(path)).isDirectory() || paths.has(path)) {
      throw new TypeError("Framework workspace paths must be unique canonical directories");
    }
    paths.add(path);
    projects.push({path, title: project.title.trim()});
  }
  return projects;
}

async function managedProjects(root) {
  try {
    if (await realpath(root) !== root || !(await stat(root)).isDirectory()) {
      throw new TypeError("Managed framework root must be a canonical directory");
    }
  } catch (error) {
    // The Worker may not have prepared its first framework yet.
    if (error.code === "ENOENT") return [];
    throw error;
  }
  const entries = (await readdir(root, {withFileTypes: true}))
    .filter(entry => entry.isDirectory() && /^[a-f0-9]{64}$/.test(entry.name));
  if (entries.length > 256) throw new TypeError("Too many managed framework workspaces");
  const projects = [];
  for (const entry of entries) {
    const directory = join(root, entry.name);
    const recordPath = join(directory, "project.json");
    let metadata;
    try { metadata = await lstat(recordPath); }
    catch (error) {
      if (error.code === "ENOENT") continue;
      throw error;
    }
    if (!metadata.isFile() || metadata.size > 8192) throw new TypeError("Invalid managed framework record");
    const record = JSON.parse(await readFile(recordPath, "utf8"));
    if (record.profile !== "hypertest-framework-project/v1" ||
        typeof record.path !== "string" || dirname(record.path) !== directory) {
      throw new TypeError("Invalid managed framework project");
    }
    projects.push({path: record.path, title: record.title});
  }
  return projects;
}

// These narrow internal methods are pinned to the audited 0.2.2-alpha.2
// workspace implementation. They affect membership only, never Session state.
const LEGACY_METHODS = {
  candidateMatches: "6c93354c2db14ce1035cd2e2f59778100f1c5661e8dafb04aec700cac5874dda",
  mutate: "93b1e227bc7dd8ec86487054443d5f386ccdfcb299f4caa13038b78f776ee05c",
  detachSession: "4d56d0a0fc886e33468528e8a8badde04771cc328168fdb4b4bbc35fbe91e6d7",
};

function requireMethod(method, name) {
  if (typeof method !== "function" || createHash("sha256")
    .update(Function.prototype.toString.call(method).replace(/\s+/g, ""))
    .digest("hex") !== LEGACY_METHODS[name]) {
    throw new TypeError("Unsupported native workspace membership implementation");
  }
}

export function legacyMemberships(configured, projects, snapshots) {
  if (!Array.isArray(configured) || configured.length > 4096) {
    throw new TypeError("Invalid legacy workspace memberships");
  }
  const paths = new Set(projects.map(project => project.path));
  const headers = new Map();
  for (const {header} of snapshots) {
    if (!header || typeof header.id !== "string" || headers.has(header.id)) {
      throw new TypeError("Ambiguous native session headers");
    }
    headers.set(header.id, header);
  }
  const members = new Map();
  for (const row of configured) {
    if (typeof row?.sessionId !== "string" || !row.sessionId || row.sessionId.length > 255 ||
        typeof row.originCwd !== "string" || !isAbsolute(row.originCwd) ||
        resolve(row.originCwd) !== row.originCwd || !paths.has(row.projectPath) ||
        members.has(row.sessionId) || headers.get(row.sessionId)?.cwd !== row.originCwd) {
      throw new TypeError("Legacy session membership does not match its original header");
    }
    members.set(row.sessionId, {projectPath: row.projectPath, originCwd: row.originCwd});
  }
  // Native parentSession links, not titles or ID spelling, define descendants.
  let added;
  do {
    added = false;
    for (const header of headers.values()) {
      const parent = members.get(header.parentSession);
      if (!parent) continue;
      const current = members.get(header.id);
      if (header.parentSession === header.id || typeof header.cwd !== "string" ||
          (current && current.projectPath !== parent.projectPath)) {
        throw new TypeError("Conflicting native child workspace membership");
      }
      if (!current) {
        members.set(header.id, {projectPath: parent.projectPath, originCwd: header.cwd});
        added = true;
      }
    }
  } while (added);
  return members;
}

export function legacyGrouping(ctx, configured) {
  let members = new Map();
  let original;
  let replacement;
  let published = false;
  const registry = ctx.workspaceRegistry;
  return {
    contains: id => members.has(id),
    dispose() {
      if (replacement && registry.host.candidateMatches === replacement) {
        registry.host.candidateMatches = original;
      }
      members.clear();
    },
    async sync(projects, snapshots, signal) {
      let next;
      try { next = legacyMemberships(configured, projects, snapshots); }
      catch (error) { members.clear(); throw error; }
      if (!replacement) {
        requireMethod(registry.host?.candidateMatches, "candidateMatches");
        original = registry.host.candidateMatches;
      } else if (registry.host.candidateMatches !== replacement) {
        throw new TypeError("Native workspace matcher changed after installation");
      }
      const workspaces = [];
      for (const project of projects) {
        signal.throwIfAborted();
        workspaces.push(await registry.create(project.path, project.title));
      }
      // Validate every entity before changing either the matcher or membership.
      const all = registry.list();
      for (const workspace of all) {
        requireMethod(workspace.mutate, "mutate");
        requireMethod(workspace.detachSession, "detachSession");
        if (!Array.isArray(workspace.record?.sessionIds) || workspace.record.path !== workspace.path) {
          throw new TypeError("Unsupported native workspace membership record");
        }
      }
      members = next;
      if (!replacement) {
        replacement = (id, path) => members.has(id)
          ? members.get(id).projectPath === path : original(id, path);
        registry.host.candidateMatches = replacement;
      }
      // Drop an old ownership slot before adding the new one. An interruption
      // can leave a session temporarily ungrouped, never owned by two projects.
      for (const workspace of all) {
        for (const id of [...workspace.record.sessionIds]) {
          signal.throwIfAborted();
          if (members.has(id) && members.get(id).projectPath !== workspace.path) {
            await workspace.detachSession(id);
          }
        }
      }
      for (const workspace of workspaces) {
        signal.throwIfAborted();
        const ids = [...members].filter(([, row]) => row.projectPath === workspace.path).map(([id]) => id);
        if (!ids.length) continue;
        await workspace.mutate(record => {
          const missing = ids.filter(id => !record.sessionIds.includes(id));
          // On host startup, publish once even if persisted members were only
          // filtered while the native registry initialized before this plugin.
          if (published && missing.length === 0) return record;
          return {...record, sessionIds: [...missing, ...record.sessionIds]};
        });
      }
      published = true;
    },
  };
}

export async function syncFrameworkWorkspaces(ctx, projects, signal, legacy = null) {
  // The official list method returns snapshots containing headers and file
  // metadata only. Do not open/restore a session to obtain its membership.
  const snapshots = await ctx.sessionPersistence.list({signal});
  if (legacy) await legacy.sync(projects, snapshots, signal);
  for (const project of projects) {
    signal.throwIfAborted();
    // create reuses by canonical path without changing an existing title.
    const workspace = await ctx.workspaceRegistry.create(project.path, project.title);
    const attached = new Set(workspace.sessionIds);
    for (const {header} of snapshots) {
      signal.throwIfAborted();
      if (header?.cwd !== project.path || typeof header.id !== "string" || attached.has(header.id) ||
          legacy?.contains(header.id)) continue;
      // Native attach validates the original header again and persists only
      // the registry membership. Root and child sessions follow the same rule.
      await workspace.attachSession(header.id);
      attached.add(header.id);
    }
  }
}

export async function apply(ctx, config) {
  await frameworkProjects(config);
  const interval = config.pollIntervalMs ?? 3000;
  if (!Number.isInteger(interval) || interval < 1000 || interval > 60000) {
    throw new TypeError("Framework workspace poll interval is invalid");
  }
  const controller = new AbortController();
  const legacy = config.legacyMemberships === undefined ? null : legacyGrouping(ctx, config.legacyMemberships);
  let pending;
  const tick = () => {
    if (controller.signal.aborted || pending) return pending;
    pending = frameworkProjects(config)
      .then(projects => syncFrameworkWorkspaces(ctx, projects, controller.signal, legacy))
      .catch(() => {
        if (!controller.signal.aborted) ctx.logger.warn("HyperTest framework grouping will retry");
      })
      .finally(() => { pending = undefined; });
    return pending;
  };
  const timer = setInterval(tick, interval);
  timer.unref?.();
  ctx.effect(() => async () => {
    clearInterval(timer);
    controller.abort();
    await pending;
    legacy?.dispose();
  }, "hypertest-framework-workspaces.poll");
  await tick();
}
