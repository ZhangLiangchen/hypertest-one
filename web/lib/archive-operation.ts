"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";
import { createOperationJournal, type JournalIdentity } from "@/lib/operation-journal";
import { createUuid } from "@/lib/uuid";
import { archiveManage, getArchiveOperation, type ArchiveManagement, type ArchiveRequest } from "@/lib/archive";

export type LocalWebPending = JournalIdentity & { stream: string; path: string; recovery_path: string; payload: Record<string, unknown> & { idempotency_key: string } };
function pending(value: unknown, project: string): LocalWebPending {
  const v = value as LocalWebPending;
  if (!v || v.project_id !== project || !["SENT", "UNKNOWN"].includes(v.state) || typeof v.stream !== "string" || typeof v.path !== "string" || typeof v.recovery_path !== "string"
    || !v.payload || v.payload.idempotency_key !== v.operation_key || !/^[A-Za-z0-9_.:-]{1,128}$/.test(v.operation_key)) throw new Error("ARCHIVE_JOURNAL_INVALID");
  return v;
}
const journals = {
  archive: createOperationJournal("local-archive", pending, (v) => v.stream),
  auth: createOperationJournal("cli-authorization", pending, (v) => v.stream),
};
const canonical = (v: unknown): string => JSON.stringify(v && typeof v === "object" ? Array.isArray(v) ? v.map((x) => JSON.parse(canonical(x))) : Object.fromEntries(Object.keys(v).sort().map((k) => [k, JSON.parse(canonical((v as Record<string, unknown>)[k]))])) : v);
export function validateManagement(original: LocalWebPending, result: ArchiveManagement) {
  const receipt = result?.receipt;
  const names: Record<string, string> = { tasks: "CREATE", subtasks: "SUBTASK_CREATE", authorize: "AUTHORIZE", update: "UPDATE", publications: "PUBLISH" };
  const action = names[original.path.split("/").at(-1)!];
  const frozen = { operation: action, task_id: action === "CREATE" ? null : original.path.split("/")[1], request: original.payload };
  const expectedVersion = action === "CREATE" ? 1 : Number(original.payload.expected_task_version) + 1;
  if (!receipt || receipt.project_id !== original.project_id || receipt.idempotency_key !== original.operation_key || receipt.task_id !== result.task?.id
    || receipt.operation !== action || result.task.project_id !== original.project_id || receipt.task_version !== result.task.version || result.task.version !== expectedVersion
    || canonical(receipt.request_payload) !== canonical(frozen) || !Array.isArray(result.subtasks)
    || (original.path !== "tasks" && result.task.id !== original.path.split("/")[1])) throw new Error("ARCHIVE_RECEIPT_MISMATCH");
  if (["CREATE", "UPDATE"].includes(action) && ["title", "objective"].some((field) => field in original.payload && original.payload[field] !== result.task[field as "title" | "objective"])) throw new Error("ARCHIVE_RECEIPT_MISMATCH");
  if (action === "CREATE" && (result.task.archive_version !== 1 || result.task.reported_result !== "NOT_RUN" || result.task.status !== "DRAFT"
    || ("owner_uploader_actor_ref" in original.payload && original.payload.owner_uploader_actor_ref !== result.task.owner_uploader_actor_ref))) throw new Error("ARCHIVE_RECEIPT_MISMATCH");
  if (action === "CREATE" && (["sut_branch", "framework_branch"] as const).some((field) => field in original.payload && original.payload[field] !== (result.task[field] ?? null))) throw new Error("ARCHIVE_RECEIPT_MISMATCH");
  return result;
}
/** Persist SENT before the sole POST; failed delivery is only reconciled by GET. */
export function useLocalWebOperation<T>(domain: "archive" | "auth", projectId: string, stream: string, send: (path: string, payload: LocalWebPending["payload"]) => Promise<T>, recover: (path: string) => Promise<T>, validate: (original: LocalWebPending, result: T) => T) {
  const journal = journals[domain];
  const [current, setCurrent] = useState<LocalWebPending | null>(null), [ready, setReady] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const active = useRef(false), epoch = useRef(0), currentRef = useRef<LocalWebPending | null>(null);
  async function read(generation: number) {
    const rows = await journal.read(projectId);
    if (epoch.current === generation) { currentRef.current = rows.find((r) => r.stream === stream) || null; setCurrent(currentRef.current); }
  }
  useEffect(() => {
    const generation = ++epoch.current; setReady(false); setCurrent(null); currentRef.current = null; setError(null); setBusy(false); active.current = false;
    const refresh = () => void read(generation).catch((failure) => { if (epoch.current === generation) { setError(failure); setReady(false); } });
    const unsubscribe = journal.subscribe(projectId, refresh);
    void read(generation).then(() => { if (epoch.current === generation) setReady(true); }).catch((failure) => { if (epoch.current === generation) setError(failure); });
    return () => { unsubscribe(); epoch.current++; };
  }, [domain, projectId, stream]);
  async function accept(original: LocalWebPending, response: T, generation: number) {
    const value = validate(original, response);
    if (!await journal.settle(original)) return null;
    await read(generation); if (epoch.current !== generation) return null;
    setError(null); return value;
  }
  async function submit(path: string, recoveryPath: (key: string) => string, payload: Record<string, unknown>): Promise<T | null> {
    if (!ready || active.current || currentRef.current) return null;
    active.current = true; const generation = epoch.current; setBusy(true); setError(null);
    let original: LocalWebPending | null = null, acknowledged = false;
    try {
      const key = createUuid();
      const record: LocalWebPending = { project_id: projectId, stream, path, recovery_path: recoveryPath(key), operation_key: key, state: "SENT", payload: { ...payload, idempotency_key: key } };
      const reserved = await journal.reserve(record);
      if (!reserved.created) { await read(generation); return null; }
      original = record; if (epoch.current === generation) { currentRef.current = original; setCurrent(original); }
      const result = await send(path, original.payload); acknowledged = true;
      return await accept(original, result, generation);
    } catch (failure) {
      if (original) {
        try {
          if (!acknowledged && failure instanceof ApiError && [400, 401, 403, 404, 409, 413, 415, 422].includes(failure.status) && !/KEY_CONFLICT/.test(failure.detail)) await journal.settle(original);
          else await journal.markUnknown(original);
          await read(generation);
        } catch { if (epoch.current === generation) setReady(false); }
      } else if (epoch.current === generation) setReady(false);
      if (epoch.current === generation) setError(failure);
      return null;
    } finally { if (epoch.current === generation) { active.current = false; setBusy(false); } }
  }
  async function reconcile() {
    if (!currentRef.current || active.current) return null;
    active.current = true; const generation = epoch.current, original = currentRef.current; setBusy(true);
    try { return await accept(original, await recover(original.recovery_path), generation); }
    catch (failure) { if (epoch.current === generation) setError(failure); return null; }
    finally { if (epoch.current === generation) { active.current = false; setBusy(false); } }
  }
  return { pending: current, ready, busy, error, blocked: !ready || busy || Boolean(current), submit, reconcile };
}
export function useArchiveOperation(projectId: string, stream: string) {
  const operation = useLocalWebOperation("archive", projectId, stream, (path, payload) => archiveManage(path, payload as ArchiveRequest),
    (path) => getArchiveOperation(projectId, new URLSearchParams(path.split("?")[1]).get("idempotency_key") || ""), validateManagement);
  return { ...operation, manage: (path: string, fields: Record<string, unknown>) => operation.submit(path, (key) => `operations/by-key?project_id=${projectId}&idempotency_key=${key}`, { ...fields, project_id: projectId }) };
}
