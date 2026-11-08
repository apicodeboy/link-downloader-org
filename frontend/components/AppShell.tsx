"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrfToken, setUnauthorizedHandler } from "@/lib/api";
import type { Me } from "@/lib/types";
import { Spinner, cx } from "./ui";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

const NAV = [
  { href: "/", label: "Download" },
  { href: "/history", label: "History" },
  { href: "/process", label: "Process" },
  { href: "/publish", label: "Publish" },
  { href: "/jobs", label: "Jobs" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const toLogin = useCallback(() => {
    setCsrfToken("");
    const next = typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
    router.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [router]);

  useEffect(() => {
    setUnauthorizedHandler(toLogin);
    api<Me>("/api/auth/me")
      .then((m) => {
        setCsrfToken(m.csrf_token);
        setMe(m);
      })
      .catch(() => toLogin())
      .finally(() => setLoading(false));
    return () => setUnauthorizedHandler(null);
  }, [toLogin]);

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      toLogin();
    }
  };

  // Pages always render (so Next.js can prerender their shell) but stay hidden until the
  // session is confirmed; an unauthenticated visitor is redirected to /login.
  if (loading || !me) {
    return (
      <>
        <div className="flex flex-1 items-center justify-center text-muted" aria-busy="true">
          <Spinner className="size-6" />
        </div>
        <div hidden>{children}</div>
      </>
    );
  }

  return (
    <MeContext.Provider value={me}>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 pt-3 sm:pt-0 sm:h-16 flex-wrap sm:flex-nowrap">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg">▼</span>
            <span>Video Downloader</span>
          </Link>
          <div className="ml-auto flex items-center gap-2 text-sm sm:order-last">
            <span className="hidden text-muted sm:inline">{me.user.username}</span>
            <button onClick={logout} className="rounded-lg px-3 h-9 text-muted hover:bg-surface-3 hover:text-fg">Sign out</button>
          </div>
          <nav className="-mx-4 flex w-[calc(100%+2rem)] gap-1 overflow-x-auto px-4 pb-2 sm:mx-0 sm:w-auto sm:pb-0 sm:ml-6" aria-label="Main">
            {NAV.map((n) => {
              const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
              return (
                <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
                      className={cx("shrink-0 rounded-lg px-3 py-2 text-sm transition-colors",
                        active ? "bg-surface-3 text-fg" : "text-muted hover:text-fg")}>
                  {n.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:py-8">{children}</main>
      <footer className="mx-auto w-full max-w-5xl px-4 pb-8 text-xs text-faint">
        Only download content you own or are authorized to use. Private, login-protected and DRM-protected content is not supported.
      </footer>
    </MeContext.Provider>
  );
}
