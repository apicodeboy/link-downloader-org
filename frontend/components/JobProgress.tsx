"use client";

import { isActive } from "@/lib/format";
import type { Job } from "@/lib/types";
import { Alert, ProgressBar, StatusBadge } from "./ui";

export function JobProgress({ job, pollError }: { job: Job | null; pollError?: string | null }) {
  if (!job) {
    return pollError ? <Alert tone="warn">{pollError}</Alert> : null;
  }
  if (job.status === "failed") {
    return (
      <div className="space-y-2">
        <Alert title="Failed">{job.error?.message ?? "The job failed."}</Alert>
        {job.error_detail && (
          <details className="rounded-lg bg-surface-2 px-3 py-2 text-xs text-muted">
            <summary className="cursor-pointer select-none">Technical details</summary>
            <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono">{job.error_detail}</pre>
          </details>
        )}
      </div>
    );
  }
  const active = isActive(job.status);
  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-center justify-between gap-3 text-sm">
        <StatusBadge status={job.status} />
        <span className="truncate text-muted">{job.stage}</span>
        <span className="tabular-nums text-muted">{Math.round(job.progress * 100)}%</span>
      </div>
      {active && <ProgressBar value={job.progress} active />}
      {pollError && <p className="text-xs text-warn">{pollError} Retrying…</p>}
    </div>
  );
}
