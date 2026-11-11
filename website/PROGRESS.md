# Website progress

Checklist for `Website_Build_Prompt.md` (and Phase 8 of the cloud upgrade). `[x]` = done and tested.

## 1. Scaffold and tooling
- [x] Next.js 16 (App Router, TypeScript) in `website/`, API in `backend/` (FastAPI, from the cloud upgrade)
- [x] CI workflow `.github/workflows/ci.yml`: website lint, type-check, unit tests, build; API tests on PostgreSQL
- [x] `.env.example` for the website and the API; `.env*` git-ignored; no secret reaches the browser bundle
- [x] This checklist

## 2. Design system (Design E "Spotlight Bento")
- [x] Both themes as CSS variables on `:root` / `[data-theme="light"]`, colours from `DesignE_dark.html` and `DesignE_light.html`
- [x] Manrope + IBM Plex Mono (+ IBM Plex Sans Arabic) self-hosted with `next/font`
- [x] Backdrop: dot grid, spotlight sweep, light-theme blobs; beam cards, pill, buttons, gradient headings
- [x] Motion off for `prefers-reduced-motion`, paused while the tab is hidden; phones get the backdrop without blur filters
- [x] Label colours adjusted where the reference fell below WCAG AA contrast (`#7a7a98`, `#7b83ad`, pink `#d946a8` on text)

## 3. Home (English)
- [x] Nav, hero ("Focus, measured. Privately."), manager-report mock (labelled "Example data"), 6-card bento, live feed
  (labelled illustrative), 3 steps, privacy strip, CTA, footer with GitHub link
- [x] Compared with the references at 1440 px and 390 px in both themes (the reference itself breaks at 390 px; the site
  stacks the bento and the privacy strip instead)

## 4. Arabic and RTL
- [x] `/ar` with `dir="rtl"`, logical CSS properties, natural Arabic copy, المساعد المكتبي الذكي
- [x] Language switch keeps the page and is remembered (`oa-lang` cookie) for addresses without a language
- [x] Screenshot-checked: bento order, mock, steps and footer mirror correctly

## 5. Accounts (API + site)
- [x] Sign up (company + manager), join with a code or invite link, sign in, sign out
- [x] Forgot / reset password: one-time link (30 min, hashed, newest only), same answer for unknown addresses, signs out everywhere
- [x] New passwords need 10 characters (API, website and desktop app)
- [x] Tokens only in httpOnly, Secure (production), SameSite=Lax cookies; refresh rotation de-duplicated
- [x] Company isolation: repository filter + PostgreSQL RLS, tested for every table (incl. `password_resets`)

## 6. Portal
- [x] Overview: company, profile, desktop download card, members with approval status, meetings / messages / reports counts
- [x] Employees (approve, reject, enable, disable, company code, invite links), Reports, Meetings, Messages — real data, empty states when there is none

## 7. Download
- [x] Latest GitHub Release (cached 1 h; `DOWNLOAD_URL` can override the installer link)
- [x] Disabled button with the reason when no release exists; link to GitHub when GitHub cannot be reached
- [x] System requirements and install steps

## 8. Hardening
- [x] CSP with a fresh nonce per page, `frame-ancestors 'none'`, nosniff, referrer policy, permissions policy
- [x] Same-origin + custom-header check on every state-changing call; API WebSocket refuses other sites' origins
- [x] Rate limits (API) with the visitor's IP passed on only with `WEB_PROXY_SECRET`
- [x] Accessibility: axe (WCAG 2.2 AA) on every page, both languages, both themes — no serious/critical problems
- [x] Lighthouse (local production build): desktop 96–100 performance, 100 accessibility / best practices / SEO;
  mobile Home 84–93 (English), 86–87 (Arabic)
- [x] SEO: titles, descriptions, Open Graph image, canonical + hreflang (en/ar/x-default), sitemap, robots
- [x] Styled 404 and error pages

## 9. Deploy
- [x] README with local setup, tests and deploy steps
- [ ] Preview deployment (Vercel + a public API) — needs the owner's Vercel account and the API host (cloud-upgrade Phase 9)
