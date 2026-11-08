"use client";

import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, EmptyState, Field, LinkButton, SectionTitle, Spinner, cx, inputClass } from "@/components/ui";
import { useMe } from "@/components/AppShell";
import { api, errorMessage, fileUrl } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { MediaFile, PublishingConfig, PublishingJob } from "@/lib/types";
import { readQueryParam, useAvailableVideos } from "@/lib/useAvailableVideos";

const STATUS_TONE = { draft: "neutral", approved: "info", submitted: "ok", failed: "bad", cancelled: "neutral" } as const;

function parseTags(text: string): string[] {
  return Array.from(new Set(text.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean).map((t) => "#" + t.replace(/^#+/, ""))));
}

export default function PublishPage() {
  const me = useMe();
  const videos = useAvailableVideos();
  const [config, setConfig] = useState<PublishingConfig | null>(null);
  const [jobs, setJobs] = useState<PublishingJob[]>([]);
  const [fileId, setFileId] = useState("");
  const [caption, setCaption] = useState("");
  const [tags, setTags] = useState("");
  const [dest, setDest] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);

  const loadJobs = () => api<{ items: PublishingJob[] }>("/api/publishing/jobs").then((r) => setJobs(r.items)).catch(() => {});

  useEffect(() => {
    api<PublishingConfig>("/api/publishing/config").then(setConfig).catch((e) => setError(errorMessage(e)));
    loadJobs();
    const q = readQueryParam("file");
    if (q) setFileId(q);
  }, []);

  // Prefill with the original extracted caption so it can be edited, never invented.
  const [source, setSource] = useState<MediaFile["source"]>(null);
  useEffect(() => {
    setSource(null);
    if (!fileId) return;
    api<MediaFile>(`/api/media/${fileId}`).then((f) => {
      setSource(f.source ?? null);
      if (f.source?.caption) setCaption((c) => c || (f.source?.caption ?? ""));
      if (f.source?.hashtags?.length) setTags((t) => t || f.source!.hashtags.join(" "));
    }).catch(() => {});
  }, [fileId]);

  const create = async () => {
    setSaving(true);
    setError(null);
    try {
      await api("/api/publishing/jobs", { body: { media_file_id: fileId, caption, hashtags: parseTags(tags), destinations: dest } });
      setCaption("");
      setTags("");
      setNotice("Publishing job saved as a draft. Review and approve it below.");
      loadJobs();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const act = async (job: PublishingJob, action: "approve" | "cancel" | "submit") => {
    setError(null);
    setNotice(null);
    if (action === "submit" && !confirm("Send this post to the publishing provider now?")) return;
    try {
      await api(`/api/publishing/jobs/${job.id}/${action}`, { method: "POST" });
      loadJobs();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const check = async () => {
    setChecking(true);
    try {
      const r = await api<{ ok: boolean; message: string }>("/api/publishing/check", { method: "POST" });
      (r.ok ? setNotice : setError)(r.message);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 pb-10 pt-8 sm:px-8 sm:pt-10">
      <div>
        <h1 className="font-display text-4xl text-cream sm:text-5xl">Prepare for publishing</h1>
        <p className="mt-1 text-sm text-muted">Create a post draft, approve it, then download the package or send it to a connected scheduler.</p>
      </div>

      {config && (
        <Alert tone="info" title={config.provider === "none" ? "Manual publishing mode" : `Provider: ${config.provider}`}>
          {config.provider === "none"
            ? "No publishing service is connected. Approved jobs can be downloaded as a package (MP4 + caption.txt) to upload in Metricool or any scheduler."
            : config.submit_enabled
              ? "Submitting is enabled, but only features verified against the provider's documentation are active."
              : "Submitting is turned off on the server. Nothing will be published automatically."}
          {config.provider !== "none" && me?.user.role === "admin" && (
            <Button variant="secondary" className="mt-2 h-8 px-3" loading={checking} onClick={check}>Test connection</Button>
          )}
        </Alert>
      )}
      {error && <Alert>{error}</Alert>}
      {notice && <Alert tone="ok">{notice}</Alert>}

      <Card className="space-y-4">
        <SectionTitle>New post</SectionTitle>
        <Field label="Video">
          {videos === null ? <Spinner /> : (
            <select className={inputClass} value={fileId} onChange={(e) => setFileId(e.target.value)}>
              <option value="">Choose a downloaded or processed video…</option>
              {videos.map((v) => (
                <option key={v.file.id} value={v.file.id}>
                  {v.file.kind === "processed" ? "[processed] " : ""}{v.title.slice(0, 80)} · {v.file.width}×{v.file.height}
                </option>
              ))}
            </select>
          )}
        </Field>
        {fileId && source && (
          <p className="text-xs text-muted">
            {source.caption ? "Prefilled with the original caption extracted from the post. Edit it freely." : "Caption unavailable for the source post."}
            {source.creator?.name && <> Original creator: {source.creator.name}. Credit them when you have permission to repost.</>}
          </p>
        )}
        <Field label="Caption" hint={`${caption.length} / 5000`}>
          <textarea className={cx(inputClass, "h-36 py-2 leading-relaxed")} maxLength={5000} value={caption}
                    onChange={(e) => setCaption(e.target.value)} placeholder="Write the caption for this post…" />
        </Field>
        <Field label="Hashtags" hint="Separate with spaces or commas. # is optional.">
          <input className={inputClass} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="#reels #behindthescenes" />
        </Field>
        {parseTags(tags).length > 0 && (
          <div className="flex flex-wrap gap-1.5">{parseTags(tags).map((t) => <Badge key={t}>{t}</Badge>)}</div>
        )}
        <div>
          <span className="mb-1.5 block text-sm font-medium">Destination accounts</span>
          {config && config.destinations.length === 0 ? (
            <p className="rounded-lg bg-surface-2 p-3 text-sm text-muted">
              No destination accounts are configured. Add them to PUBLISHING_ACCOUNTS in the server&apos;s environment file.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {config?.destinations.map((d) => {
                const on = dest.includes(d.id);
                return (
                  <button key={d.id} type="button" aria-pressed={on}
                          onClick={() => setDest((x) => (on ? x.filter((i) => i !== d.id) : [...x, d.id]))}
                          className={cx("rounded-lg border px-3 py-2 text-sm", on ? "border-accent bg-accent/10" : "border-line hover:border-line-strong")}>
                    <span className="font-medium">{d.label}</span> <span className="text-muted">· {d.network}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <Button onClick={create} loading={saving} disabled={!fileId} className="w-full sm:w-auto">Save draft</Button>
      </Card>

      <section>
        <SectionTitle>Publishing jobs</SectionTitle>
        {jobs.length === 0 ? <EmptyState title="No publishing jobs yet" /> : (
          <ul className="space-y-3">
            {jobs.map((j) => (
              <li key={j.id}>
                <Card className="p-4">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge tone={STATUS_TONE[j.status]}>{j.status}</Badge>
                    <span className="text-faint">#{j.id} · {timeAgo(j.created_at)}</span>
                    {j.destinations.length > 0 && <span className="text-muted">→ {j.destinations.join(", ")}</span>}
                  </div>
                  <p className="mt-2 line-clamp-3 whitespace-pre-wrap break-words text-sm">{j.caption || <span className="text-muted">No caption</span>}</p>
                  {j.hashtags.length > 0 && <p className="mt-1 text-sm text-accent">{j.hashtags.join(" ")}</p>}
                  {j.error && <p className="mt-1 text-sm text-bad">{j.error}</p>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <LinkButton href={fileUrl(j.media_file_id)} className="h-9 px-3">Preview</LinkButton>
                    <LinkButton href={`/api/publishing/jobs/${j.id}/package`} download className="h-9 px-3">Download package</LinkButton>
                    {j.status === "draft" && (
                      <Button className="h-9 px-3" onClick={() => act(j, "approve")}>Approve</Button>
                    )}
                    {j.status === "approved" && (
                      <Button className="h-9 px-3" disabled={!config?.submit_enabled} onClick={() => act(j, "submit")}
                              title={config?.submit_enabled ? "" : "Submitting is disabled on the server"}>
                        Submit
                      </Button>
                    )}
                    {(j.status === "draft" || j.status === "approved") && (
                      <Button variant="ghost" className="h-9 px-3" onClick={() => act(j, "cancel")}>Cancel</Button>
                    )}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
