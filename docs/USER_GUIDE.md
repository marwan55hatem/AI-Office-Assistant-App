# User guide

Version 2: the desktop app and the website share one online account per company.

## Getting started

* **A manager** creates the company on the website (*Create company*) or in the app. The manager can then
  find the **company code** and make **invite links** under *Employees*.
* **An employee** chooses *Join a company* (website or app) with the code or the invite link, and signs in
  once the manager has approved them.
* **Forgot your password?** On the website's sign-in page: you receive a one-time link (valid 30 minutes).
  New passwords need at least 10 characters.

The desktop window has a sidebar on the left (☰ collapses it to icons) and the selected page on the right.
**Settings → Appearance** switches between the dark and the light theme. Without a connection the app
shows a banner; work sessions keep counting and are sent when the connection is back.

---

## Employees

### Session
The page you will use most. Press **START SESSION** when you begin working and **STOP SESSION** when you finish.

* **Session timer** — total time of the session.
* **Time worked / Time distracted / Time away** — every second is counted in exactly one of them:

  | the app sees… | counted as |
  |---|---|
  | no keyboard or mouse input for 90 s | away |
  | nobody in front of the camera | away |
  | a phone in the camera picture | distracted |
  | a distracting window (YouTube, Netflix, games, social media; WhatsApp after 90 s) | distracted |
  | no window / screen idle | away |
  | otherwise | worked (focus) |

* **Camera preview** with *Person* and *Phone* indicators (the picture is never saved or sent).
* **Active application** — the window you are using and its classification. Only the program's name
  (for example "Word") is sent with the session, never the window title.

While the camera model loads (a few seconds) nothing is counted, so a slow start does not count as "away".

### Calendar
Your events: the ones you were invited to by a manager. The sidebar badge shows today's count.
You also get a Windows notification shortly before an event starts.

### To Do
* **Assigned** — tasks from your manager, with description, priority and deadline
  (badges: *overdue*, *due soon*). Tick a task when it is done.
* **My tasks** — your own list; type a task, optionally a description, and press *Add*.
* You are notified about deadlines that are due soon or overdue.

### Meetings
Ask your manager for a meeting: a topic, a short note and **1 to 3 proposed times**. The manager accepts
one (it appears in both calendars), declines with a reason, or proposes other times — then you pick one.
You can cancel a request or a booked meeting. The sidebar badge shows what waits for you.

### Messages
A private chat with your manager (all managers of your company can answer; other employees cannot see
it). Messages arrive live; your own show *Sent*, *Delivered* or *Read*. Enter sends, Shift+Enter starts a
new line.

### AI Helper
* **Summarise**: paste text or open a PDF, choose a length, press *Summarise* (BART model).
* **Translate**: between English, Arabic, French and German (MarianMT models).
The first use loads the model (a few seconds); later runs are fast.

### AI Chat
Ask in English or Arabic, for example:

| ask | answered from |
|---|---|
| "What tasks do I have?", "What's due soon?", "What should I do first?" | your own tasks (database) |
| "How should I start on the Q3 report?" | a step-by-step plan for that task |
| "What's on my calendar today?", "How much did I focus this week?" | your calendar / sessions |
| "How do I build a CNN in PyTorch?", "Explain overfitting" | the online AI model (through your company's server) |
| a question covered by your manager's documents | the online model, quoting the document, with *Sources: file.md* |

* **Stop** ends an answer early; **New chat** starts a fresh conversation; right-click a chat to rename or delete it.
* The badge in the header shows the AI model state (*online*, *offline — needs a connection*, *off*).
  Questions about your own tasks and calendar never go to the online model.
* Team questions ("who is the best performer?") are for managers only.

### Settings
Profile (name), password, theme; **AI assistant**: switch the online model off (the chat then answers only
from your data) and see exactly what is and is not sent; **Notifications**: e-mails about meetings and
unread messages on/off (urgent tasks are always e-mailed) and the e-mail language (English or Arabic).

---

## Managers

Managers have everything above (To Do, AI Helper, AI Chat, Settings, Calendar) plus:

### Home
Team size, who is working now, total focus and distracted time today, today's activity per employee,
the recent activity feed and alerts (absent employees, people waiting for approval).

### Employees
* **Waiting for approval** — people who joined with the company code or an invite link: *Approve* or *Reject*.
* **Status** of every employee today: working / not started, focus and distraction time.
* On the website: the **company code** (and a new one), **invite links** (one-time, 7 days), and
  enabling / disabling accounts (a disabled account is signed out everywhere).

### Sessions
History of all sessions (filter by employee and period). Open one to see its numbers and the event log
(when focus, distraction and away started).

### Tasks
Assign a task: employee, title, optional description, priority (*normal* / *urgent*) and optional deadline
(date, optional time). **Urgent tasks are e-mailed** to the employee. See and remove assigned tasks.

### Reports (app and website)
For a period (7 days, 30 days, this month, custom): focus / distracted / away %, hours worked, task
completion and attendance, each with the change from the previous period; focus over time, hours per day,
attendance, most-used apps, and a ranking you can sort and page through. Double-click (app) or click
(website) an employee to compare them with the team. **Export CSV / PDF**.

### Meetings and Messages (manager)
Requests from your team: accept a selected time, propose other times, or decline with a reason; cancel a
booked meeting. Messages: one conversation per employee, unread ones first, with live delivery.

### Calendar (manager)
Create, edit and delete events; invite selected employees or *All employees*.

### AI Chat (manager)
Also answers team questions from the database: "How is the team doing today?", "Who should I check in on?",
"Who is the best performer this week?", "Summarise last week", "How is Sara doing?".

### Knowledge
Documents the AI Chat can read:
* **Add documents…** (or drag `.txt` / `.md` files onto the page), up to 2 MB each.
* **Who can read it**: *Everyone* or *Managers only* — employees never see managers-only content, not even
  through the chat.
* **Try a search** shows which passages the chat would use for a question.

---

## Website

Everything a manager needs away from the office PC: **Overview** (company, profile, desktop download,
members, what waits for you), **Reports**, **Employees**, **Meetings** and **Messages**. Employees have
Overview, Meetings and Messages. English and Arabic (right-to-left), dark and light themes. Work sessions,
tasks, the AI Helper and the AI Chat are in the desktop app.
