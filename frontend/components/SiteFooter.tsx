"use client";

import Link from "next/link";
import { useSiteInfo } from "@/lib/site";

/** Sits on the olive frame, below the card. */
export function SiteFooter({ note }: { note?: string }) {
  const site = useSiteInfo();
  return (
    <footer className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-3 py-5 text-xs text-frame-ink/75 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <p className="max-w-2xl">
        Only download content you own or have permission to use. Private, login-protected and DRM-protected
        content isn&apos;t supported.{note ? ` ${note}` : ""}
      </p>
      <nav className="flex shrink-0 flex-wrap gap-x-4 gap-y-1 font-medium" aria-label="Site">
        <Link href="/terms" className="hover:text-frame-ink">Terms</Link>
        <Link href="/privacy" className="hover:text-frame-ink">Privacy</Link>
        {site?.contact_email && (
          <a href={`mailto:${site.contact_email}`} className="hover:text-frame-ink">Contact</a>
        )}
      </nav>
    </footer>
  );
}
