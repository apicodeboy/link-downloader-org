"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useMe } from "@/components/AppShell";
import { JobProgress } from "@/components/JobProgress";
import { EXAMPLE_URL, Hero, useBrandCycle } from "@/components/Hero";
import { IconArrow } from "@/components/Icons";
import { Alert, Badge, Button, Card, CopyButton, LinkButton, SectionTitle, Spinner, cx } from "@/components/ui";
import { api, errorMessage, fileUrl } from "@/lib/api";
import { CAPTION_SOURCE_LABEL, PLATFORM_LABEL, formatBytes, formatDuration, timeUntil } from "@/lib/format";
import type { AnalysisResult, DownloadResult, FormatOption, Job } from "@/lib/types";
import { minutes, useSiteInfo } from "@/lib/site";
import { useJob } from "@/lib/useJob";

export default function DashboardPage() {
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [downloadId, setDownloadId] = useState<string | null>(null);

  const analysis = useJob<AnalysisResult>(analysisId);
  const download = useJob<DownloadResult>(downloadId);

  const me = useMe();
  const startAnalysis = useCallback(async (target: string) => {
    setSubmitting(true);
    setFormError(null);
    setDownloadId(null);
    try {
      const job = await api<Job>("/api/media/analyze", { body: { url: target } });
      setAnalysisId(job.id);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }, []);

  const analyze = (e: FormEvent) => {
    e.preventDefault();
    startAnalysis(url);
  };

  // Links shared to the site (phone share sheet, bookmarklet, ?url=…) start right away.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (autoStarted.current || !me) return;
    const params = new URLSearchParams(window.location.search);
    const shared = params.get("url") || params.get("text")?.match(/https?:\/\/\S+/)?.[0];
    if (!shared) return;
    autoStarted.current = true;
    setUrl(shared);
    window.history.replaceState(null, "", "/");
    startAnalysis(shared);
  }, [me, startAnalysis]);

  const paste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) setUrl(text.trim());
    } catch {
      setFormError("Your browser blocked clipboard access. Long-press the field and paste instead.");
    }
  };

  const result = analysis.job?.status === "completed" ? analysis.job.result : null;
  const [brand, pickBrand] = useBrandCycle(url.length > 0 || submitting);
  const urlInput = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (result) resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [result]);

  return (
    <>
      <Hero brand={brand} headline="Save any video"
            onPickBrand={(b) => { pickBrand(b); urlInput.current?.focus(); }}>
        <form onSubmit={analyze}
              className="w-full rounded-[1.75rem] bg-cream p-3 text-cream-ink shadow-[0_30px_60px_-25px_rgba(10,15,5,.8)] sm:p-4">
          <label htmlFor="url" className="sr-only">Video link</label>
          <div className="relative">
            <input id="url" ref={urlInput} type="url" inputMode="url" placeholder={EXAMPLE_URL[brand]}
                   autoComplete="off" autoCapitalize="none" spellCheck={false} required value={url}
                   onChange={(e) => setUrl(e.target.value)}
                   className="h-12 w-full rounded-2xl border border-cream-ink/15 bg-white/70 pl-4 pr-20 text-base text-cream-ink placeholder:text-cream-ink/40 focus:border-cream-ink/40 focus:outline-none focus:ring-2 focus:ring-cream-ink/15" />
            <button type="button" onClick={paste}
                    className="absolute right-1.5 top-1.5 h-9 rounded-xl px-3 text-xs font-semibold text-cream-ink/70 hover:bg-cream-ink/10 hover:text-cream-ink">
              Paste
            </button>
          </div>
          <button type="submit" disabled={submitting}
                  className="mt-2.5 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-ink text-sm font-semibold text-cream shadow-[0_8px_20px_-8px_rgba(0,0,0,.6)] transition-colors hover:bg-black disabled:opacity-60">
            {submitting ? <Spinner /> : null}
            Analyze video
            {!submitting && <IconArrow className="size-4" />}
          </button>
          {me && (
            <p className="mt-2.5 text-center text-[11px] text-cream-ink/60">
              Up to {minutes(me.limits.max_duration_seconds)} · {me.limits.max_filesize_mb} MB · files deleted after{" "}
              {minutes(me.limits.retention_minutes * 60)}
            </p>
          )}
        </form>
        {formError && <div className="mt-3 w-full"><Alert>{formError}</Alert></div>}
        {analysis.job && analysis.job.status !== "completed" && (
          <div className="glass mt-3 w-full rounded-2xl p-3">
            <JobProgress job={analysis.job} pollError={analysis.error} onRetry={() => startAnalysis(url)} />
          </div>
        )}
      </Hero>

      <div ref={resultsRef} className="mx-auto w-full max-w-5xl scroll-mt-6 space-y-6 px-4 pb-10 sm:px-8">
      {result && analysis.job && (
        <AnalysisView
          key={analysis.job.id}
          analysisJob={analysis.job as Job<AnalysisResult>}
          result={result}
          onDownload={setDownloadId}
          downloadJob={download.job}
          downloadPollError={download.error}
        />
      )}

      {!analysisId && <HowItWorks />}
      </div>
    </>
  );
}

function HowItWorks() {
  const site = useSiteInfo();
  const g = site?.guest_limits;
  const faq: [string, string][] = [
    ["Which sites work?", `${(site?.platforms ?? ["X / Twitter", "Instagram", "Facebook", "TikTok", "YouTube", "Reddit"]).join(", ")}. Support varies: platforms change often, and some videos can't be fetched without logging in.`],
    ["Why did a video fail?", "Private, login-only, age-restricted, members-only and DRM-protected videos can't be downloaded. Sometimes a platform is temporarily rate-limiting us. Wait a few minutes and try again."],
    ["How long are my files kept?", g ? `Downloads and edits are deleted from the server after ${minutes(g.retention_minutes * 60)}. Your list of past downloads stays in this browser for ${site?.history_days} days.` : "Files are deleted automatically after a short time."],
    ["Do I need an account?", "No. Your files are private to this browser. Nobody else can see them."],
    ["Is there a limit?", g ? `Videos up to ${minutes(g.max_duration_seconds)} and ${g.max_filesize_mb} MB, and ${g.max_pending_jobs} jobs at a time. Editing works for videos up to ${minutes(g.process_max_duration_seconds)}.` : "Yes, to keep the site fast for everyone."],
    ["Can I use downloaded videos however I like?", "Only if you own them or have the creator's permission. Respect copyright and the platform's terms."],
  ];
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ["1. Paste a link", "Copy the post's link from the app or website, or share it straight to this site from your phone."],
          ["2. Pick a quality", "See the caption, creator and length, then choose a resolution. Audio is always included."],
          ["3. Save the MP4", "Download it, copy the caption, or add your watermark and convert to 9:16 in Edit."],
        ].map(([t, d]) => (
          <div key={t} className="rounded-3xl bg-cream p-5 text-cream-ink shadow-[0_20px_40px_-25px_rgba(0,0,0,.7)]">
            <p className="font-display text-2xl">{t}</p>
            <p className="mt-1 text-sm text-cream-ink/70">{d}</p>
          </div>
        ))}
      </div>
      <section aria-labelledby="faq" id="faq" className="scroll-mt-6">
        <h2 id="faq" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Questions</h2>
        <div className="divide-y divide-cream/10 rounded-3xl border border-cream/10 bg-surface/75 backdrop-blur-sm">
          {faq.map(([q, a]) => (
            <details key={q} className="group px-4 py-3">
              <summary className="cursor-pointer list-none text-sm font-medium marker:hidden">
                <span className="mr-2 inline-block text-faint transition-transform group-open:rotate-90">›</span>{q}
              </summary>
              <p className="mt-2 pl-4 text-sm text-muted">{a}</p>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}

function AnalysisView({ analysisJob, result, onDownload, downloadJob, downloadPollError }: {
  analysisJob: Job<AnalysisResult>;
  result: AnalysisResult;
  onDownload: (id: string) => void;
  downloadJob: Job<DownloadResult> | null;
  downloadPollError: string | null;
}) {
  const options = result.formats;
  const [formatId, setFormatId] = useState(options[0]?.format_id ?? "best");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const job = await api<Job>("/api/media/download", { body: { analysis_job_id: analysisJob.id, format_id: formatId } });
      onDownload(job.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };

  const busy = downloadJob != null && !["completed", "failed"].includes(downloadJob.status);
  const editLimit = result.process_max_duration_seconds;
  const canEdit = !editLimit || !result.duration || result.duration <= editLimit;
  const done = downloadJob?.status === "completed" ? downloadJob.result : null;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Card className="space-y-4">
        <div className="overflow-hidden rounded-xl bg-surface-2">
          {done ? (
            <video key={done.media_file_id} src={fileUrl(done.media_file_id)} controls playsInline preload="metadata"
                   className="mx-auto max-h-[70vh] w-full bg-black" />
          ) : result.thumbnail_file_id ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={fileUrl(result.thumbnail_file_id)} alt="Video thumbnail" className="mx-auto max-h-[60vh] w-full object-contain" />
          ) : (
            <div className="grid aspect-video place-items-center text-sm text-faint">No thumbnail available</div>
          )}
        </div>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info">{PLATFORM_LABEL[result.platform] ?? result.platform}</Badge>
            <Badge>{formatDuration(result.duration)}</Badge>
            {result.entry_count > 1 && <Badge tone="warn">1 of {result.entry_count} videos in this post</Badge>}
            {result.cached && <Badge tone="ok">Ready instantly</Badge>}
          </div>
          <h2 className="mt-3 text-lg font-semibold leading-snug break-words">
            {result.title ?? "Untitled video"}
          </h2>
          {result.title_is_generated && (
            <p className="mt-1 text-xs text-faint">Title generated by yt-dlp from the post, not written by the creator.</p>
          )}
          {(result.creator.name || result.creator.handle) && (
            <p className="mt-1 text-sm text-muted">
              {result.creator.name}{result.creator.handle && result.creator.handle !== result.creator.name && ` · @${result.creator.handle.replace(/^@/, "")}`}
            </p>
          )}
          {result.webpage_url && (
            <a href={result.webpage_url} target="_blank" rel="noopener noreferrer" className="mt-1 block truncate text-xs text-accent hover:underline">
              {result.webpage_url}
            </a>
          )}
        </div>
      </Card>

      <div className="space-y-6">
        <Card>
          <SectionTitle aside={<CopyButton text={result.caption ?? ""} label="Copy Caption" disabled={!result.caption} />}>
            Caption
          </SectionTitle>
          {result.caption ? (
            <>
              <p className="mb-2 text-xs text-faint">{CAPTION_SOURCE_LABEL[result.caption_source ?? ""] ?? "Extracted text"} · extracted, not generated</p>
              <div className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3 text-sm leading-relaxed">
                {result.caption}
              </div>
            </>
          ) : (
            <p className="rounded-lg bg-surface-2 p-3 text-sm text-muted">Caption unavailable</p>
          )}
          {result.hashtags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {result.hashtags.map((h) => <Badge key={h}>{h}</Badge>)}
            </div>
          )}
          {result.description && result.description !== result.caption && (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-muted">Description</summary>
              <div className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-3">{result.description}</div>
            </details>
          )}
        </Card>

        <Card>
          <SectionTitle>Resolution</SectionTitle>
          {result.too_long ? (
            <Alert tone="warn">
              This video is {formatDuration(result.duration)} long. The server limit is {formatDuration(result.max_duration_seconds)}.
            </Alert>
          ) : result.is_live ? (
            <Alert tone="warn">Live streams can&apos;t be downloaded while they&apos;re live.</Alert>
          ) : (
            <>
              <fieldset className="grid gap-2 sm:grid-cols-2" disabled={busy}>
                <legend className="sr-only">Choose a resolution</legend>
                {options.map((o) => <FormatChoice key={o.format_id} option={o} checked={formatId === o.format_id} onSelect={setFormatId} />)}
              </fieldset>
              <Button onClick={start} loading={starting} disabled={busy} className="mt-4 w-full">Download MP4</Button>
            </>
          )}
          {error && <div className="mt-3"><Alert>{error}</Alert></div>}
          {downloadJob && downloadJob.status !== "completed" && (
            <div className="mt-4"><JobProgress job={downloadJob} pollError={downloadPollError} onRetry={start} /></div>
          )}
          {done && (
            <div className="mt-4 space-y-3 rounded-xl border border-ok/30 bg-ok/5 p-4">
              <p className="text-sm">
                <span className="font-medium text-ok">Ready.</span>{" "}
                {done.width}×{done.height} · {formatBytes(done.size_bytes)} · {done.has_audio ? "with audio" : "no audio track in source"}
              </p>
              <p className="text-xs text-muted">Deleted from the server automatically {timeUntil(done.expires_at)}.</p>
              <div className="flex flex-wrap gap-2">
                <LinkButton href={fileUrl(done.media_file_id, true)} variant="primary" download>Save MP4</LinkButton>
                {canEdit && (
                  <Link href={`/process?file=${done.media_file_id}`}
                        className="inline-flex h-11 items-center rounded-lg border border-line-strong bg-surface-3 px-4 text-sm hover:bg-line">
                    Edit video
                  </Link>
                )}
              </div>
              {!canEdit && (
                <p className="text-xs text-faint">
                  Editing is available for videos up to {minutes(result.process_max_duration_seconds)}.
                </p>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function FormatChoice({ option, checked, onSelect }: { option: FormatOption; checked: boolean; onSelect: (id: string) => void }) {
  return (
    <label className={cx(
      "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors",
      checked ? "border-accent bg-accent/10" : "border-line hover:border-line-strong",
    )}>
      <input type="radio" name="format" className="accent-[var(--color-accent)]" checked={checked} onChange={() => onSelect(option.format_id)} />
      <span className="flex-1">
        <span className="font-medium">{option.label}</span>
        <span className="block text-xs text-muted">
          {[option.vcodec, option.filesize ? `~${formatBytes(option.filesize)}` : null, !option.has_audio ? "no audio" : null]
            .filter(Boolean).join(" · ") || (option.format_id === "best" ? "Highest quality, merged to MP4" : "MP4")}
        </span>
      </span>
    </label>
  );
}
