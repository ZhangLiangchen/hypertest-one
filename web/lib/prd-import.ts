export const MAX_PRD_CHARACTERS = 2_000_000;
export type PrdDecodeError = "encoding" | "length" | "empty";

/** Validate the decoded input without trimming content or normalizing newlines. */
export function decodePrdBytes(bytes: ArrayBuffer): { ok: true; text: string } | { ok: false; error: PrdDecodeError } {
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return { ok: false, error: "encoding" };
  }
  if (text.includes("\0")) return { ok: false, error: "encoding" };
  if (text.length > MAX_PRD_CHARACTERS) return { ok: false, error: "length" };
  if (!text.trim()) return { ok: false, error: "empty" };
  return { ok: true, text };
}
