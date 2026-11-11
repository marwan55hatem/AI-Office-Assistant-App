# Privacy

The product measures how people work, so privacy is a design requirement. This page says what stays on
the PC, what goes to the company's online account, who can see what, and where each guarantee is
enforced and tested. (Version 2: online and multi-company. Version 1 was fully local.)

## 1. What stays on the PC

| signal | how | what happens to it |
|---|---|---|
| camera picture | webcam frame → YOLO12n | analysed in memory: two booleans ("person present", "phone visible") feed the timers. The frame is shown only in the employee's own preview. **No image or video is written to disk or sent anywhere.** |
| window title | the focused window's title | classified as productive / neutral / distraction / idle and shown on the employee's own screen. **Never stored and never sent.** |
| keyboard / mouse | Win32 `GetLastInputInfo` → "seconds since last input" | one number. **No key, no mouse position, no screenshot.** |
| summaries and translations | BART and MarianMT on the PC | the text and the result stay on the PC |
| AI Chat questions about your own tasks and calendar | the app's own intent classifier, on the PC | answered from your data through the API; nothing goes to the online model |

## 2. What goes to the company's online account

| data | why |
|---|---|
| name, e-mail, role, password **hash** (Argon2id) | sign-in |
| session totals: focus, distraction and away seconds per session and day | reports |
| **program names** used during a session (for example "Word", "Chrome") with seconds — never window titles | "most-used apps" in reports |
| tasks, calendar events, meeting requests, chat messages | the features themselves |
| documents a manager uploads for the AI Chat | answers with sources |
| AI Chat: general/document questions, the model's earlier answers in that chat, matching passages from documents the asker may read | sent through the company's server to the online model (Groq, `openai/gpt-oss-120b`). Tasks, calendars and team numbers are **never** in that prompt. |

Each company's data is kept apart twice: every query is filtered by the company (application code) and
PostgreSQL **Row-Level Security** refuses other companies' rows to the API's database role, which has no
power to bypass it. Tests try every table and endpoint across companies.

## 3. Who can see what

| data | employee | manager |
|---|---|---|
| own sessions, tasks, calendar, AI chats | yes | yes (own) |
| other employees' sessions and reports | **no** | yes (same company only) |
| own conversation with the managers | yes | yes (every employee's, same company) |
| another employee's conversation | **no** (404) | — |
| documents marked *Managers only* | **invisible** (not even searched) | yes |
| another company's anything | **no** | **no** |

## 4. E-mail

The service e-mails urgent tasks (always), meetings, meeting-request answers and messages left unread
for 10 minutes while the person is offline (these can be turned off in Settings → Notifications), and
password-reset links. **E-mails never contain the text of a chat message.** The e-mail log keeps the
type and status of each e-mail, never the address or the body.

## 5. The online model (Groq)

Groq's terms: requests are not used for training; logs may be kept for up to 30 days for abuse checks
(Zero Data Retention can be switched on in Groq's console). The app's Settings show the same list of
what is and is not sent, and the online model can be switched off there.

## 6. Security measures (summary)

Argon2id passwords (10 characters minimum for new ones); access tokens for 15 minutes and rotating refresh
tokens (a reused one signs the user out everywhere); the website keeps tokens in httpOnly cookies; rate
limits on sign-in, join and password reset; HTTPS only in production; strict Content Security Policy on
the website; the chat's WebSocket refuses other sites; encrypted daily database backups. Details and the
release checklist: [PRODUCTION.md](PRODUCTION.md).

## 7. Known limitations

| limitation | consequence | next step |
|---|---|---|
| A manager sees every employee's reports and conversations in the company | by design for a small team | per-team managers |
| The online model can be wrong | an answer may be inaccurate | the UI shows sources; read generated code before using it |
| The intent classifier is ~85 % accurate | a wrong *kind* of answer, never a leak (team questions are refused for employees) | more training data |
| The installer is not code-signed | Windows SmartScreen warns | a code-signing certificate |
| Error messages from the server are in English on the Arabic website | mixed languages | translate the API's messages |
