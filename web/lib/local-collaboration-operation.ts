"use client";

import { useEffect, useRef, useState } from "react";
import { changeTaskCollaboration, getTaskCollaboration, getTaskCollaborationReceipt } from "@/lib/api";
import { createOperationJournal } from "@/lib/operation-journal";
import { collaborationWasRejected, validateCollaborationPending, validateCollaborationReadback } from "@/lib/local-collaboration";
import type { CollaborationDocument, CollaborationPending, CollaborationReceipt, CollaborationRequest } from "@/lib/local-collaboration";

export const collaborationJournal = createOperationJournal<CollaborationPending>("local-collaboration", validateCollaborationPending, (value) => value.task_id);

/** One frozen request per task, independent of Cloud and Local CREATE journals. */
export function useCollaborationOperation(projectId: string, taskId: string) {
  const [pending, setPending] = useState<CollaborationRequest | null>(null);
  const [ready, setReady] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null), [storageError, setStorageError] = useState(false);
  const current = useRef<CollaborationPending | null>(null), active = useRef(false), generation = useRef(0);
  const reads = useRef<Promise<void>>(Promise.resolve()), scope = useRef("");
  scope.current = `${projectId}:${taskId}`;
  const visible = (epoch: number) => scope.current === `${projectId}:${taskId}` && generation.current === epoch;
  function refresh(epoch: number): Promise<void> {
    const read = reads.current.catch(() => {}).then(async () => {
      const records = (await collaborationJournal.read(projectId)).filter((row) => row.task_id === taskId);
      if (visible(epoch)) { current.current = records[0] || null; setPending(current.current?.payload || null); }
    });
    reads.current = read; return read;
  }
  useEffect(() => {
    const epoch = ++generation.current;
    current.current = null; active.current = false;
    setPending(null); setReady(false); setBusy(false); setError(null); setStorageError(false);
    const changed = () => { void refresh(epoch).catch(() => { if (visible(epoch)) { setReady(false); setStorageError(true); } }); };
    const unsubscribe = collaborationJournal.subscribe(projectId, changed);
    void refresh(epoch).then(() => { if (visible(epoch)) setReady(true); }).catch(() => { if (visible(epoch)) setStorageError(true); });
    return () => { unsubscribe(); if (generation.current === epoch) generation.current++; };
  }, [projectId, taskId]);
  async function accept(original: CollaborationPending, receipt: CollaborationReceipt, epoch: number) {
    // Read the receipt's fixed version. A current GET never settles a write.
    const document = validateCollaborationReadback(original, receipt, await getTaskCollaboration(taskId, receipt.version));
    const settled = await collaborationJournal.settle(original);
    await refresh(epoch);
    if (!visible(epoch) || !settled) return null;
    setError(null); return document;
  }
  async function submit(payload: CollaborationRequest): Promise<CollaborationDocument | null> {
    if (!ready || active.current || current.current) return null;
    const epoch = generation.current;
    active.current = true; setBusy(true); setError(null);
    let original: CollaborationPending | null = null, acknowledged = false;
    try {
      const reserved = await collaborationJournal.reserve({ project_id: projectId, task_id: taskId, operation_key: payload.idempotency_key, state: "SENT", payload });
      if (!reserved.created) { await refresh(epoch); return null; }
      original = reserved.records[0];
      if (visible(epoch)) { current.current = original; setPending(original.payload); }
      const receipt = await changeTaskCollaboration(taskId, original.payload);
      acknowledged = true;
      return await accept(original, receipt, epoch);
    } catch (failure) {
      if (original) {
        try {
          if (!acknowledged && collaborationWasRejected(failure)) await collaborationJournal.settle(original);
          else await collaborationJournal.markUnknown(original);
          await refresh(epoch);
        } catch { if (visible(epoch)) { setReady(false); setStorageError(true); } }
      } else if (visible(epoch)) { setReady(false); setStorageError(true); }
      if (visible(epoch)) setError(failure);
      return null;
    } finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }
  async function reconcile(): Promise<CollaborationDocument | null> {
    if (!current.current || active.current) return null;
    const original = current.current, epoch = generation.current;
    active.current = true; setBusy(true); setError(null);
    try { return await accept(original, await getTaskCollaborationReceipt(taskId, original.operation_key), epoch); }
    catch (failure) { if (visible(epoch)) setError(failure); return null; }
    finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }
  return { pending, ready, busy, error, storageError, submit, reconcile, blocked: !ready || busy || pending !== null };
}
