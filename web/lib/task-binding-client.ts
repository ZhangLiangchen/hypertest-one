import { buildLocalSetupPrompt } from "@/lib/local-mode-install";
import type { LocalSetupOptions, LocalUpdater } from "@/lib/local-mode-install";

/** Binding and collaboration use the same published updater as initial setup. */
export function taskBindingClientPrompt(options: Omit<LocalSetupOptions, "harness">, updater?: LocalUpdater): string {
  return buildLocalSetupPrompt({ ...options, harness: "codex" }, updater);
}
