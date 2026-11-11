import { IBM_Plex_Mono, IBM_Plex_Sans_Arabic, Manrope } from "next/font/google";

/** Self-hosted at build time by next/font (no request to Google from the visitor, no layout shift). */
// Manrope is a variable font: one file covers every weight
export const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });
// labels and numbers only: two weights, not preloaded (they are not needed for the first paint)
export const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["500", "600"], variable: "--font-plex-mono", display: "swap", preload: false });
// Arabic text: two weights (the headings use 700). Not preloaded: a preload would load it on every
// English page too (it cost English Home about 10 Lighthouse points on a simulated phone).
export const plexArabic = IBM_Plex_Sans_Arabic({ subsets: ["arabic"], weight: ["400", "700"], variable: "--font-plex-arabic", display: "swap", preload: false });

export const fontVariables = `${manrope.variable} ${plexMono.variable} ${plexArabic.variable}`;
