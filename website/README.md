# Office Assistant — website

Next.js 16 site for Office Assistant: the public pages (Home, How it works, Features, Privacy,
Download, Docs & FAQ) in **English and Arabic (right-to-left)** with light and dark themes, sign-up
and sign-in, and the signed-in area: the manager's **reports**, **employees** (approve, invite,
disable), **meeting requests** and **chat** — the same data as the desktop app, from any device.

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
End-to-end (Playwright) against a running API and site, including accessibility (axe, WCAG 2.2 AA)
in both languages and themes:
```bash
npx playwright install chromium
npm run build && API_URL=http://localhost:8766 ALLOW_INSECURE_COOKIES=1 npx next start -p 3100
npm run test:e2e
```
`SCREENSHOTS=1 npx playwright test tests/screenshots.spec.ts` refreshes the screenshots in
`../screenshots_redesign/cloud/phase8_*`.

## Deploy
Vercel (or any Node host): set `API_URL`, `SITE_URL`, `WEB_PROXY_SECRET`, and `PUBLIC_API_WS_URL` if
the API's public WebSocket address differs. Cookies are `Secure` in production, so serve over HTTPS.
