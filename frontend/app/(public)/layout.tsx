import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteName } from "@/components/SiteName";

export default function PublicLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <header className="border-b border-line">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg">▼</span>
            <SiteName />
          </Link>
          <Link href="/" className="ml-auto rounded-lg px-3 py-2 text-sm text-muted hover:bg-surface-3 hover:text-fg">
            Download a video
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">{children}</main>
      <SiteFooter />
    </>
  );
}
