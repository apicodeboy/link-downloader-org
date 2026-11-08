"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { HistoryItem, MediaFile } from "./types";

export interface VideoChoice {
  file: MediaFile;
  title: string;
}

/** Downloaded or processed videos that are still on the server. */
export function useAvailableVideos() {
  const [videos, setVideos] = useState<VideoChoice[] | null>(null);
  useEffect(() => {
    api<{ items: HistoryItem[] }>("/api/media/history?limit=100")
      .then((r) =>
        setVideos(
          r.items
            .filter((i) => i.file?.available && (i.file.kind === "video" || i.file.kind === "processed"))
            .map((i) => ({ file: i.file as MediaFile, title: i.title ?? (i.file as MediaFile).filename })),
        ),
      )
      .catch(() => setVideos([]));
  }, []);
  return videos;
}

export function readQueryParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}
