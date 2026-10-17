import type { BackgroundJob, InputAnswer, InputRequest } from "@/lib/types";

export const MAX_INPUT_ANSWER_CHARACTERS = 12_000;

export function validateInputAnswer(answer: string): "empty" | "length" | "nul" | null {
  if (!answer.trim()) return "empty";
  if (answer.includes("\0")) return "nul";
  return Array.from(answer).length > MAX_INPUT_ANSWER_CHARACTERS ? "length" : null;
}

/** An uncertain retry must retain both the key and the original concurrency token. */
export function prepareInputAnswer(previous: InputAnswer | undefined, answer: string, rowVersion: number, newKey: () => string): InputAnswer {
  return previous?.answer === answer ? previous : {
    answer, expected_row_version: rowVersion, idempotency_key: newKey(),
  };
}

export function canAnswerInput(request: InputRequest, job: BackgroundJob | undefined): boolean {
  return request.status === "PENDING" && job?.id === request.durable_job_id
    && job.test_run_id === request.test_run_id && job.status === "WAITING_INPUT";
}
