"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError, getJobActivity } from "@/lib/api";
import { emptyActivityFeed, reconcileActivity } from "@/lib/job-activity";
import type { BackgroundJob } from "@/lib/types";

export function useJobActivity(job: BackgroundJob) {
  const [feed, setFeed] = useState(emptyActivityFeed);
  const previousStatus = useRef(job.status);
  const olderController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const latest = useQuery({
    queryKey: ["job-activity", job.id],
    queryFn: ({ signal }) => getJobActivity(job.id, undefined, signal),
    refetchInterval: ["QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"].includes(job.status) ? 2_000 : false,
    retry: false,
  });
  const { refetch } = latest;
  useEffect(() => {
    if (previousStatus.current !== job.status) { previousStatus.current = job.status; void refetch(); }
  }, [job.status, refetch]);
  useEffect(() => {
    if (latest.data?.job_id === job.id) setFeed((current) => reconcileActivity(current, latest.data!, "head"));
  }, [latest.data, latest.dataUpdatedAt, job.id]);
  useEffect(() => () => olderController.current?.abort(), []);

  const older = useMutation({
    mutationFn: async (cursor: string) => {
      olderController.current?.abort();
      olderController.current = new AbortController();
      const requestGeneration = generation.current;
      const page = await getJobActivity(job.id, cursor, olderController.current.signal);
      return { page, requestGeneration, cursor };
    },
    onSuccess: ({ page, requestGeneration, cursor }) => { if (page.job_id === job.id && requestGeneration === generation.current) setFeed((current) => reconcileActivity(current, page, "older", cursor)); },
    retry: false,
  });
  const cursorExpired = older.error instanceof ApiError && older.error.status === 409 && older.error.detail === "Activity cursor expired";

  async function reset() {
    generation.current += 1;
    olderController.current?.abort();
    older.reset();
    const result = await latest.refetch();
    // A failed reset retains all previously loaded records.
    if (result.data?.job_id === job.id && !result.isError) setFeed(reconcileActivity(emptyActivityFeed(), result.data, "reset"));
  }
  return {
    latest, feed, older, cursorExpired, reset,
    loadEarlier: () => { if (feed.nextCursor && !feed.atLimit && !older.isPending && !cursorExpired) older.mutate(feed.nextCursor); },
  };
}
