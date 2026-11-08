"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, api, errorMessage, setCsrfToken, setIdentityReady, setUnauthorizedHandler } from "@/lib/api";
import type { Me } from "@/lib/types";
import { SITE_NAME } from "@/lib/site";
import { Frame, Wordmark } from "./Frame";
import { IconActivity, IconDownload, IconEdit, IconFiles, IconHelp, IconLogout, IconSend } from "./Icons";
import { SiteFooter } from "./SiteFooter";
import { Spinner, cx } from "./ui";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);

// Order mirrors the design: utility icons first, the dark primary action last.
const NAV = [
  { href: "/history", label: "My files", Icon: IconFiles, adminOnly: false },
  { href: "/process", label: "Edit", Icon: IconEdit, adminOnly: false },
  { href: "/jobs", label: "Activity", Icon: IconActivity, adminOnly: false },
  { href: "/publish", label: "Publish", Icon: IconSend, adminOnly: true },
  { href: "/", label: "Download", Icon: IconDownload, adminOnly: false, primary: true },
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
      <Frame>
        <div className="flex flex-1 items-center justify-center px-4 text-center text-muted" aria-busy={loading}>
          {startError ? <p className="max-w-sm text-sm">{startError}</p> : <Spinner className="size-6" />}
        </div>
        <div hidden>{children}</div>
      </Frame>
    );
  }

  const isGuest = me.user.role === "guest";

  return (
    <MeContext.Provider value={me}>
      <Frame
        header={
          <header className="relative z-20 grid grid-cols-[1fr_auto] items-center gap-y-4 px-5 pt-5 sm:px-10 sm:pt-8 lg:grid-cols-[1fr_auto_1fr]">
            <Link href="/" className="justify-self-start" aria-label={`${SITE_NAME} home`}>
              <Wordmark name={SITE_NAME} />
            </Link>
            <nav aria-label="Main"
                 className="glass col-span-2 row-start-2 flex items-center gap-1 justify-self-center rounded-2xl p-1.5 lg:col-span-1 lg:col-start-2 lg:row-start-1">
              {NAV.filter((n) => !n.adminOnly || me.user.role === "admin").map((n) => {
                const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
                return (
                  <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined} title={n.label}
                        aria-label={n.label}
                        className={cx(
                          "flex h-10 items-center gap-2 rounded-xl px-3 text-sm font-medium transition-colors",
                          n.primary
                            ? "bg-ink text-cream shadow-[0_6px_16px_-6px_rgba(0,0,0,.6)] hover:bg-black"
                            : active ? "bg-cream/30 text-fg" : "text-fg/80 hover:bg-cream/15 hover:text-fg",
                        )}>
                    <n.Icon className="size-[18px]" />
                    <span className={cx(active || n.primary ? "inline" : "hidden md:inline")}>{n.label}</span>
                  </Link>
                );
              })}
            </nav>
            <div className="flex items-center gap-2 justify-self-end lg:col-start-3">
              {isGuest ? (
                <Link href="/#faq" title="Questions" aria-label="Questions"
                      className="glass grid size-11 place-items-center rounded-xl text-fg/90 hover:text-fg">
                  <IconHelp className="size-[18px]" />
                </Link>
              ) : (
                <button onClick={logout} title={`Sign out ${me.user.username}`} aria-label="Sign out"
                        className="glass flex h-11 items-center gap-2 rounded-xl px-3 text-sm text-fg/90 hover:text-fg">
                  <span className="hidden sm:inline">{me.user.username}</span>
                  <IconLogout className="size-[18px]" />
                </button>
              )}
            </div>
          </header>
        }
        footer={<SiteFooter note={isGuest ? "Your files and history are private to this browser." : undefined} />}
      >
        <main className="relative flex w-full flex-1 flex-col">{children}</main>
      </Frame>
    </MeContext.Provider>
  );
}
