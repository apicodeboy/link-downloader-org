"use client";

import { useCallback, useEffect, useState } from "react";
import { useMe } from "@/components/AppShell";
import { Alert, Badge, Button, Card, EmptyState, SectionTitle, Spinner, StatusBadge, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, isActive, timeAgo } from "@/lib/format";
import type { Job } from "@/lib/types";

interface AdminStatus {
  versions: Record<string, string | null>;
  queue: { connected: boolean; depth: number | null };
  jobs: Record<string, number>;
  storage: { used_bytes: number; quota_bytes: number; disk_free_bytes: number; disk_total_bytes: number };
  limits: Record<string, number>;
}

const FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

export default function JobsPage() {
  const me = useMe();
  const [filter, setFilter] = useState("");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ items: Job[] }>(`/api/jobs?limit=100${filter ? `&status=${filter}` : ""}`);
      setJobs(r.items);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
    if (me?.user.role === "admin") api<AdminStatus>("/api/admin/status").then(setStatus).catch(() => {});
  }, [filter, me]);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const usedPct = status ? Math.round((status.storage.used_bytes / status.storage.quota_bytes) * 100) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
        <p className="mt-1 text-sm text-muted">Live view of background work. Refreshes every few seconds.</p>
      </div>

      {status && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="Queue" value={status.queue.connected ? `${status.queue.depth ?? 0} waiting` : "Offline"} bad={!status.queue.connected} />
          <Stat label="Running" value={String((status.jobs.analyzing ?? 0) + (status.jobs.downloading ?? 0) + (status.jobs.processing ?? 0))} />
          <Stat label="Storage used" value={`${formatBytes(status.storage.used_bytes)} (${usedPct}%)`} bad={usedPct > 90} />
          <Stat label="Disk free" value={formatBytes(status.storage.disk_free_bytes)} />
        </div>
      )}
      {status && (
        <p className="text-xs text-faint">
          yt-dlp {status.versions.yt_dlp} · {status.versions.ffmpeg?.split(" Copyright")[0] ?? "FFmpeg missing"} · Python {status.versions.python} ·
          files kept {status.limits.retention_minutes} min
        </p>
      )}

      <div className="flex gap-1 overflow-x-auto">
        {FILTERS.map((f) => (
          <button key={f.value} onClick={() => setFilter(f.value)}
                  className={cx("shrink-0 rounded-lg px-3 py-1.5 text-sm", filter === f.value ? "bg-surface-3 text-fg" : "text-muted hover:text-fg")}>
            {f.label}
          </button>
        ))}
      </div>

      {error && <Alert>{error}</Alert>}
      {jobs === null ? (
        <div className="flex justify-center py-12 text-muted"><Spinner className="size-6" /></div>
      ) : jobs.length === 0 ? (
        <EmptyState title="No jobs" />
      ) : (
        <Card className="p-0 sm:p-0">
          <SectionTitle><span className="block px-4 pt-4">{jobs.length} jobs</span></SectionTitle>
          <ul className="divide-y divide-line">
            {jobs.map((j) => (
              <li key={j.id} className="px-4 py-3">
                <button className="flex w-full items-center gap-3 text-left" onClick={() => setOpen(open === j.id ? null : j.id)}>
                  <StatusBadge status={j.status} />
                  <Badge>{j.kind}</Badge>
                  <span className="min-w-0 flex-1 truncate text-sm text-muted">
                    {isActive(j.status) ? `${j.stage ?? ""} ${Math.round(j.progress * 100)}%` : j.error?.message ?? j.source_url ?? j.id}
                  </span>
                  <span className="shrink-0 text-xs text-faint">{timeAgo(j.created_at)}</span>
                </button>
                {open === j.id && (
                  <dl className="mt-3 grid gap-x-4 gap-y-1 rounded-lg bg-surface-2 p-3 text-xs sm:grid-cols-[8rem_1fr]">
                    <dt className="text-muted">Job ID</dt><dd className="font-mono break-all">{j.id}</dd>
                    <dt className="text-muted">Source</dt><dd className="break-all">{j.source_url ?? "—"}</dd>
                    <dt className="text-muted">Started</dt><dd>{j.started_at ? new Date(j.started_at).toLocaleString() : "—"}</dd>
                    <dt className="text-muted">Finished</dt><dd>{j.finished_at ? new Date(j.finished_at).toLocaleString() : "—"}</dd>
                    {j.error && (<><dt className="text-muted">Error</dt><dd className="text-bad">{j.error.code}: {j.error.message}</dd></>)}
                  </dl>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Button variant="ghost" onClick={load} className="h-9 px-3">Refresh now</Button>
    </div>
  );
}

function Stat({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className={cx("mt-1 text-lg font-semibold tabular-nums", bad && "text-bad")}>{value}</p>
    </div>
  );
}
