"use client";

import type { ReactNode } from "react";
import { useSiteInfo } from "@/lib/site";
import type { SiteInfo } from "@/lib/types";
import { Spinner } from "./ui";

export function LegalPage({ title, updated, children }: {
  title: string;
  updated: string;
  children: (site: SiteInfo) => ReactNode;
}) {
  const site = useSiteInfo();
  return (
    <article className="space-y-5 text-sm leading-relaxed text-fg/90 [&_h2]:mt-8 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-fg [&_li]:ml-5 [&_li]:list-disc [&_a]:text-accent">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        <p className="mt-1 text-xs text-faint">Last updated {updated}</p>
      </header>
      {site ? children(site) : <Spinner className="size-5 text-muted" />}
    </article>
  );
}

export function Contact({ site }: { site: SiteInfo }) {
  return site.contact_email
    ? <a href={`mailto:${site.contact_email}`}>{site.contact_email}</a>
    : <span>the site operator</span>;
}

export const mins = (s: number | null | undefined) => (s ? Math.round(s / 60) : 0);
