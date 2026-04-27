import type { Config } from "tailwindcss";

/**
 * Tailwind v4. Design tokens live in `src/app/globals.css` via `@theme`
 * + `:root`/`.dark`. This file holds only the content glob and any legacy
 * keyframes/animations. Workspace-specific motion (slide-bar, fade-in,
 * slide-up, panel-scale-in) is defined in globals.css and referenced via
 * `.animate-*` utility classes.
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
