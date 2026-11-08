"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, api, errorMessage, setCsrfToken, setIdentityReady, setUnauthorizedHandler } from "@/lib/api";
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

// One identity request per page load, even if effects run twice (React dev mode). This
// matters in open mode, where the first call creates the visitor's guest identity.
let meRequest: Promise<Me> | null = null;
function loadMe(): Promise<Me> {
  meRequest ??= api<Me>("/api/auth/me").catch((e) => {
    meRequest = null;
    throw e;
  });
  return meRequest;
}

/** Forget the cached identity (after signing in or out). */
export function resetIdentity() {
  meRequest = null;
}

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

  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    // Open mode: /api/auth/me gives every new browser a private guest identity, so there is
    // no sign-in. If that identity later expires, a reload simply creates a fresh one.
    let mode: Me["mode"] | null = null;
    setUnauthorizedHandler(() => (mode === "open" ? window.location.reload() : toLogin()));
    loadMe()
      .then((m) => {
        mode = m.mode;
        setCsrfToken(m.csrf_token);
        setIdentityReady();
        setMe(m);
      })
      .catch((e) => (e instanceof ApiError && e.status === 401 ? toLogin() : setStartError(errorMessage(e))))
      .finally(() => setLoading(false));
    return () => setUnauthorizedHandler(null);
  }, [toLogin]);

  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      meRequest = null;
      if (me?.mode === "open") window.location.assign("/");
      else toLogin();
    }
  };

  // Pages always render (so Next.js can prerender their shell) but stay hidden until the
  // identity is known. In login mode an unauthenticated visitor is sent to /login.
  if (loading || !me) {
    return (
      <>
        <div className="flex flex-1 items-center justify-center px-4 text-center text-muted" aria-busy={loading}>
          {startError ? <p className="max-w-sm text-sm">{startError}</p> : <Spinner className="size-6" />}
        </div>
        <div hidden>{children}</div>
      </>
    );
  }

  const isGuest = me.user.role === "guest";

  return (
    <MeContext.Provider value={me}>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 pt-3 sm:pt-0 sm:h-16 flex-wrap sm:flex-nowrap">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg">▼</span>
            <span>Video Downloader</span>
          </Link>
          {!isGuest && (
            <div className="ml-auto flex items-center gap-2 text-sm sm:order-last">
              <span className="hidden text-muted sm:inline">{me.user.username}</span>
              <button onClick={logout} className="rounded-lg px-3 h-9 text-muted hover:bg-surface-3 hover:text-fg">Sign out</button>
            </div>
          )}
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
        {isGuest && " Your downloads and history are tied to this browser."}
      </footer>
    </MeContext.Provider>
  );
}
