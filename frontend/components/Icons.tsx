// Small stroke icons for the navigation (drawn for this app).
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const IconDownload = (p: P) => (
  <svg {...base} {...p}><path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></svg>
);
export const IconFiles = (p: P) => (
  <svg {...base} {...p}><path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" /></svg>
);
export const IconEdit = (p: P) => (
  <svg {...base} {...p}><path d="M15 4l5 5L9 20H4v-5z" /><path d="m13 6 5 5" /></svg>
);
export const IconActivity = (p: P) => (
  <svg {...base} {...p}><path d="M3 12h4l3-7 4 14 3-7h4" /></svg>
);
export const IconSend = (p: P) => (
  <svg {...base} {...p}><path d="M21 3 10 14" /><path d="m21 3-7 18-4-7-7-4z" /></svg>
);
export const IconHelp = (p: P) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14" /><path d="M12 17.5h.01" /></svg>
);
export const IconLogout = (p: P) => (
  <svg {...base} {...p}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" /><path d="m10 16 4-4-4-4" /><path d="M14 12H4" /></svg>
);
export const IconArrow = (p: P) => (
  <svg {...base} {...p}><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></svg>
);
