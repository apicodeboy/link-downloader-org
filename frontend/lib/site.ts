"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { SiteInfo } from "./types";

/** Display name, set at build time (GitHub Actions variable SITE_NAME). */
export const SITE_NAME = process.env.NEXT_PUBLIC_SITE_NAME || "Video Downloader";

let cached: Promise<SiteInfo> | null = null;

/** Public facts about this site (limits, contact) from the server. */
export function useSiteInfo() {
  const [info, setInfo] = useState<SiteInfo | null>(null);
  useEffect(() => {
    cached ??= api<SiteInfo>("/api/site").catch((e) => {
      cached = null;
      throw e;
    });
    cached.then(setInfo).catch(() => {});
  }, []);
  return info;
}

export function minutes(seconds: number | null | undefined): string {
  if (!seconds) return "";
  const m = Math.round(seconds / 60);
  return m >= 60 && m % 60 === 0 ? `${m / 60} hour${m === 60 ? "" : "s"}` : `${m} minutes`;
}
