"use client";

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { BRAND_LABEL, BrandIcon, type Brand } from "./BrandIcons";
import { cx } from "./ui";

// Tilted cream tiles arranged in an arc around the centre, like the reference design.
// Positions are percentages of the hero so they scale with the card.
const TILES: { brand: Brand; className: string; tilt: number; delay: number }[] = [
  { brand: "youtube", tilt: -32, delay: 0,
    className: "left-[-7%] top-[52%] sm:left-[-4%] sm:top-[50%] lg:left-[-2%] lg:top-[47%]" },
  { brand: "instagram", tilt: -16, delay: 1.2,
    className: "left-[3%] top-[1%] sm:left-[7%] sm:top-[2%] lg:left-[5%] lg:top-[14%] xl:left-[12%] xl:top-[21%]" },
  { brand: "facebook", tilt: 16, delay: 0.6,
    className: "right-[3%] top-[1%] sm:right-[7%] sm:top-[2%] lg:right-[5%] lg:top-[13%] xl:right-[12%] xl:top-[19%]" },
  { brand: "x", tilt: 30, delay: 1.8,
    className: "right-[-7%] top-[52%] sm:right-[-4%] sm:top-[50%] lg:right-[-2%] lg:top-[46%]" },
];

export const EXAMPLE_URL: Record<Brand, string> = {
  youtube: "https://www.youtube.com/shorts/…",
  instagram: "https://www.instagram.com/reel/…",
  facebook: "https://www.facebook.com/reel/…",
  x: "https://x.com/…/status/…",
};

/** Cycles through the platform names; the matching tile lights up. */
export function useBrandCycle(paused: boolean) {
  const order: Brand[] = ["instagram", "youtube", "facebook", "x"];
  const [i, setI] = useState(0);
  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => setI((n) => (n + 1) % order.length), 2600);
    return () => clearInterval(t);
  }, [paused, order.length]);
  return [order[i], (b: Brand) => setI(order.indexOf(b))] as const;
}

export function Hero({ brand, onPickBrand, children, headline }: {
  brand: Brand;
  onPickBrand: (b: Brand) => void;
  children: ReactNode;
  headline: string;
}) {
  return (
    <section className="relative flex min-h-[640px] flex-1 flex-col items-center sm:min-h-[700px] lg:min-h-[760px]">
      {TILES.map((t) => (
        <button key={t.brand} type="button" onClick={() => onPickBrand(t.brand)}
                aria-label={`Use a ${BRAND_LABEL[t.brand]} link`} aria-pressed={brand === t.brand}
                style={{ "--tilt": `${t.tilt}deg`, "--delay": `${t.delay}s` } as CSSProperties}
                className={cx(
                  "tile-float absolute z-0 grid aspect-square w-[22vw] min-w-[84px] max-w-[210px] place-items-center sm:w-[18vw]",
                  "rounded-[26%] bg-cream shadow-[0_30px_60px_-25px_rgba(10,15,5,.75)] transition-[filter,box-shadow] duration-500",
                  "hover:brightness-105 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cream",
                  brand === t.brand ? "ring-4 ring-cream/40" : "brightness-[.93]",
                  t.className,
                )}>
          <BrandIcon brand={t.brand} className="w-[42%] drop-shadow-[0_8px_10px_rgba(0,0,0,.18)]" />
        </button>
      ))}

      <div className="relative z-10 mt-[30%] flex w-full max-w-md flex-col items-center px-4 sm:mt-[13%] lg:mt-[9%]">
        <p className="text-xs font-medium uppercase tracking-[0.2em] text-fg/70">Paste a link from</p>
        <p key={brand} className="word-in font-display mb-5 mt-1 text-5xl text-cream drop-shadow-[0_6px_24px_rgba(0,0,0,.35)] sm:text-6xl">
          {BRAND_LABEL[brand]}
        </p>
        {children}
      </div>

      {/* The hills fade out (mask) so the card continues seamlessly below. */}
      <div aria-hidden
           className="pointer-events-none absolute inset-x-0 bottom-0 z-0 h-[34%] [mask-image:linear-gradient(to_bottom,black_45%,transparent)]">
        <PowderMounds />
      </div>
      <h1 className="font-display relative z-10 mt-auto px-4 pb-6 text-center text-[clamp(3rem,10.5vw,8.5rem)] leading-[0.9] text-cream drop-shadow-[0_10px_30px_rgba(0,0,0,.35)] sm:pb-10">
        {headline}
      </h1>
    </section>
  );
}

/** Matcha-powder hills drawn as SVG, textured with noise (no photos needed). */
function PowderMounds() {
  return (
    <svg viewBox="0 0 1200 300" preserveAspectRatio="none" className="h-full w-full">
      <defs>
        <filter id="powder" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="3" seed="7" result="noise" />
          <feColorMatrix in="noise" type="saturate" values="0" result="mono" />
          <feComponentTransfer in="mono" result="speckle">
            <feFuncA type="table" tableValues="0 0.85" />
          </feComponentTransfer>
          <feComposite in="speckle" in2="SourceGraphic" operator="in" result="grain" />
          <feBlend in="SourceGraphic" in2="grain" mode="multiply" />
        </filter>
        <linearGradient id="hillBack" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#5f6b3d" />
          <stop offset="1" stopColor="#323b22" />
        </linearGradient>
        <linearGradient id="hillFront" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#8a9658" />
          <stop offset="0.55" stopColor="#5c6939" />
          <stop offset="1" stopColor="#3a4426" />
        </linearGradient>
        <radialGradient id="peakLight" cx="0.5" cy="0.15" r="0.6">
          <stop offset="0" stopColor="#c3cb8f" stopOpacity="0.55" />
          <stop offset="1" stopColor="#c3cb8f" stopOpacity="0" />
        </radialGradient>
      </defs>
      <path filter="url(#powder)" fill="url(#hillBack)"
            d="M0 300V190c90-40 170-62 250-46 70 14 120 46 190 40 60-6 90-40 150-40v156zM700 300V170c80-30 150-48 230-40 90 10 170 52 270 44v126z" />
      <path filter="url(#powder)" fill="url(#hillFront)"
            d="M230 300c70-60 140-120 230-176 50-32 95-62 140-64 46 2 92 32 142 64 90 56 160 116 228 176z" />
      <path fill="url(#peakLight)" d="M380 300c80-80 150-150 220-176 70 26 140 96 220 176z" />
    </svg>
  );
}
