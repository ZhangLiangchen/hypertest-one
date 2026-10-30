"use client";

import { useEffect, useRef, useState } from "react";
import { createUuid } from "@/lib/uuid";
import { createOperationJournal } from "@/lib/operation-journal";
import { CLOUD_PROFILE, CloudApiError, canReleaseCloudPending, cloudConfiguration, cloudCredentialReceiptVisible, cloudCredentials, cloudDocument, cloudInputIdentity, cloudOperation, cloudReceiptMatches, cloudRequest, cloudStorageKey, parseCloudPending, cloudSubmissionIssue } from "@/lib/cloud";
import type { CloudMutation, CloudPending, CloudReceipt, CloudRecord } from "@/lib/cloud";

export const cloudJournal = createOperationJournal<CloudPending>("cloud", (value, projectId) => {
  const pending = parseCloudPending(JSON.stringify(value), projectId);
  if (!pending) throw new Error("PENDING_RECORD_INVALID");
  return pending;
});

async function verifyAccepted(projectId: string, receipt: CloudReceipt): Promise<void> {
  if (receipt.task_id) {
    const document = await cloudDocument(projectId, receipt.task_id, receipt.version);
    if (document.task?.id !== receipt.task_id || document.task.project_id !== projectId || document.task.version !== receipt.version
      || (receipt.operation === "DELETE_TASK" && !document.task.deleted_at)
      || ![document.attempts, document.resolutions, document.assets, document.artifacts, document.runs, document.run_cases, document.delegations, document.questions, document.answers].every(Array.isArray)) throw new Error("READBACK_PENDING");
    return;
  }
  if (receipt.operation === "CONFIGURE") {
    const configurations = await cloudConfiguration(projectId);
    if (!configurations.items.some((row) => row.id === receipt.config_id && row.revision === receipt.version)) throw new Error("READBACK_PENDING");
  } else if (["STORE_CREDENTIAL", "REVOKE_CREDENTIAL"].includes(receipt.operation)) {
    const credentials = await cloudCredentials(projectId);
    if (!cloudCredentialReceiptVisible(receipt, credentials)) throw new Error("READBACK_PENDING");
  }
}

/** One durable Cloud stream per Project, independently fenced by its original key. */
export function useCloudOperation(projectId: string) {
  const [pending, setPending] = useState<CloudPending | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  const [rejection, setRejection] = useState<string | null>(null);
  const [rejectedOperation, setRejectedOperation] = useState<CloudPending | null>(null);
  const [receipt, setReceipt] = useState<CloudReceipt | null>(null);
  const active = useRef(false);
  const current = useRef<CloudPending | null>(null);
  const visibleProject = useRef(projectId);
  const generation = useRef(0);
  const migrationFailed = useRef(false);
  const reads = useRef<Promise<void>>(Promise.resolve());
  visibleProject.current = projectId;

  const visible = (epoch: number) => visibleProject.current === projectId && generation.current === epoch;
  function refresh(epoch: number): Promise<void> {
    const read = reads.current.catch(() => {}).then(async () => {
      const records = await cloudJournal.read(projectId);
      if (visible(epoch)) { current.current = records[0] || null; setPending(current.current); }
    });
    reads.current = read;
    return read;
  }

  useEffect(() => {
    const epoch = ++generation.current;
    active.current = false; current.current = null; setPending(null);
    setReady(false); setBusy(false); setReceipt(null); setIssue(null); setRejection(null); setRejectedOperation(null);
    const changed = () => { void refresh(epoch).catch(() => { if (visible(epoch)) { setReady(false); setIssue("PRIVATE_JOURNAL_UNAVAILABLE"); } }); };
    const unsubscribe = cloudJournal.subscribe(projectId, changed);
    void (async () => {
      // An unreadable legacy store blocks new writes, while durable keys remain
      // available for authorized read-only reconciliation.
      migrationFailed.current = false;
      try {
        const legacy = parseCloudPending(sessionStorage.getItem(cloudStorageKey(projectId)), projectId);
        if (legacy) {
          await cloudJournal.importLegacy(legacy);
          sessionStorage.removeItem(cloudStorageKey(projectId));
        }
      } catch { if (visible(epoch)) migrationFailed.current = true; }
      await refresh(epoch);
      if (visible(epoch)) { setReady(!migrationFailed.current); if (migrationFailed.current) setIssue("PRIVATE_JOURNAL_UNAVAILABLE"); }
    })().catch(() => { if (visible(epoch)) setIssue("PRIVATE_JOURNAL_UNAVAILABLE"); });
    return () => { unsubscribe(); if (generation.current === epoch) generation.current++; };
  }, [projectId]);

  async function accept(original: CloudPending, response: CloudReceipt, epoch: number) {
    if (!cloudReceiptMatches(original, response)) throw new Error("RECEIPT_MISMATCH");
    await verifyAccepted(projectId, response);
    // Another tab may have settled this key and started a new request while our
    // readback was in flight. Settle only this immutable identity.
    const settled = await cloudJournal.settle(original);
    await refresh(epoch);
    if (!visible(epoch) || !settled) return null;
    setReceipt(response); setIssue(migrationFailed.current ? "PRIVATE_JOURNAL_UNAVAILABLE" : null);
    return response;
  }

  async function submit(fields: CloudRecord): Promise<CloudReceipt | null> {
    if (!ready || active.current || current.current) return null;
    const epoch = generation.current;
    active.current = true; setBusy(true); setIssue(null); setReceipt(null); setRejection(null); setRejectedOperation(null);
    let original: CloudPending | null = null;
    let acknowledged = false;
    try {
      const payload = { ...fields, profile: CLOUD_PROFILE, project_id: projectId, operation_key: "web:" + createUuid() } as CloudMutation;
      const body = JSON.stringify(payload);
      const { secret: _secret, ...safeIdentity } = payload;
      const candidate: CloudPending = { project_id: projectId, operation_key: payload.operation_key, expected_version: payload.expected_version,
        operation: payload.operation, digest: cloudInputIdentity(safeIdentity), state: "SENT",
        ...(typeof payload.task_id === "string" ? { task_id: payload.task_id } : {}),
        ...(typeof payload.attempt_id === "string" ? { attempt_id: payload.attempt_id } : {}) };
      const reserved = await cloudJournal.reserve(candidate); // Commit before any POST; storage failure prohibits sending.
      if (!reserved.created) { await refresh(epoch); if (visible(epoch)) setIssue("ORIGINAL_KEY_READBACK_REQUIRED"); return null; }
      original = candidate;
      if (visible(epoch)) { current.current = original; setPending(original); }
      const response = await cloudRequest<CloudReceipt>("operations", { method: "POST", body });
      acknowledged = true;
      return await accept(original, response, epoch);
    } catch (error) {
      if (original && error instanceof CloudApiError && canReleaseCloudPending(error.status, acknowledged, cloudSubmissionIssue(error))) {
        try { await cloudJournal.settle(original); await refresh(epoch); }
        catch { if (visible(epoch)) setReady(false); }
        if (visible(epoch)) {
          setIssue(cloudSubmissionIssue(error));
          setRejection(error.message); setRejectedOperation(original);
        }
      } else {
        if (original) {
          try { await cloudJournal.markUnknown(original); await refresh(epoch); }
          catch { if (visible(epoch)) setReady(false); }
        } else if (visible(epoch)) setReady(false);
        if (visible(epoch)) setIssue(original ? "ORIGINAL_KEY_READBACK_REQUIRED" : "PRIVATE_JOURNAL_UNAVAILABLE");
      }
      return null;
    } finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }

  async function reconcile(): Promise<CloudReceipt | null> {
    if (!current.current || active.current) return null;
    const original = current.current, epoch = generation.current;
    active.current = true; setBusy(true);
    try { return await accept(original, await cloudOperation(projectId, original.operation_key), epoch); }
    catch { if (visible(epoch)) setIssue("ORIGINAL_KEY_READBACK_REQUIRED"); return null; }
    finally { if (visible(epoch)) { active.current = false; setBusy(false); } }
  }

  return { pending, ready, busy, issue, rejection, rejectedOperation, receipt, submit, reconcile, blocked: !ready || busy || pending !== null };
}
