import Link from "next/link";
import { Frame } from "@/components/Frame";

export default function NotFound() {
  return (
    <Frame>
      <main className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-24 text-center">
        <p className="font-display text-[clamp(5rem,18vw,11rem)] leading-none text-cream/90">404</p>
        <h1 className="text-lg font-medium text-fg">This page doesn&apos;t exist</h1>
        <Link href="/" className="rounded-xl bg-cream px-5 py-3 text-sm font-semibold text-cream-ink hover:bg-white">
          Download a video
        </Link>
      </main>
    </Frame>
  );
}
