import type { Verdict } from "@/lib/types";

/** Only a formal decision for this run can lead the run overview. */
export function latestRunVerdict(records: readonly Verdict[] | undefined): Verdict | undefined {
  return records?.reduce<Verdict | undefined>((latest, item) => {
    if (item.status !== "FINAL" || item.scope !== "TEST_RUN") return latest;
    return !latest || item.sequence_no > latest.sequence_no ? item : latest;
  }, undefined);
}
