"use client";

import { useEffect, useRef, useState } from "react";
import { createLocalTask, getLocalTaskCreation, getSessionTask } from "@/lib/api";
import { createOperationJournal } from "@/lib/operation-journal";
import { localTaskCreateWasRejected, pendingLocalTaskCreation, validateLocalTaskCreation } from "@/lib/local-task-binding";
import type { LocalTaskCreate, SessionTaskDetail } from "@/lib/types";

type LocalPending = { project_id: string; operation_key: string; expected_version: 0; state: "SENT" | "UNKNOWN"; payload: LocalTaskCreate };
export const localCreateJournal = createOperationJournal<LocalPending>("local-create", (value, projectId) => {
  const record = value as LocalPending;
  const payload = pendingLocalTaskCreation(JSON.stringify(record), projectId);
  if (record.operation_key !== payload.idempotency_key || record.expected_version !== 0 || !["SENT", "UNKNOWN"].includes(record.state)) throw new Error("LOCAL_TASK_PENDING_REQUEST_INVALID");
  return { project_id: projectId, operation_key: payload.idempotency_key, expected_version: 0, state: record.state, payload };
});

/** Local CREATE retains its complete management request in a separate ledger. */
export function useLocalCreateOperation(projectId: string) {
  const [pending, setPending] = useState<LocalTaskCreate | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [storageError, setStorageError] = useState(false);
  const [success, setSuccess] = useState(false);
  const current = useRef<LocalPending | null>(null);
  const active = useRef(false);
  const generation = useRef(0);
  const reads = useRef<Promise<void>>(Promise.resolve());
  const visibleProject = useRef(projectId);
  visibleProject.current = projectId;
  const visible = (epoch: number) => visibleProject.current === projectId && generation.current === epoch;

  function refresh(epoch: number): Promise<void> {
    const read = reads.current.catch(() => {}).then(async () => {
      const records = await localCreateJournal.read(projectId);
      if (visible(epoch)) { current.current = records[0] || null; setPending(current.current?.payload || null); }
    });
    reads.current = read;
    return read;
  }

  useEffect(() => {
    const epoch = ++generation.current;
    active.current = false; current.current = null;
    setPending(null); setReady(false); setBusy(false); setSuccess(false); setError(null); setStorageError(false);
    const changed = () => { void refresh(epoch).catch(() => { if (visible(epoch)) { setReady(false); setStorageError(true); } }); };
    const unsubscribe = localCreateJournal.subscribe(projectId, changed);
    void (async () => {
      let migrationFailed = false;
      try {
        const storageKey = `hypertest:local-task-create:${projectId}`;
        const raw = sessionStorage.getItem(storageKey);
        if (raw) {
          const payload = pendingLocalTaskCreation(raw, projectId);
          await localCreateJournal.importLegacy({ project_id: projectId, operation_key: payload.idempotency_key, expected_version: 0, state: "UNKNOWN", payload });
          sessionStorage.removeItem(storageKey);
        }
      } catch { migrationFailed = true; }
      await refresh(epoch);
      if (visible(epoch)) { setReady(!migrationFailed); setStorageError(migrationFailed); }
    })().catch(() => { if (visible(epoch)) setStorageError(true); });
    return () => { unsubscribe(); if (generation.current === epoch) generation.current++; };
  }, [projectId]);

  async function accept(original: LocalPending, response: SessionTaskDetail, epoch: number) {
    const accepted = validateLocalTaskCreation(response, projectId, original.operation_key);
    if (accepted.task.version !== original.expected_version + 1) throw new Error("LOCAL_TASK_CREATION_RECEIPT_MISMATCH");
    const payload = original.payload;
    if (accepted.task.title !== payload.title || accepted.task.objective !== (payload.objective || "")
      || accepted.task.plan_markdown !== (payload.plan_markdown || "")
      || (Object.prototype.hasOwnProperty.call(payload, "intended_actor_ref") && accepted.task.intended_actor_ref !== payload.intended_actor_ref)) throw new Error("LOCAL_TASK_CREATION_RECEIPT_MISMATCH");
    // Never substitute a later current task for the original accepted version.
    const detail = await getSessionTask(accepted.task.id, accepted.task.version, true);
    if (detail.task?.id !== accepted.task.id || detail.task.project_id !== projectId || detail.task.version !== accepted.task.version
      || ![detail.cases, detail.reports, detail.case_history, detail.report_history, detail.sync_history, detail.management_history, detail.binding_history].every(Array.isArray)
      || Object.keys({ ...detail.task, ...accepted.task }).some((key) => JSON.stringify(detail.task[key as keyof typeof detail.task]) !== JSON.stringify(accepted.task[key as keyof typeof accepted.task]))) throw new Error("LOCAL_TASK_CREATION_READBACK_PENDING");
    const settled = await localCreateJournal.settle(original);
    await refresh(epoch);
    if (!visible(epoch) || !settled) return null;
    setSuccess(true); setError(null);
    return { ...detail, creation_receipt: accepted.creation_receipt };
  }

  async function submit(payload: LocalTaskCreate): Promise<SessionTaskDetail | null> {
    if (!ready || active.current || current.current || success) return null;
    const epoch = generation.current;
    active.current = true; setBusy(true); setError(null);
    let original: LocalPending | null = null, acknowledged = false;
    try {
      const candidate: LocalPending = { project_id: projectId, operation_key: payload.idempotency_key, expected_version: 0, state: "SENT", payload };
      const reserved = await localCreateJournal.reserve(candidate);
      if (!reserved.created) { await refresh(epoch); return null; }
      original = reserved.records[0];
      if (visible(epoch)) { current.current = original; setPending(original.payload); }
      const response = await createLocalTask(projectId, original.payload);
      acknowledged = true;
      return await accept(original, response, epoch);
    } catch (failure) {
      if (original) {
        try {
          if (!acknowledged && localTaskCreateWasRejected(failure)) await localCreateJournal.settle(original);
          else await localCreateJournal.markUnknown(original);
          await refresh(epoch);
        } catch { if (visible(epoch)) { setReady(false); setStorageError(true); } }
      } else if (visible(epoch)) { setReady(false); setStorageError(true); }
      if (visible(epoch)) setError(failure);
      return null;
    } finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }

  async function reconcile(): Promise<SessionTaskDetail | null> {
    if (!current.current || active.current) return null;
    const original = current.current, epoch = generation.current;
    active.current = true; setBusy(true); setError(null);
    try { return await accept(original, await getLocalTaskCreation(projectId, original.operation_key), epoch); }
    catch (failure) { if (visible(epoch)) setError(failure); return null; }
    finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }

  return { pending, ready, busy, error, storageError, success, submit, reconcile, resetError: () => setError(null), blocked: !ready || busy || success || pending !== null };
}
