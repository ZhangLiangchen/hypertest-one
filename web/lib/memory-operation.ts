"use client";

import { useEffect, useRef, useState } from "react";
import { createUuid } from "@/lib/uuid";
import { createMemoryJournal } from "@/lib/memory-journal";
import { MemoryApiError, memoryConfiguration, memoryDigest, memoryEntry, memoryOperation, memoryReceiptMatches, memoryRequest, parseMemoryPending } from "@/lib/memory";
import type { MemoryMutation, MemoryPending, MemoryReceipt } from "@/lib/memory";

export const memoryJournal = createMemoryJournal<MemoryPending>("memory", parseMemoryPending);

export async function verifyMemoryAccepted(original: MemoryPending, receipt: MemoryReceipt) {
  if (!memoryReceiptMatches(original, receipt)) throw new Error("MEMORY_RECEIPT_MISMATCH");
  if (receipt.operation === "CONFIGURE") {
    const configuration = await memoryConfiguration(original.project_id, receipt.accepted_version!);
    if (configuration.project_id !== original.project_id || configuration.version !== receipt.accepted_version || typeof configuration.enabled !== "boolean") throw new Error("MEMORY_READBACK_PENDING");
  } else {
    const entry = await memoryEntry(original.project_id, receipt.entry_id!, receipt.accepted_version!);
    if (entry.id !== receipt.entry_id || entry.project_id !== original.project_id || entry.version !== receipt.accepted_version
      || typeof entry.title !== "string" || typeof entry.content !== "string" || (entry.revision_status || entry.status) !== (receipt.operation === "CREATE_CANDIDATE" ? "CANDIDATE" : receipt.operation === "RETRACT" ? "RETRACTED" : "PUBLISHED")) throw new Error("MEMORY_READBACK_PENDING");
  }
}

/** A Memory uncertainty blocks only this separate Memory write stream. */
export function useMemoryOperation(projectId: string) {
  const [pending, setPending] = useState<MemoryPending | null>(null); const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false); const [issue, setIssue] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<MemoryReceipt | null>(null);
  const current = useRef<MemoryPending | null>(null), active = useRef(false), generation = useRef(0), visibleProject = useRef(projectId);
  const reads = useRef<Promise<void>>(Promise.resolve()); visibleProject.current = projectId;
  const visible = (epoch: number) => visibleProject.current === projectId && generation.current === epoch;
  function refresh(epoch: number) {
    const read = reads.current.catch(() => {}).then(async () => {
      const records = await memoryJournal.read(projectId);
      if (visible(epoch)) { current.current = records[0] || null; setPending(current.current); }
    }); reads.current = read; return read;
  }
  useEffect(() => {
    const epoch = ++generation.current; active.current = false; current.current = null;
    setReady(false); setBusy(false); setPending(null); setIssue(null); setReceipt(null);
    const changed = () => { void refresh(epoch).catch(() => { if (visible(epoch)) { setReady(false); setIssue("MEMORY_STORAGE_UNAVAILABLE"); } }); };
    const unsubscribe = memoryJournal.subscribe(projectId, changed);
    void refresh(epoch).then(() => { if (visible(epoch)) setReady(true); }).catch(() => { if (visible(epoch)) setIssue("MEMORY_STORAGE_UNAVAILABLE"); });
    return () => { unsubscribe(); if (generation.current === epoch) generation.current++; };
  }, [projectId]);
  async function accept(original: MemoryPending, response: MemoryReceipt, epoch: number) {
    await verifyMemoryAccepted(original, response);
    const settled = await memoryJournal.settle(original); await refresh(epoch);
    if (!visible(epoch) || !settled) return null;
    setReceipt(response); setIssue(null); return response;
  }
  async function submit(fields: Omit<MemoryMutation, "project_id" | "operation_key">): Promise<MemoryReceipt | null> {
    if (!ready || current.current || active.current) return null;
    const epoch = generation.current; active.current = true; setBusy(true); setIssue(null); setReceipt(null);
    let original: MemoryPending | null = null; let acknowledged = false;
    try {
      const request: MemoryMutation = { ...fields, project_id: projectId, operation_key: `memory-web:${createUuid()}` };
      const candidate: MemoryPending = { project_id: projectId, operation_key: request.operation_key, operation: request.operation,
        expected_version: request.expected_version, digest: await memoryDigest(request), state: "SENT", ...(request.entry_id ? { entry_id: request.entry_id } : {}) };
      const reservation = await memoryJournal.reserve(candidate);
      if (!reservation.created) { await refresh(epoch); if (visible(epoch)) setIssue("MEMORY_ORIGINAL_KEY_REQUIRED"); return null; }
      original = candidate; if (visible(epoch)) { current.current = original; setPending(original); }
      const response = await memoryRequest<MemoryReceipt>("operations", { method: "POST", body: JSON.stringify(request) });
      acknowledged = true; return await accept(original, response, epoch);
    } catch (error) {
      // Definite schema/auth/precondition rejection creates no remote operation.
      // A conflict with an existing original key remains uncertain.
      const rejected = original && !acknowledged && error instanceof MemoryApiError && [400, 401, 403, 404, 409, 413, 415, 422].includes(error.status) && error.code !== "MEMORY_OPERATION_KEY_CONFLICT";
      try {
        if (original) { if (rejected) await memoryJournal.settle(original); else await memoryJournal.markUnknown(original); await refresh(epoch); }
      } catch { if (visible(epoch)) setReady(false); }
      if (!original && visible(epoch)) setReady(false);
      if (visible(epoch)) setIssue(!original ? "MEMORY_STORAGE_UNAVAILABLE" : rejected ? "MEMORY_REQUEST_REJECTED" : "MEMORY_ORIGINAL_KEY_REQUIRED");
      return null;
    } finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }
  async function reconcile(): Promise<MemoryReceipt | null> {
    if (!current.current || active.current) return null;
    const original = current.current, epoch = generation.current; active.current = true; setBusy(true);
    try { return await accept(original, await memoryOperation(projectId, original.operation_key), epoch); }
    catch { if (visible(epoch)) setIssue("MEMORY_ORIGINAL_KEY_REQUIRED"); return null; }
    finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }
  async function recoverOriginal(response: MemoryReceipt): Promise<MemoryReceipt | null> {
    if (!ready || active.current || current.current || response.project_id !== projectId || !["SENT", "UNKNOWN"].includes(response.status)) return null;
    const epoch = generation.current;
    try {
      const original = parseMemoryPending({ project_id: projectId, operation_key: response.operation_key, operation: response.operation,
        expected_version: response.expected_version, entry_id: response.entry_id, state: "UNKNOWN", digest: response.request_digest }, projectId);
      await memoryJournal.reserve(original); await refresh(epoch);
      return await reconcile();
    } catch { if (visible(epoch)) setIssue("MEMORY_ORIGINAL_KEY_REQUIRED"); return null; }
  }
  return { pending, ready, busy, issue, receipt, submit, reconcile, recoverOriginal, blocked: !ready || busy || pending !== null };
}
