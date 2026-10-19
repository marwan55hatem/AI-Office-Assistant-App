# User guide

The window has a sidebar on the left (☰ collapses it to icons) and the selected page on the right.
**Settings → Appearance** switches between the dark and the light theme.

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

* **Camera preview** with *Person* and *Phone* indicators (the picture is never saved).
* **Active application** — the title of the window you are using and its classification.

While the camera model loads (a few seconds) nothing is counted, so a slow start does not count as "away".

### Calendar
Your events: the ones you were invited to by a manager. The sidebar badge shows today's count.
You also get a Windows notification shortly before an event starts.

### To Do
* **Assigned** — tasks from your manager, with description, priority and deadline
  (badges: *overdue*, *due soon*). Tick a task when it is done.
* **My tasks** — your own list; type a task, optionally a description, and press *Add*.
* You are notified about deadlines that are due soon or overdue.

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
| "How do I build a CNN in PyTorch?", "Explain overfitting" | the local AI model |
| a question covered by your manager's documents | the model, quoting the document, with *Sources: file.md* |

* **Stop** ends an answer early; **New chat** starts a fresh conversation; right-click a chat to rename or delete it.
* The badge in the header shows the AI model state (*loads on first question*, *loading*, *ready · GPU*,
  *slow mode · CPU*, *off*).
* Team questions ("who is the best performer?") are for managers only.

### Settings
Profile (name, username), password, theme, and **AI assistant**: switch the AI model off (the chat then
answers only from your data) or free its memory.

---

## Managers

Managers have everything above (To Do, AI Helper, AI Chat, Settings, Calendar) plus:

### Home
Team size, who is working now, total focus and distracted time today, today's activity per employee,
the recent activity feed and alerts (absent employees, pending sign-ups).

### Employees
* **Pending sign-up requests** — *Approve* or *Reject*.
* **Status** of every employee today: working / not started, focus and distraction time.

### Sessions
History of all sessions (filter by employee and period). Open one to see its numbers and the event log
(when focus, distraction and away started).

### Tasks
Assign a task: employee, title, optional description, priority (*normal* / *urgent*) and optional deadline
(date, optional time). See and remove assigned tasks.

### Reports
Weekly report per employee and for the team (focus, distraction, away).

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

## Admin panel (Office Assistant Admin)
Password `admin123`. Tabs: **Users** (add, edit, change role, delete with all their data), **Sessions**,
**Tasks**, **Events**, and **Danger zone** (delete all sessions or tasks, reset employee passwords to `1234`,
export / import the database, factory reset). Destructive actions ask you to type a confirmation phrase.
