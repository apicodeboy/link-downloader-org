import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-24 text-center">
      <p className="text-5xl font-semibold text-faint">404</p>
      <h1 className="text-lg font-semibold">This page doesn&apos;t exist</h1>
      <Link href="/" className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:bg-accent-strong">
        Download a video
      </Link>
    </main>
  );
}
