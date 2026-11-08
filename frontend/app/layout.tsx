import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const NAME = process.env.NEXT_PUBLIC_SITE_NAME || "Video Downloader";
const DESCRIPTION =
  "Save public videos from X, Instagram, Facebook, TikTok, YouTube and Reddit as MP4, with the original caption. Free, no account needed.";

export const metadata: Metadata = {
  title: { default: `${NAME}: save videos as MP4`, template: `%s · ${NAME}` },
  description: DESCRIPTION,
  applicationName: NAME,
  openGraph: { title: NAME, description: DESCRIPTION, type: "website" },
  appleWebApp: { capable: true, title: NAME, statusBarStyle: "black-translucent" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#0b0d12",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
