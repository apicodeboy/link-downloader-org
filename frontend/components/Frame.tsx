import type { ReactNode } from "react";

/** The olive page frame with the rounded deep-green card inside (matcha theme). */
export function Frame({ header, footer, children }: { header?: ReactNode; footer?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col px-2 pt-2 sm:px-6 sm:pt-6 lg:px-10">
      <div className="flex flex-1 flex-col rounded-[2rem] bg-frame-edge/70 p-1.5 shadow-[0_30px_80px_-30px_rgba(40,45,20,.55)] sm:rounded-[2.75rem] sm:p-3">
        <div className="matcha-card relative isolate flex flex-1 flex-col overflow-hidden rounded-[1.65rem] sm:rounded-[2.25rem]">
          <div aria-hidden className="grain-layer pointer-events-none absolute inset-0 -z-10" />
          {header}
          {children}
        </div>
      </div>
      {footer}
    </div>
  );
}

export function Wordmark({ name }: { name: string }) {
  return <span className="font-display whitespace-nowrap text-[1.65rem] leading-none text-fg sm:text-3xl">{name}</span>;
}
