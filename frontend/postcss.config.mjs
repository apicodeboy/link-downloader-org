// Tailwind via PostCSS works with both bundlers: webpack (production builds, required on
// Hostinger for Next.js >= 16.3.3) and Turbopack (`next dev`).
export default {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
