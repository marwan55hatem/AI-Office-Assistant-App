# Office Assistant — website

Next.js 16 site and company portal for Office Assistant (المساعد المكتبي الذكي), built on the
**Design E "Spotlight Bento"** design (`DesignE_dark.html` / `DesignE_light.html`):

- Public pages — Home (hero, report mock, bento features, live feed, steps, privacy strip, call to
  action), How it works, Features, Privacy, Download, Docs & FAQ — in **English and Arabic
  (right-to-left)**, **dark** (default) and **light** themes.
- Accounts — create a company (the owner becomes the manager), join with a company code or invite link,
  sign in / out, **forgot and reset password**. New passwords need 10 characters.
- Portal — overview (company, profile, desktop download, members, what waits for you), **reports**,
  **employees** (approve, invite, disable), **meeting requests** and **chat**: the same data as the
  desktop app, from any device.

Progress against the build brief: [PROGRESS.md](PROGRESS.md).

## Choices that differ from the build brief
- **No Tailwind, next-intl or next-themes.** The site already had a tested theme system (CSS variables,
  no flash, remembered) and i18n (typed dictionaries, `/en` and `/ar`, RTL) when the design brief came;
  both meet every requirement of the brief, so the design was rebuilt on them instead of swapping
  libraries. All colours are CSS variables switched by one `data-theme` attribute.
- Two label colours and the light theme's pink are slightly darker than the references, to pass WCAG AA
  contrast. On phones the backdrop uses soft gradients instead of large blur filters (smooth scrolling;
  Lighthouse mobile went from 61 to 84–93 on Home).

## How it talks to the API
The browser never holds the long-lived sign-in token and never calls the API directly. The site's own
server (route handlers under `src/app/api/`) keeps the tokens in **httpOnly, SameSite=Lax cookies**,
forwards the signed-in pages' calls (`/api/proxy/...`, allow-listed paths only) and refreshes the
session — one refresh per token, so the API's refresh-token-reuse protection is never triggered by
parallel requests. State-changing calls must come from this site (same Origin + a custom header).
The chat's live channel gets a 15-minute access token from `/api/auth/socket` and sends it as the
socket's first message.

## Run locally
```bash
npm install
cp .env.example .env.local        # set API_URL (and WEB_PROXY_SECRET, same value as the API's)
npm run dev                       # http://localhost:3000
```
Production build: `npm run build && npm start`.

## Tests
Unit tests (Vitest + Testing Library: forms, API client, validation, languages, download card, CSP):
```bash
npm test
```
End-to-end (Playwright) against a running API and site, including accessibility (axe, WCAG 2.2 AA)
in both languages and themes. The password-reset test reads the queued e-mail from the database, so run
the API with `EMAIL_WORKER_ENABLED=0` and `CORS_ORIGINS=["http://localhost:3100"]`:
```bash
npx playwright install chromium
npm run build && API_URL=http://127.0.0.1:8766 ALLOW_INSECURE_COOKIES=1 npx next start -p 3100
npm run test:e2e
```
`SCREENSHOTS=1 npx playwright test tests/screenshots.spec.ts` refreshes the screenshots in
`../screenshots_redesign/cloud/phase8_*`.

## Deploy
Vercel (or any Node host): set `API_URL`, `SITE_URL`, `WEB_PROXY_SECRET`, and `PUBLIC_API_WS_URL` if
the API's public WebSocket address differs. Optional: `DOWNLOAD_URL` (installer link instead of the
GitHub release's), `GITHUB_REPO`, `GITHUB_TOKEN`. Cookies are `Secure` in production, so serve over HTTPS.
On the API, set `CORS_ORIGINS` to the site's address (the chat's WebSocket only accepts pages from it)
and the same `WEB_PROXY_SECRET`. Lint, types, unit tests and the build run in CI
(`.github/workflows/ci.yml`).
