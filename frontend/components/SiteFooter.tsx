"use client";

import Link from "next/link";
import { useSiteInfo } from "@/lib/site";

export function SiteFooter({ note }: { note?: string }) {
  const site = useSiteInfo();
  return (
    <footer className="mx-auto w-full max-w-5xl space-y-2 px-4 pb-8 text-xs text-faint">
      <p>
        Only download content you own or have permission to use. Private, login-protected and DRM-protected
        content isn&apos;t supported.{note ? ` ${note}` : ""}
      </p>
      <nav className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Site">
        <Link href="/terms" className="hover:text-fg">Terms</Link>
        <Link href="/privacy" className="hover:text-fg">Privacy</Link>
        {site?.contact_email && (
          <a href={`mailto:${site.contact_email}`} className="hover:text-fg">Contact &amp; takedown requests</a>
        )}
      </nav>
    </footer>
  );
}
