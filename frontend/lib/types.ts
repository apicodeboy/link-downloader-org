export type JobStatus = "queued" | "analyzing" | "downloading" | "processing" | "completed" | "failed";
export type JobKind = "analyze" | "download" | "process";

export interface ApiErrorBody {
  code: string;
  message: string;
}

export interface FormatOption {
  format_id: string;
  label: string;
  height: number | null;
  width: number | null;
  fps: number | null;
  ext: string | null;
  vcodec: string | null;
  has_audio: boolean;
  needs_merge: boolean;
  filesize: number | null;
}

export interface Creator {
  name: string | null;
  handle: string | null;
  url: string | null;
}

export interface AnalysisResult {
  platform: string;
  caption: string | null;
  caption_source: "post_text" | "post_title" | "video_description" | "video_title" | "description" | "title" | null;
  caption_available: boolean;
  title: string | null;
  title_is_generated: boolean;
  description: string | null;
  hashtags: string[];
  tags: string[];
  creator: Creator;
  id: string | null;
  extractor: string | null;
  webpage_url: string | null;
  duration: number | null;
  upload_date: string | null;
  view_count: number | null;
  like_count: number | null;
  is_live: boolean;
  formats: FormatOption[];
  entry_count: number;
  too_long: boolean;
  max_duration_seconds: number;
  thumbnail_file_id?: string;
  warnings?: string[];
}

export interface DownloadResult {
  media_file_id: string;
  filename: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  vcodec: string | null;
  acodec: string | null;
  title: string | null;
  caption: string | null;
  expires_at: string;
  has_audio: boolean;
}

export interface ProcessResult {
  media_file_id: string | null;
  thumbnail_file_ids: string[];
  width?: number;
  height?: number;
  duration?: number;
  has_audio?: boolean;
}

export interface Job<R = unknown> {
  id: string;
  kind: JobKind;
  status: JobStatus;
  progress: number;
  stage: string | null;
  source_url: string | null;
  resolved_url: string | null;
  platform: string | null;
  parent_job_id: string | null;
  input_file_id: string | null;
  options: Record<string, unknown>;
  result: R | null;
  error: ApiErrorBody | null;
  error_detail?: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface MediaFile {
  id: string;
  kind: "video" | "processed" | "thumbnail" | "watermark";
  job_id: string | null;
  parent_file_id: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  vcodec: string | null;
  acodec: string | null;
  has_audio: boolean | null;
  available: boolean;
  created_at: string;
  expires_at: string | null;
  url: string;
  children?: MediaFile[];
  source?: {
    title: string | null;
    caption: string | null;
    caption_source: string | null;
    hashtags: string[];
    platform: string | null;
    webpage_url: string | null;
    creator: Creator | null;
  } | null;
}

export interface HistoryItem {
  id: number;
  job_id: string;
  kind: "download" | "process";
  status: "completed" | "failed";
  source_url: string | null;
  platform: string | null;
  title: string | null;
  format_label: string | null;
  size_bytes: number | null;
  error_message: string | null;
  created_at: string;
  file: MediaFile | null;
  thumbnail_file_id: string | null;
}

export interface ProcessOptions {
  aspect: "original" | "9:16";
  fill_mode: "blur" | "black";
  watermark_file_id: string | null;
  watermark_size_pct: number;
  watermark_opacity: number;
  watermark_margin_pct: number;
  thumbnails: boolean;
}

export interface Preset extends ProcessOptions {
  id: number;
  name: string;
  watermark_position: string;
}

export interface Destination {
  id: string;
  network: string;
  label: string;
}

export interface PublishingConfig {
  provider: string;
  provider_configured: boolean;
  submit_enabled: boolean;
  destinations: Destination[];
}

export interface PublishingJob {
  id: number;
  media_file_id: string;
  provider: string;
  caption: string;
  hashtags: string[];
  destinations: string[];
  scheduled_at: string | null;
  status: "draft" | "approved" | "submitted" | "failed" | "cancelled";
  approved_at: string | null;
  provider_ref: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Me {
  user: { id: number; username: string; role: string };
  csrf_token: string;
  expires_at: string;
}
