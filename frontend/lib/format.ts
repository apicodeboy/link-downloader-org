import type { JobStatus } from "./types";

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function timeUntil(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  if (diff <= 0) return "expired";
  if (diff < 3600) return `in ${Math.max(1, Math.round(diff / 60))} min`;
  return `in ${Math.round(diff / 3600)} h`;
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  analyzing: "Analyzing",
  downloading: "Downloading",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};

export const PLATFORM_LABEL: Record<string, string> = {
  twitter: "X / Twitter",
  instagram: "Instagram",
  facebook: "Facebook",
  tiktok: "TikTok",
  youtube: "YouTube",
  reddit: "Reddit",
  other: "Other",
};

export const CAPTION_SOURCE_LABEL: Record<string, string> = {
  post_text: "Original post text",
  post_title: "Original post title",
  video_description: "Video description",
  video_title: "Video title",
  description: "Description",
  title: "Title",
};

export const isActive = (s: JobStatus) => s === "queued" || s === "analyzing" || s === "downloading" || s === "processing";
