"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useState } from "react";
import { STATUS_LABEL, isActive } from "@/lib/format";
import type { JobStatus } from "@/lib/types";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "primary",
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-fg hover:bg-accent-strong font-semibold",
    secondary: "bg-cream/10 text-fg hover:bg-cream/20 border border-cream/15",
    ghost: "text-muted hover:text-fg hover:bg-surface-3",
    danger: "text-bad hover:bg-bad/10 border border-bad/40",
  };
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 h-11 text-sm transition-colors",
        "disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        styles[variant],
        className,
      )}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function LinkButton({ href, children, variant = "secondary", download, className }: {
  href: string; children: ReactNode; variant?: Variant; download?: boolean; className?: string;
}) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accent-fg hover:bg-accent-strong font-semibold",
    secondary: "bg-cream/10 text-fg hover:bg-cream/20 border border-cream/15",
    ghost: "text-muted hover:text-fg hover:bg-surface-3",
    danger: "text-bad hover:bg-bad/10 border border-bad/40",
  };
  return (
    <a href={href} download={download || undefined}
       className={cx("inline-flex items-center justify-center gap-2 rounded-xl px-4 h-11 text-sm transition-colors", styles[variant], className)}>
      {children}
    </a>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cx("inline-block size-4 rounded-full border-2 border-current border-r-transparent animate-spin", className)} />
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-3xl border border-cream/10 bg-surface/75 p-4 shadow-[0_20px_50px_-30px_rgba(0,0,0,.6)] backdrop-blur-sm sm:p-6", className)}>
      {children}
    </section>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{children}</h2>
      {aside}
    </div>
  );
}

const STATUS_STYLE: Record<JobStatus, string> = {
  queued: "bg-surface-3 text-muted",
  analyzing: "bg-info/15 text-info",
  downloading: "bg-accent/15 text-accent",
  processing: "bg-warn/15 text-warn",
  completed: "bg-ok/15 text-ok",
  failed: "bg-bad/15 text-bad",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", STATUS_STYLE[status])}>
      {isActive(status) && <span className="size-1.5 rounded-full bg-current animate-pulse" />}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" | "ok" | "bad" | "info" }) {
  const tones = {
    neutral: "bg-surface-3 text-muted",
    warn: "bg-warn/15 text-warn",
    ok: "bg-ok/15 text-ok",
    bad: "bg-bad/15 text-bad",
    info: "bg-info/15 text-info",
  };
  return <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function ProgressBar({ value, active }: { value: number; active?: boolean }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      {active && pct < 3 ? (
        <div className="h-full w-2/5 rounded-full bg-accent/70" style={{ animation: "indeterminate 1.2s ease-in-out infinite" }} />
      ) : (
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
      )}
    </div>
  );
}

export function Alert({ tone = "bad", title, children }: { tone?: "bad" | "warn" | "info" | "ok"; title?: string; children: ReactNode }) {
  const tones = {
    bad: "border-bad/40 bg-bad/10 text-bad",
    warn: "border-warn/40 bg-warn/10 text-warn",
    info: "border-info/40 bg-info/10 text-info",
    ok: "border-ok/40 bg-ok/10 text-ok",
  };
  return (
    <div role={tone === "bad" ? "alert" : "status"} className={cx("rounded-xl border px-4 py-3 text-sm", tones[tone])}>
      {title && <p className="font-semibold">{title}</p>}
      <div className={cx(title && "mt-0.5", "text-fg/90")}>{children}</div>
    </div>
  );
}

export function CopyButton({ text, label = "Copy", disabled }: { text: string; label?: string; disabled?: boolean }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      // Fallback for browsers that block the async clipboard API.
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      setState(ok ? "copied" : "failed");
    }
    setTimeout(() => setState("idle"), 1800);
  };
  return (
    <Button variant="secondary" onClick={copy} disabled={disabled} className="h-9 px-3">
      {state === "copied" ? "Copied ✓" : state === "failed" ? "Copy failed" : label}
    </Button>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-3xl border border-dashed border-cream/20 px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-xl border border-cream/15 bg-black/15 px-3 h-11 text-base sm:text-sm text-fg placeholder:text-faint " +
  "focus:outline-none focus:border-cream/50 focus:ring-2 focus:ring-cream/20";
