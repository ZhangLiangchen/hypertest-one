/**
 * Group SDK sessions in the existing Harness host, which alone owns the native
 * workspace registry. Listing session headers does not restore an Agent or
 * read its conversation. Install this in the Web/desktop host, never in each
 * independent SDK process.
 */
import {lstat, readFile, readdir, realpath, stat} from "node:fs/promises";
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

export async function syncFrameworkWorkspaces(ctx, projects, signal) {
  // The official list method returns snapshots containing headers and file
  // metadata only. Do not open/restore a session to obtain its membership.
  const snapshots = await ctx.sessionPersistence.list({signal});
  for (const project of projects) {
    signal.throwIfAborted();
    // create reuses by canonical path without changing an existing title.
    const workspace = await ctx.workspaceRegistry.create(project.path, project.title);
    const attached = new Set(workspace.sessionIds);
    for (const {header} of snapshots) {
      signal.throwIfAborted();
      if (header?.cwd !== project.path || typeof header.id !== "string" || attached.has(header.id)) continue;
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
  let pending;
  const tick = () => {
    if (controller.signal.aborted || pending) return pending;
    pending = frameworkProjects(config)
      .then(projects => syncFrameworkWorkspaces(ctx, projects, controller.signal))
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
  }, "hypertest-framework-workspaces.poll");
  await tick();
}
