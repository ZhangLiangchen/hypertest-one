"use client";

import { useEffect, useRef, useState } from "react";
import { createUuid } from "@/lib/uuid";
import { CLOUD_PROFILE, CloudApiError, canReleaseCloudPending, cloudConfiguration, cloudCredentialReceiptVisible, cloudCredentials, cloudDocument, cloudInputIdentity, cloudOperation, cloudReceiptMatches, cloudRequest, cloudStorageKey, parseCloudPending } from "@/lib/cloud";
import type { CloudMutation, CloudPending, CloudReceipt, CloudRecord } from "@/lib/cloud";

async function verifyAccepted(projectId: string, receipt: CloudReceipt): Promise<void> {
  if (receipt.task_id) { await cloudDocument(projectId, receipt.task_id, receipt.version); return; }
  if (receipt.operation === "CONFIGURE") {
    const configurations = await cloudConfiguration(projectId);
    if (!configurations.items.some((row) => row.id === receipt.config_id && row.revision === receipt.version)) throw new Error("READBACK_PENDING");
  } else if (["STORE_CREDENTIAL", "REVOKE_CREDENTIAL"].includes(receipt.operation)) {
    const credentials = await cloudCredentials(projectId);
    if (!cloudCredentialReceiptVisible(receipt, credentials)) throw new Error("READBACK_PENDING");
  }
}

/** One Web submission stream: uncertain writes reconcile by original key only. */
export function useCloudOperation(projectId: string) {
  const [pending, setPending] = useState<CloudPending | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<CloudReceipt | null>(null);
  const active = useRef(false);
  const current = useRef<CloudPending | null>(null);

  useEffect(() => {
    setReady(false); setReceipt(null); setIssue(null);
    try {
      const restored = parseCloudPending(sessionStorage.getItem(cloudStorageKey(projectId)), projectId);
      current.current = restored; setPending(restored); setReady(true);
    } catch { setIssue("PRIVATE_JOURNAL_UNAVAILABLE"); }
  }, [projectId]);

  function save(value: CloudPending | null) {
    if (value) sessionStorage.setItem(cloudStorageKey(projectId), JSON.stringify(value));
    else sessionStorage.removeItem(cloudStorageKey(projectId));
    current.current = value; setPending(value);
  }

  async function accept(original: CloudPending, response: CloudReceipt) {
    if (!cloudReceiptMatches(original, response)) throw new Error("RECEIPT_MISMATCH");
    setReceipt(response);
    await verifyAccepted(projectId, response);
    save(null); setIssue(null);
    return response;
  }

  async function submit(fields: CloudRecord): Promise<CloudReceipt | null> {
    if (!ready || active.current || current.current) return null;
    active.current = true; setBusy(true); setIssue(null); setReceipt(null);
    let original: CloudPending | null = null;
    let acknowledged = false;
    try {
      const payload = { ...fields, profile: CLOUD_PROFILE, project_id: projectId, operation_key: "web:" + createUuid() } as CloudMutation;
      // The exact body is frozen in memory; private credentials are never journaled.
      const body = JSON.stringify(payload);
      const { secret: _secret, ...safeIdentity } = payload;
      original = { project_id: projectId, operation_key: payload.operation_key, expected_version: payload.expected_version,
        operation: payload.operation, digest: cloudInputIdentity(safeIdentity), state: "SENT",
        ...(typeof payload.task_id === "string" ? { task_id: payload.task_id } : {}) };
      save(original); // A failing storage write prevents the POST.
      const response = await cloudRequest<CloudReceipt>("operations", { method: "POST", body });
      acknowledged = true;
      return await accept(original, response);
    } catch (error) {
      if (error instanceof CloudApiError && canReleaseCloudPending(error.status, acknowledged)) {
        try { save(null); } catch { /* Keep the in-memory stream blocked on storage failure. */ }
        setIssue(error.status === 409 ? "VERSION_CONFLICT" : "REQUEST_REJECTED");
      } else {
        if (original) { try { save({ ...original, state: "UNKNOWN" }); } catch { setReady(false); } }
        setIssue(original ? "ORIGINAL_KEY_READBACK_REQUIRED" : "PRIVATE_JOURNAL_UNAVAILABLE");
      }
      return null;
    } finally { active.current = false; setBusy(false); }
  }

  async function reconcile(): Promise<CloudReceipt | null> {
    if (!current.current || active.current) return null;
    active.current = true; setBusy(true);
    try { return await accept(current.current, await cloudOperation(projectId, current.current.operation_key)); }
    catch { setIssue("ORIGINAL_KEY_READBACK_REQUIRED"); return null; }
    finally { active.current = false; setBusy(false); }
  }

  return { pending, ready, busy, issue, receipt, submit, reconcile, blocked: !ready || busy || pending !== null };
}
