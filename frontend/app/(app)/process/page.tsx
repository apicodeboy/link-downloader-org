"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { JobProgress } from "@/components/JobProgress";
import { Alert, Button, Card, EmptyState, Field, LinkButton, SectionTitle, Spinner, cx, inputClass } from "@/components/ui";
import { api, errorMessage, fileUrl } from "@/lib/api";
import { formatBytes, formatDuration, timeUntil } from "@/lib/format";
import type { Job, MediaFile, Preset, ProcessOptions, ProcessResult } from "@/lib/types";
import { readQueryParam, useAvailableVideos } from "@/lib/useAvailableVideos";
import { useJob } from "@/lib/useJob";

const DEFAULTS: ProcessOptions = {
  aspect: "original",
  fill_mode: "blur",
  watermark_file_id: null,
  watermark_size_pct: 15,
  watermark_opacity: 0.8,
  watermark_margin_pct: 3,
  thumbnails: true,
};

export default function ProcessPage() {
  const videos = useAvailableVideos();
  const [fileId, setFileId] = useState<string | null>(null);
  const [file, setFile] = useState<MediaFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    const q = readQueryParam("file");
    if (q) setFileId(q);
  }, []);

  useEffect(() => {
    if (!fileId) return;
    setFile(null);
    setFileError(null);
    api<MediaFile>(`/api/media/${fileId}`)
      .then((f) => (f.available ? setFile(f) : setFileError("This video has expired. Download it again first.")))
      .catch((e) => setFileError(errorMessage(e)));
  }, [fileId]);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 pb-10 pt-8 sm:px-8 sm:pt-10">
      <div>
        <h1 className="font-display text-4xl text-cream sm:text-5xl">Edit video</h1>
        <p className="mt-1 text-sm text-muted">
          Add your watermark, convert to 9:16 and create thumbnails. Existing creator watermarks are never removed or cropped out.
        </p>
      </div>
      <Card>
        <Field label="Video">
          {videos === null ? (
            <div className="flex h-11 items-center text-muted"><Spinner /></div>
          ) : videos.length === 0 && !fileId ? (
            <EmptyState title="No videos on the server"><Link href="/" className="text-accent hover:underline">Download a video first</Link></EmptyState>
          ) : (
            <select className={inputClass} value={fileId ?? ""} onChange={(e) => setFileId(e.target.value || null)}>
              <option value="">Choose a video…</option>
              {videos.map((v) => (
                <option key={v.file.id} value={v.file.id}>
                  {v.file.kind === "processed" ? "[processed] " : ""}{v.title.slice(0, 80)} · {v.file.width}×{v.file.height}
                </option>
              ))}
              {fileId && !videos.some((v) => v.file.id === fileId) && <option value={fileId}>Selected video</option>}
            </select>
          )}
        </Field>
        {fileError && <div className="mt-3"><Alert>{fileError}</Alert></div>}
      </Card>
      {file && <Editor key={file.id} file={file} />}
    </div>
  );
}

function Editor({ file }: { file: MediaFile }) {
  const [opts, setOpts] = useState<ProcessOptions>(DEFAULTS);
  const [watermarks, setWatermarks] = useState<MediaFile[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const { job, error: pollError } = useJob<ProcessResult>(jobId);

  const set = <K extends keyof ProcessOptions>(k: K, v: ProcessOptions[K]) => setOpts((o) => ({ ...o, [k]: v }));

  const refresh = () => {
    api<{ items: MediaFile[] }>("/api/watermarks").then((r) => setWatermarks(r.items)).catch(() => {});
    api<{ items: Preset[] }>("/api/presets").then((r) => setPresets(r.items)).catch(() => {});
  };
  useEffect(refresh, []);

  const upload = async (f: File) => {
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", f);
      const wm = await api<MediaFile>("/api/watermarks", { form });
      setWatermarks((w) => [wm, ...w]);
      set("watermark_file_id", wm.id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const applyPreset = (id: string) => {
    const p = presets.find((x) => String(x.id) === id);
    if (!p) return;
    setOpts({
      aspect: p.aspect, fill_mode: p.fill_mode, watermark_file_id: p.watermark_file_id,
      watermark_size_pct: p.watermark_size_pct, watermark_opacity: p.watermark_opacity,
      watermark_margin_pct: p.watermark_margin_pct, thumbnails: p.thumbnails,
    });
  };

  const savePreset = async () => {
    if (!presetName.trim()) return;
    try {
      const p = await api<Preset>("/api/presets", { body: { name: presetName.trim(), ...opts } });
      setPresets((list) => [...list, p]);
      setPresetName("");
      setNotice(`Saved preset “${p.name}”.`);
      setTimeout(() => setNotice(null), 2500);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const j = await api<Job>(`/api/media/${file.id}/process`, { body: opts });
      setJobId(j.id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const wm = watermarks.find((w) => w.id === opts.watermark_file_id);
  const vertical = opts.aspect === "9:16";
  // FFmpeg uses the same pixel margin on both edges (a % of width); CSS bottom % is of height.
  const ratio = vertical ? 9 / 16 : file.width && file.height ? file.width / file.height : 16 / 9;
  const busy = !!job && job.status !== "completed" && job.status !== "failed";
  const result = job?.status === "completed" ? job.result : null;
  const nothing = !opts.watermark_file_id && opts.aspect === "original" && !opts.thumbnails;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Card>
        <SectionTitle>Preview</SectionTitle>
        {/* Approximate live preview: the real render happens in FFmpeg on the server. */}
        <div className={cx("relative mx-auto overflow-hidden rounded-xl bg-black", vertical ? "aspect-[9/16] max-h-[70vh]" : "")}
             style={vertical ? undefined : { aspectRatio: file.width && file.height ? `${file.width}/${file.height}` : "16/9" }}>
          {vertical && opts.fill_mode === "blur" && (
            <video src={fileUrl(file.id)} muted playsInline aria-hidden className="absolute inset-0 size-full scale-110 object-cover blur-xl opacity-70" />
          )}
          <video src={fileUrl(file.id)} controls playsInline preload="metadata" className="absolute inset-0 size-full object-contain" />
          {wm && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={fileUrl(wm.id)} alt="" className="pointer-events-none absolute"
                 style={{
                   width: `${opts.watermark_size_pct}%`,
                   right: `${opts.watermark_margin_pct}%`,
                   bottom: `${opts.watermark_margin_pct * ratio}%`,
                   opacity: opts.watermark_opacity,
                   maxHeight: "40%",
                   objectFit: "contain",
                 }} />
          )}
        </div>
        <p className="mt-2 text-xs text-muted">
          Source: {file.width}×{file.height} · {formatDuration(file.duration)} · {formatBytes(file.size_bytes)} · {file.has_audio ? "audio preserved" : "no audio"}
        </p>
      </Card>

      <div className="space-y-6">
        <Card className="space-y-5">
          {presets.length > 0 && (
            <Field label="Preset">
              <select className={inputClass} defaultValue="" onChange={(e) => applyPreset(e.target.value)}>
                <option value="">Load a saved preset…</option>
                {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </Field>
          )}

          <div>
            <span className="mb-1.5 block text-sm font-medium">Watermark (bottom-right)</span>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => set("watermark_file_id", null)}
                      className={cx("h-14 rounded-lg border px-3 text-sm", !opts.watermark_file_id ? "border-accent bg-accent/10" : "border-line")}>
                None
              </button>
              {watermarks.map((w) => (
                <button key={w.id} type="button" onClick={() => set("watermark_file_id", w.id)} title={w.filename}
                        className={cx("grid h-14 w-20 place-items-center rounded-lg border bg-[repeating-conic-gradient(#222_0_25%,#2c2c2c_0_50%)] bg-[length:12px_12px] p-1",
                          opts.watermark_file_id === w.id ? "border-accent ring-2 ring-accent/40" : "border-line")}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={fileUrl(w.id)} alt={w.filename} className="max-h-full max-w-full object-contain" />
                </button>
              ))}
              <Button type="button" variant="secondary" className="h-14" loading={uploading} onClick={() => fileInput.current?.click()}>
                Upload PNG
              </Button>
              <input ref={fileInput} type="file" accept="image/png" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </div>
          </div>

          {opts.watermark_file_id && (
            <div className="grid gap-4 sm:grid-cols-3">
              <Slider label="Size" value={opts.watermark_size_pct} min={2} max={50} step={1} hint="of video width"
                      onChange={(v) => set("watermark_size_pct", v)} />
              <Slider label="Opacity" value={Math.round(opts.watermark_opacity * 100)} min={5} max={100} step={5} hint="100% = solid"
                      onChange={(v) => set("watermark_opacity", v / 100)} />
              <Slider label="Margin" value={opts.watermark_margin_pct} min={0} max={20} step={1} hint="from the edges"
                      onChange={(v) => set("watermark_margin_pct", v)} />
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Aspect ratio" hint="9:16 fits Reels, Shorts and TikTok.">
              <select className={inputClass} value={opts.aspect} onChange={(e) => set("aspect", e.target.value as ProcessOptions["aspect"])}>
                <option value="original">Keep original</option>
                <option value="9:16">9:16 vertical</option>
              </select>
            </Field>
            {vertical && (
              <Field label="Background" hint="The full original frame is kept; nothing is cropped.">
                <select className={inputClass} value={opts.fill_mode} onChange={(e) => set("fill_mode", e.target.value as ProcessOptions["fill_mode"])}>
                  <option value="blur">Blurred video</option>
                  <option value="black">Black bars</option>
                </select>
              </Field>
            )}
          </div>

          <label className="flex items-center gap-3 text-sm">
            <input type="checkbox" className="size-4 accent-[var(--color-accent)]" checked={opts.thumbnails} onChange={(e) => set("thumbnails", e.target.checked)} />
            Generate 3 thumbnails
          </label>

          {error && <Alert>{error}</Alert>}
          {notice && <Alert tone="ok">{notice}</Alert>}
          <Button className="w-full" onClick={start} loading={starting} disabled={busy || nothing}>
            {nothing ? "Choose at least one option" : "Export MP4"}
          </Button>

          <div className="flex gap-2 border-t border-line pt-4">
            <input className={inputClass} placeholder="Preset name" maxLength={100} value={presetName} onChange={(e) => setPresetName(e.target.value)} />
            <Button variant="secondary" className="shrink-0 whitespace-nowrap" onClick={savePreset} disabled={!presetName.trim()}>Save preset</Button>
          </div>
        </Card>

        {job && (
          <Card className="space-y-4">
            <SectionTitle>Export</SectionTitle>
            {job.status !== "completed" && <JobProgress job={job} pollError={pollError} />}
            {result && <ExportResult result={result} />}
          </Card>
        )}
      </div>
    </div>
  );
}

function ExportResult({ result }: { result: ProcessResult }) {
  const [file, setFile] = useState<MediaFile | null>(null);
  useEffect(() => {
    if (result.media_file_id) api<MediaFile>(`/api/media/${result.media_file_id}`).then(setFile).catch(() => {});
  }, [result.media_file_id]);
  return (
    <div className="space-y-4">
      {result.media_file_id && (
        <>
          <video src={fileUrl(result.media_file_id)} controls playsInline className="max-h-[60vh] w-full rounded-lg bg-black" />
          {file && (
            <p className="text-xs text-muted">
              {file.width}×{file.height} · {formatBytes(file.size_bytes)} · {file.has_audio ? "audio preserved" : "no audio"} · deleted {timeUntil(file.expires_at)}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <LinkButton href={fileUrl(result.media_file_id, true)} variant="primary" download>Download MP4</LinkButton>
            <Link href={`/publish?file=${result.media_file_id}`} className="inline-flex h-11 items-center rounded-lg border border-line-strong bg-surface-3 px-4 text-sm hover:bg-line">
              Prepare for publishing
            </Link>
          </div>
        </>
      )}
      {result.thumbnail_file_ids.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Thumbnails</p>
          <div className="grid grid-cols-3 gap-2">
            {result.thumbnail_file_ids.map((id, i) => (
              <a key={id} href={fileUrl(id, true)} download className="group relative overflow-hidden rounded-lg bg-surface-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={fileUrl(id)} alt={`Thumbnail ${i + 1}`} className="aspect-[9/16] w-full object-cover" />
                <span className="absolute inset-x-0 bottom-0 bg-black/60 py-1 text-center text-xs opacity-0 transition-opacity group-hover:opacity-100">Download</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Slider({ label, value, min, max, step, hint, onChange }: {
  label: string; value: number; min: number; max: number; step: number; hint: string; onChange: (v: number) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="flex justify-between"><span className="font-medium">{label}</span><span className="tabular-nums text-muted">{value}%</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 w-full" />
      <span className="text-xs text-faint">{hint}</span>
    </label>
  );
}
