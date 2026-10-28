/**
 * Clipboard copy that also works on plain-HTTP origins (the WireGuard test Web),
 * where `navigator.clipboard` is undefined because the page is not a secure
 * context. Falls back to the legacy selection command during the same user
 * gesture; callers show the manual-copy textarea only when both paths fail.
 */
export async function copyText(value: string): Promise<void> {
  const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
  if (clipboard && typeof clipboard.writeText === "function") {
    try { await clipboard.writeText(value); return; } catch { /* fall through to the legacy copy path */ }
  }
  if (!legacyCopy(value)) throw new Error("CLIPBOARD_UNAVAILABLE");
}

function legacyCopy(value: string): boolean {
  if (typeof document === "undefined" || !document.body || typeof document.execCommand !== "function") return false;
  const previous = document.activeElement as HTMLElement | null;
  const area = document.createElement("textarea");
  area.value = value;
  area.setAttribute("readonly", "");
  area.setAttribute("aria-hidden", "true");
  area.style.position = "fixed";
  area.style.top = "-1000px";
  area.style.left = "-1000px";
  area.style.opacity = "0";
  document.body.appendChild(area);
  try {
    area.focus();
    area.select();
    area.setSelectionRange(0, value.length);
    return document.execCommand("copy");
  } catch { return false; }
  finally {
    if (area.parentNode) area.parentNode.removeChild(area);
    if (previous && typeof previous.focus === "function") previous.focus({ preventScroll: true });
  }
}
