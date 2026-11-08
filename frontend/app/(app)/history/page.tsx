"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Card, EmptyState, LinkButton, Spinner, StatusBadge } from "@/components/ui";
import { api, errorMessage, fileUrl } from "@/lib/api";
import { PLATFORM_LABEL, formatBytes, timeAgo, timeUntil } from "@/lib/format";
import type { HistoryItem } from "@/lib/types";

const PAGE = 25;

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  const load = useCallback(async (off: number) => {
    try {
      const res = await api<{ items: HistoryItem[] }>(`/api/media/history?limit=${PAGE}&offset=${off}`);
      setItems((prev) => (off === 0 ? res.items : [...(prev ?? []), ...res.items]));
      setMore(res.items.length === PAGE);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    load(0);
  }, [load]);

  const remove = async (item: HistoryItem) => {
    if (!item.file || !confirm(`Delete "${item.file.filename}" from the server now?`)) return;
    try {
      await api(`/api/media/${item.file.id}`, { method: "DELETE" });
      setOffset(0);
      load(0);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 pb-10 pt-8 sm:px-8 sm:pt-10">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-4xl text-cream sm:text-5xl">My files</h1>
          <p className="mt-1 text-sm text-muted">Files are deleted from the server after a while. This list stays in your browser.</p>
        </div>
        <Button variant="secondary" onClick={() => { setOffset(0); load(0); }} className="h-9 px-3">Refresh</Button>
      </div>
      {error && <Alert>{error}</Alert>}
      {items === null ? (
        <div className="flex justify-center py-12 text-muted"><Spinner className="size-6" /></div>
      ) : items.length === 0 ? (
        <EmptyState title="No downloads yet">
          <Link href="/" className="text-accent hover:underline">Download your first video</Link>
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => {
            const f = item.file;
            const available = f?.available;
            return (
              <li key={item.id}>
                <Card className="p-3 sm:p-4">
                  <div className="flex gap-3 sm:gap-4">
                    <div className="grid size-16 shrink-0 place-items-center overflow-hidden rounded-lg bg-surface-2 sm:size-24">
                      {item.thumbnail_file_id ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={fileUrl(item.thumbnail_file_id)} alt="" className="size-full object-cover" />
                      ) : (
                        <span className="text-xs text-faint">{item.kind === "process" ? "Processed" : "Video"}</span>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={item.status} />
                        {item.platform && <Badge>{PLATFORM_LABEL[item.platform] ?? item.platform}</Badge>}
                        {item.kind === "process" && <Badge tone="info">Processed</Badge>}
                        <span className="text-xs text-faint">{timeAgo(item.created_at)}</span>
                      </div>
                      <p className="mt-1.5 truncate font-medium">{item.title ?? item.source_url ?? "Untitled"}</p>
                      <p className="mt-0.5 text-xs text-muted">
                        {[item.format_label, formatBytes(item.size_bytes)].filter((x) => x && x !== "—").join(" · ")}
                        {f && (available ? ` · deleted ${timeUntil(f.expires_at)}` : " · file expired")}
                      </p>
                      {item.status === "failed" && item.error_message && (
                        <p className="mt-1 text-sm text-bad">{item.error_message}</p>
                      )}
                    </div>
                  </div>
                  {available && f && (
                    <div className="mt-3 flex flex-wrap gap-2 sm:pl-28">
                      <Button variant="secondary" className="h-9 px-3" onClick={() => setPreview(preview === f.id ? null : f.id)}>
                        {preview === f.id ? "Hide preview" : "Preview"}
                      </Button>
                      <LinkButton href={fileUrl(f.id, true)} download className="h-9 px-3">Download MP4</LinkButton>
                      <Link href={`/process?file=${f.id}`} className="inline-flex h-9 items-center rounded-lg px-3 text-sm text-muted hover:bg-surface-3 hover:text-fg">Process</Link>
                      <Link href={`/publish?file=${f.id}`} className="inline-flex h-9 items-center rounded-lg px-3 text-sm text-muted hover:bg-surface-3 hover:text-fg">Publish</Link>
                      <Button variant="danger" className="h-9 px-3" onClick={() => remove(item)}>Delete</Button>
                    </div>
                  )}
                  {preview && f && preview === f.id && (
                    <video src={fileUrl(f.id)} controls playsInline autoPlay className="mt-3 max-h-[70vh] w-full rounded-lg bg-black" />
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      {more && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => { const o = offset + PAGE; setOffset(o); load(o); }}>Load more</Button>
        </div>
      )}
    </div>
  );
}
