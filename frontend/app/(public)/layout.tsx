import Link from "next/link";
import { Frame } from "@/components/Frame";
import { IconDownload } from "@/components/Icons";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteName } from "@/components/SiteName";

export default function PublicLayout({ children }: LayoutProps<"/">) {
  return (
    <Frame
      header={
        <header className="flex items-center px-5 pt-5 sm:px-10 sm:pt-8">
          <Link href="/" className="font-display whitespace-nowrap text-[1.65rem] leading-none text-fg sm:text-3xl"><SiteName /></Link>
          <Link href="/" className="ml-auto flex h-11 shrink-0 items-center gap-2 whitespace-nowrap rounded-xl bg-ink px-4 text-sm font-medium text-cream hover:bg-black">
            <IconDownload className="size-[18px]" /> <span className="sm:hidden">Download</span><span className="hidden sm:inline">Download a video</span>
          </Link>
        </header>
      }
      footer={<SiteFooter />}
    >
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-10 sm:px-8">{children}</main>
    </Frame>
  );
}
