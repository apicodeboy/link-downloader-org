"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "./api";
import { isActive } from "./format";
import type { Job } from "./types";

/** Polls a job until it completes or fails. */
export function useJob<R = unknown>(jobId: string | null) {
  const [job, setJob] = useState<Job<R> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const failures = useRef(0);

  useEffect(() => {
    setJob(null);
    setError(null);
    if (!jobId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const j = await api<Job<R>>(`/api/jobs/${jobId}`);
        if (stopped) return;
        failures.current = 0;
        setJob(j);
        setError(null);
        if (isActive(j.status)) timer = setTimeout(tick, j.status === "queued" ? 1500 : 1000);
      } catch (e) {
        if (stopped) return;
        failures.current += 1;
        setError(errorMessage(e));
        timer = setTimeout(tick, Math.min(10000, 1500 * failures.current));
      }
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return { job, error };
}
