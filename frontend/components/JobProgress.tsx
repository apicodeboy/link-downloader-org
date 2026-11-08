"use client";

import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { isActive } from "@/lib/format";
import type { Job } from "@/lib/types";
import { Alert, Button, ProgressBar, StatusBadge } from "./ui";

function canCancel(job: Job) {
  return job.status === "queued" || (job.kind === "download" && job.status === "downloading");
}

export function JobProgress({ job, pollError, onRetry }: {
  job: Job | null;
  pollError?: string | null;
  onRetry?: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  if (!job) {
    return pollError ? <Alert tone="warn">{pollError}</Alert> : null;
  }

  if (job.status === "failed") {
    if (job.error?.code === "cancelled") {
      return (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-4 py-3 text-sm">
          <span className="text-muted">Cancelled.</span>
          {onRetry && <Button variant="secondary" className="h-9 px-3" onClick={onRetry}>Start again</Button>}
        </div>
      );
    }
    return (
      <div className="space-y-2">
        <Alert title="That didn't work">{job.error?.message ?? "The job failed."}</Alert>
        {onRetry && job.error?.code && RETRYABLE.has(job.error.code) && (
          <Button variant="secondary" className="h-9 px-3" onClick={onRetry}>Try again</Button>
        )}
        {job.error_detail && (
          <details className="rounded-lg bg-surface-2 px-3 py-2 text-xs text-muted">
            <summary className="cursor-pointer select-none">Technical details</summary>
            <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono">{job.error_detail}</pre>
          </details>
        )}
      </div>
    );
  }

  const cancel = async () => {
    setCancelling(true);
    setCancelError(null);
    try {
      await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
    } catch (e) {
      setCancelError(errorMessage(e));
      setCancelling(false);
    }
  };

  const active = isActive(job.status);
  const stage =
    job.status === "queued" && job.queue_position && job.queue_position > 1
      ? `Waiting in line · ${job.queue_position - 1} ahead of you`
      : job.stage;
  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-center justify-between gap-3 text-sm">
        <StatusBadge status={job.status} />
        <span className="min-w-0 flex-1 truncate text-muted">{stage}</span>
        <span className="tabular-nums text-muted">{Math.round(job.progress * 100)}%</span>
      </div>
      {active && <ProgressBar value={job.progress} active />}
      {active && canCancel(job) && !job.cancel_requested && (
        <button onClick={cancel} disabled={cancelling}
                className="text-xs text-muted underline-offset-2 hover:text-fg hover:underline disabled:opacity-50">
          {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      )}
      {cancelError && <p className="text-xs text-bad">{cancelError}</p>}
      {pollError && <p className="text-xs text-warn">{pollError} Retrying…</p>}
    </div>
  );
}

// Errors where trying again can reasonably succeed.
const RETRYABLE = new Set([
  "rate_limited", "network_timeout", "timeout", "dns_failed", "extractor_failed", "download_failed",
  "worker_error", "stale", "queue_unavailable", "internal_error", "server_busy", "storage_full", "disk_full",
  "redirect_failed",
]);
