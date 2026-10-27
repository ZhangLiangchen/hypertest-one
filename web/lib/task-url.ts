/** Archive and historical session tasks share a page route, not an API identity. */
export function archiveTaskHref(taskId: string, projectId: string, hash = ""): string {
  const fragment = hash ? (hash.startsWith("#") ? hash : `#${hash}`) : "";
  return `/tasks/${encodeURIComponent(taskId)}?mode=archive&projectId=${encodeURIComponent(projectId)}${fragment}`;
}
