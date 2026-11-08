import type { MetadataRoute } from "next";

const NAME = process.env.NEXT_PUBLIC_SITE_NAME || "Video Downloader";

// Lets visitors install the site on their phone's home screen, and on Android adds it to
// the share sheet: share a post from TikTok/Instagram/X straight to the site.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: NAME,
    short_name: NAME.length > 12 ? "Downloader" : NAME,
    description: "Save public videos you're allowed to use as MP4, with their original caption.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#29331f",
    theme_color: "#a9a76b",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    share_target: {
      action: "/",
      method: "GET",
      params: { url: "url", text: "text", title: "title" },
    },
  } as MetadataRoute.Manifest;
}
