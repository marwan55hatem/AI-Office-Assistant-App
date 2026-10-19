"""The answer engine: turns a question into a reply written from the database.

Flow for every message:

1. load who is asking (role) from the database;
2. mask known task / employee names, so the classifier sees "how is personx doing";
3. classify the question into an *intent* (``intent_model.py``);
4. if the intent needs team data and the user is not a manager, refuse -- this
   check happens **before** any team data is read, so an employee's request can
   never touch other people's numbers;
5. run the handler for the intent; it reads the database and writes the reply.

Everything is plain Python (no Qt) and every number in a reply comes straight from
the database, so the assistant cannot invent figures.
"""

import re
from collections import namedtuple
from datetime import datetime, timedelta

from assistant.entities import PERSON_MASK, TASK_MASK, autocorrect, mask_entities, match_people, match_task, vocabulary
from assistant.formatting import deadline_state, fmt_duration, format_deadline
from assistant.intents import MANAGER_INTENTS, UNKNOWN
from assistant.lexicon import concept_tags
from assistant.intent_model import get_classifier, normalize
from assistant.playbooks import build_plan
from database.db_manager import deadline_due_datetime
from typing import Any, Dict, Optional

Reply = namedtuple("Reply", "text intent confidence")

#: "Best performer" needs at least this much tracked time, or a few minutes
#: of luck could win.  (week / today)
MIN_TRACKED_WEEK = 3600
MIN_TRACKED_TODAY = 900
#: A person counts as "distracted" today above this much distraction time.
HIGH_DISTRACTION_SECONDS = 3600
#: Lines shown per list before "... and N more".
MAX_LIST = 12

EXAMPLES = {
    "list_tasks": "What tasks do I have?",
    "task_howto": "How should I start on <task name>?",
    "task_deadlines": "What is due soon?",
    "task_next": "What should I do first?",
    "calendar_today": "What's on my calendar today?",
    "calendar_upcoming": "What's coming up this week?",
    "my_stats": "How was my focus today?",
    "team_status": "How is the team doing today?",
    "active_now": "Who is working right now?",
    "best_performer": "Who is the best performer?",
    "check_in": "Who should I check in on?",
    "absent": "Who is absent?",
    "weekly_summary": "Summarize last week's performance",
    "employee_status": "How is <name> doing?",
}


#: How the engine names what a question was about (for "what did I just ask?").
INTENT_TOPICS = {
    "list_tasks": "your task list", "task_howto": "how to do a task",
    "task_deadlines": "your deadlines", "task_next": "what to do first",
    "calendar_today": "today's calendar", "calendar_upcoming": "your upcoming events",
    "my_stats": "your own focus time", "team_status": "the team's status",
    "active_now": "who is working", "best_performer": "your best performer",
    "check_in": "who needs attention", "absent": "who is absent",
    "weekly_summary": "the weekly summary", "employee_status": "one employee",
    "greeting": "a greeting", "capabilities": "what I can do",
}


def _first_name(user):
    parts = str(user.get("full_name") or "").split()
    return parts[0] if parts else "there"


def _shorten(text, limit=90):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _rate(focus, distraction, away):
    """Focus share of the tracked time (0-100), or None when nothing was tracked."""
    total = focus + distraction + away
    return None if total <= 0 else round(100.0 * focus / total)


def _more(count):
    return ["... and %d more." % count] if count > 0 else []


#: Words that do not say *what* a "how do I ...?" question is about.  When nothing
#: else is left, the question is about the user's tasks ("how do I start?"); when a
#: topic word remains ("how to build a CNN model") it is a general question.
_HOWTO_FILLER = frozenset("""
how do does did i we you to should can could would will the a an on in for my me it this that these those
start starting started begin tackle approach handle go about get please now next and of with at is are be
task tasks one thing work doing finish complete done so what first way best
كيف ابدا ابداء ابدأ ابدأها انجز انجاز اعمل انهي
المهمه مهمه المهمة مهمة مهامي هذه هذا اللي من في على انا
""".split())


def _known_word(word, vocab):
    """In the vocabulary, or a plain -s / -es / -ing / -ed form of a word that is."""
    if word in vocab:
        return True
    stems = []
    if word.endswith("s"):
        stems.append(word[:-1])
    if word.endswith("es"):
        stems.append(word[:-2])
    if word.endswith("ing"):
        stems += [word[:-3], word[:-3] + "e"]
    if word.endswith("ed"):
        stems += [word[:-2], word[:-1]]
    return any(stem in vocab for stem in stems)


def count_unfamiliar_words(masked_text: str) -> int:
    """How many (English) words of the question the assistant has never seen
    (``overfitting``, ``dropout``...).  Typos were already repaired, names and task words
    masked, so what is left are real topic words the engine knows nothing about.
    Arabic words are not counted: their many forms are not in the example questions."""
    vocab = vocabulary()
    words = re.findall(r"[^\W\d_]{3,}", normalize(masked_text), re.UNICODE)
    return sum(1 for w in words if w.isascii() and w not in (TASK_MASK, PERSON_MASK) and not _known_word(w, vocab))


def is_general_question(text: str, tasks) -> bool:
    """True for a "how do I ...?" question that is not about one of the user's tasks."""
    if match_task(text, tasks) is not None:
        return False
    words = re.findall(r"\w+", normalize(text), re.UNICODE)
    return any(word not in _HOWTO_FILLER for word in words)


class AssistantEngine:
    """Answers questions of one logged-in user.  ``state`` is a per-chat dict the
    caller keeps between messages (it lets a follow-up like "and Sara?" work)."""

    def __init__(self, db, user_id, classifier=None, now=None):
        self.db = db
        self.user_id = user_id
        self._classifier = classifier
        self._now = now                # a fixed "now" for tests

    # ------------------------------------------------------------------ #
    #  Entry point
    # ------------------------------------------------------------------ #
    def now(self) -> datetime:
        """The current time (a fixed value in tests)."""
        return self._now or datetime.now()

    @property
    def classifier(self):
        """The intent classifier, loaded on first use."""
        if self._classifier is None:
            self._classifier = get_classifier()
        return self._classifier

    def ask(self, text: str, state: Optional[Dict[str, Any]] = None) -> Reply:
        """Answer one message; returns ``Reply(text, intent, confidence)``."""
        state = state if state is not None else {}
        state["unfamiliar"] = 0        # filled in below; the chat backend reads it for routing
        user = self.db.get_user_by_id(self.user_id) or {"full_name": "there", "role": "employee"}
        is_manager = user.get("role") == "manager"

        open_tasks = self._open_tasks()
        # Only a manager's engine ever loads other people; an employee's never does.
        people = self._employees() if is_manager else []

        # A follow-up answering "Which task?" / "Which employee?"
        pending = state.pop("pending", None)
        if pending == "task_howto":
            task = match_task(text, open_tasks)
            if task:
                return self._reply(self._howto_text(task), "task_howto", 1.0, state, task=task)
        if pending == "employee_status":
            found = match_people(text, people)
            if found:
                return self._reply(self._employee_text(found[0], user), "employee_status", 1.0,
                                   state, person=found[0])

        masked = autocorrect(mask_entities(text, [p["full_name"] for p in people],
                                           [t["title"] for t in open_tasks]))
        intent, confidence = self.classifier.predict(masked)
        state["unfamiliar"] = count_unfamiliar_words(masked)
        state["prev_intent"] = state.get("last_intent")
        state["last_intent"] = intent

        if intent in MANAGER_INTENTS and not is_manager:
            return Reply(
                "Team information is only available to managers. I can still help with "
                "your own tasks, deadlines, calendar and focus time. Try: \"%s\""
                % EXAMPLES["list_tasks"], "denied", confidence)

        if intent == "task_howto" and is_general_question(text, open_tasks):
            return self._unknown(masked, user, is_manager, confidence)   # e.g. "how to build a CNN"

        handler = getattr(self, "_h_" + intent, None)
        if handler is None:
            return self._unknown(masked, user, is_manager, confidence)
        text_out = handler(text, user, state, open_tasks, people)
        return self._reply(text_out, intent, confidence, state)

    def _reply(self, text, intent, confidence, state, task=None, person=None):
        if task is not None:
            state["last_task_id"] = task["id"]
        if person is not None:
            state["last_person_id"] = person["id"]
        return Reply(text, intent, confidence)

    # ------------------------------------------------------------------ #
    #  Data helpers
    # ------------------------------------------------------------------ #
    def _open_tasks(self):
        tasks = (self.db.get_assigned_tasks(self.user_id) + self.db.get_self_tasks(self.user_id))
        return [t for t in tasks if not t.get("is_done")]

    def _employees(self):
        return [e for e in self.db.get_all_employees() if e.get("status", "approved") == "approved"]

    def _task_line(self, number, task):
        parts = ["%d. \"%s\"" % (number, task["title"])]
        if task.get("priority") == "urgent":
            parts.append("[URGENT]")
        line = " ".join(parts)
        extra = []
        if task.get("assigned_by"):
            boss = self.db.get_user_by_id(task["assigned_by"])
            if boss:
                extra.append("assigned by %s" % boss["full_name"])
        else:
            extra.append("personal")
        if task.get("deadline_date"):
            extra.append("due %s" % format_deadline(task["deadline_date"], task.get("deadline_time")))
        if extra:
            line += " — " + ", ".join(extra)
        if task.get("description"):
            line += "\n   " + _shorten(task["description"])
        return line

    # ------------------------------------------------------------------ #
    #  Everyone: small talk
    # ------------------------------------------------------------------ #
    def _h_greeting(self, text, user, state, tasks, people):
        extra = ", your calendar" + (" or your team's performance" if user.get("role") == "manager" else "")
        return "Hi %s! Ask me about your tasks, deadlines%s." % (_first_name(user), extra)

    def _h_thanks(self, text, user, state, tasks, people):
        return "You're welcome! Ask me anything else about your work."

    def _h_goodbye(self, text, user, state, tasks, people):
        return "Goodbye %s! Come back any time." % _first_name(user)

    def _h_capabilities(self, text, user, state, tasks, people):
        lines = ["I'm the local assistant of this app: I answer from your own data, nothing leaves this computer.",
                 "You can ask me, for example:"]
        keys = ["list_tasks", "task_howto", "task_deadlines", "task_next", "calendar_today", "my_stats"]
        if user.get("role") == "manager":
            keys += ["team_status", "best_performer", "check_in", "absent", "weekly_summary"]
        lines += ["- " + EXAMPLES[k] for k in keys]
        lines.append("I can't answer general-knowledge questions.")
        return "\n".join(lines)

    def _h_recall(self, text, user, state, tasks, people):
        """"What did I just say?" -- from the earlier messages of this chat."""
        earlier = [m for m in state.get("previous_user_messages", []) if m.strip()]
        if not earlier:
            return "This is the start of our conversation: you haven't asked me anything yet."
        lines = ["You just asked: \"%s\"" % _shorten(earlier[-1], 140)]
        topic = INTENT_TOPICS.get(state.get("prev_intent"))
        if topic:
            lines[0] += " (I took it as a question about %s.)" % topic
        if len(earlier) > 1:
            lines.append("Before that: \"%s\"" % _shorten(earlier[-2], 140))
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Everyone: tasks
    # ------------------------------------------------------------------ #
    def _h_list_tasks(self, text, user, state, tasks, people):
        if not tasks:
            return "You have no open tasks. Nothing is waiting for you right now."
        lines = ["You have %d open task%s:" % (len(tasks), "" if len(tasks) == 1 else "s")]
        for number, task in enumerate(tasks[:MAX_LIST], 1):
            lines.append(self._task_line(number, task))
        lines += _more(len(tasks) - MAX_LIST)
        return "\n".join(lines)

    def _h_task_deadlines(self, text, user, state, tasks, people):
        now = self.now()
        overdue, soon, week, undated = [], [], [], 0
        for task in tasks:
            due = deadline_due_datetime(task.get("deadline_date"), task.get("deadline_time"))
            if due is None:
                undated += 1
            elif due < now:
                overdue.append((due, task))
            elif due <= now + timedelta(hours=24):
                soon.append((due, task))
            elif due <= now + timedelta(days=7):
                week.append((due, task))
        if not (overdue or soon or week):
            if tasks and undated == len(tasks):
                return "None of your open tasks has a deadline."
            return "Nothing is overdue or due in the next 7 days."

        def block(title, items):
            if not items:
                return []
            out = [title]
            for due, task in sorted(items, key=lambda pair: pair[0])[:MAX_LIST]:
                out.append("- \"%s\" — %s" % (task["title"],
                           format_deadline(task["deadline_date"], task.get("deadline_time"))))
            return out + [""]

        lines = block("Overdue:", overdue) + block("Due within 24 hours:", soon) + block("Due in the next 7 days:", week)
        return "\n".join(lines).strip()

    def _h_task_next(self, text, user, state, tasks, people):
        if not tasks:
            return "You have no open tasks, so there is nothing to start with."
        now = self.now()

        def key(task):
            due = deadline_due_datetime(task.get("deadline_date"), task.get("deadline_time"))
            return (0 if due and due < now else 1,
                    0 if task.get("priority") == "urgent" else 1,
                    due or datetime.max, task["id"])

        ranked = sorted(tasks, key=key)
        first = ranked[0]
        reasons = []
        status = deadline_state(first.get("deadline_date"), first.get("deadline_time"))
        if status == "overdue":
            reasons.append("it is overdue")
        if first.get("priority") == "urgent":
            reasons.append("it is marked urgent")
        if status in ("soon", "normal"):
            reasons.append("it is due %s" % format_deadline(first["deadline_date"], first.get("deadline_time")))
        why = (" because " + " and ".join(reasons)) if reasons else " (no task has a deadline, so I took the oldest)"
        lines = ["I'd start with \"%s\"%s." % (first["title"], why)]
        if len(ranked) > 1:
            lines.append("After that: " + ", ".join("\"%s\"" % t["title"] for t in ranked[1:4]) + ".")
        state["last_task_id"] = first["id"]
        return "\n".join(lines)

    def _howto_text(self, task):
        return build_plan(task, self.now())

    def _h_task_howto(self, text, user, state, tasks, people):
        if not tasks:
            return "You have no open tasks, so there is nothing to plan right now."
        task = match_task(text, tasks)
        if task is None and state.get("last_task_id") and re.search(r"\b(it|this|that|same)\b", normalize(text)):
            task = next((t for t in tasks if t["id"] == state["last_task_id"]), None)
        if task is None and len(tasks) == 1:
            task = tasks[0]
        if task is None:
            state["pending"] = "task_howto"
            names = "\n".join("- \"%s\"" % t["title"] for t in tasks[:MAX_LIST])
            return "Which task do you mean? You have:\n" + names
        state["last_task_id"] = task["id"]
        return self._howto_text(task)

    # ------------------------------------------------------------------ #
    #  Everyone: calendar
    # ------------------------------------------------------------------ #
    @staticmethod
    def _event_line(event):
        from_to = event["start_time"] or "All day"
        if event["start_time"] and event.get("end_time"):
            from_to += " – " + event["end_time"]
        return "%s  %s" % (from_to, event["title"])

    def _h_calendar_today(self, text, user, state, tasks, people):
        events = self.db.get_today_events(self.user_id)
        if not events:
            return "You have no events today."
        lines = ["Today you have %d event%s:" % (len(events), "" if len(events) == 1 else "s")]
        for event in events[:MAX_LIST]:
            lines.append("- " + self._event_line(event))
            if event.get("description"):
                lines.append("   " + _shorten(event["description"]))
        return "\n".join(lines)

    def _h_calendar_upcoming(self, text, user, state, tasks, people):
        today = self.now().date()
        events = self.db.get_calendar_events_for_user(
            self.user_id, from_date=today.strftime("%Y-%m-%d"),
            to_date=(today + timedelta(days=7)).strftime("%Y-%m-%d"))
        if not events:
            return "You have nothing on your calendar in the next 7 days."
        lines = ["Your next 7 days:"]
        for event in events[:MAX_LIST]:
            lines.append("- %s — %s" % (format_deadline(event["event_date"], today=today),
                                              self._event_line(event)))
        lines += _more(len(events) - MAX_LIST)
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Everyone: own numbers
    # ------------------------------------------------------------------ #
    def _h_my_stats(self, text, user, state, tasks, people):
        tags = concept_tags(normalize(text))
        want_week, want_today = "WEEK" in tags, "TODAY" in tags
        lines = []
        if want_today or not want_week:
            sessions = self.db.get_today_sessions(self.user_id)
            focus = sum(s["focus_seconds"] or 0 for s in sessions)
            distraction = sum(s["distraction_seconds"] or 0 for s in sessions)
            away = sum(s["away_seconds"] or 0 for s in sessions)
            if sessions and focus + distraction + away > 0:
                lines.append("Today: focus %s, distracted %s, away %s (%d session%s, focus rate %s%%)." % (
                    fmt_duration(focus), fmt_duration(distraction), fmt_duration(away),
                    len(sessions), "" if len(sessions) == 1 else "s",
                    _rate(focus, distraction, away)))
            else:
                lines.append("No tracked time today yet.")
        if want_week or not want_today:
            week = self.db.get_weekly_report(self.user_id)
            total = week["total_focus"] + week["total_distraction"] + week["total_away"]
            if total > 0:
                lines.append("Last 7 days: focus %s, distracted %s, away %s (%d sessions, focus rate %s%%)." % (
                    fmt_duration(week["total_focus"]), fmt_duration(week["total_distraction"]),
                    fmt_duration(week["total_away"]), week["total_sessions"],
                    _rate(week["total_focus"], week["total_distraction"], week["total_away"])))
            else:
                lines.append("No tracked time in the last 7 days.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Managers only (the gate is in ask())
    # ------------------------------------------------------------------ #
    def _h_team_status(self, text, user, state, tasks, people):
        status = self.db.get_employee_status_today()
        if not status:
            return "There are no employees yet."
        totals = self.db.get_today_totals()
        active = self.db.get_active_session_count_today()
        lines = ["Team today (%d employee%s): %d with a running session. Total focus %s, distracted %s, away %s."
                 % (len(status), "" if len(status) == 1 else "s", active,
                    fmt_duration(totals["focus_seconds"]), fmt_duration(totals["distraction_seconds"]),
                    fmt_duration(totals["away_seconds"])),
                 "Per employee:"]
        for row in status[:MAX_LIST]:
            if row["status"] == "absent":
                lines.append("- %s: absent today" % row["full_name"])
            else:
                lines.append("- %s: focus %s, distracted %s, away %s" % (
                    row["full_name"], fmt_duration(row["focus_seconds"]),
                    fmt_duration(row["distraction_seconds"]), fmt_duration(row["away_seconds"])))
        lines += _more(len(status) - MAX_LIST)
        high = self.db.get_high_distraction_employees(HIGH_DISTRACTION_SECONDS)
        if high:
            lines.append("High distraction (over 1h today): " + ", ".join(h["full_name"] for h in high) + ".")
        return "\n".join(lines)

    def _h_active_now(self, text, user, state, tasks, people):
        active = self.db.get_active_employees_today()
        if not active:
            return "Nobody has a running session right now."
        return "%d employee%s with a running session: %s." % (
            len(active), "" if len(active) == 1 else "s", ", ".join(a["full_name"] for a in active))

    def _ranking(self, week):
        """Per-employee rows ``(name, focus, distraction, away, rate)`` with enough tracked time."""
        if week:
            rows = [(r["full_name"], r["total_focus"], r["total_distraction"], r["total_away"])
                    for r in self.db.get_weekly_report_all()]
            minimum = MIN_TRACKED_WEEK
        else:
            rows = [(r["full_name"], r["focus_seconds"], r["distraction_seconds"], r["away_seconds"])
                    for r in self.db.get_today_totals_per_user()]
            minimum = MIN_TRACKED_TODAY
        counted = [(n, f, d, a, _rate(f, d, a)) for n, f, d, a in rows if f + d + a >= minimum]
        counted.sort(key=lambda row: (-row[4], -row[1], row[0]))
        return counted, minimum

    def _h_best_performer(self, text, user, state, tasks, people):
        week = "TODAY" not in concept_tags(normalize(text))
        ranking, minimum = self._ranking(week)
        label = "the last 7 days" if week else "today"
        if not ranking:
            return ("Nobody has at least %s of tracked time over %s yet, so I can't rank anyone fairly."
                    % (fmt_duration(minimum), label))
        lines = ["Most focused over %s (focus rate = focus time / tracked time):" % label]
        for place, (name, focus, distraction, away, rate) in enumerate(ranking[:3], 1):
            lines.append("%d. %s — focus %s, focus rate %s%%" % (place, name, fmt_duration(focus), rate))
        lines.append("This is based on tracked camera and screen time only, not on the quality of anyone's work.")
        return "\n".join(lines)

    def _h_check_in(self, text, user, state, tasks, people):
        lines = []
        high = self.db.get_high_distraction_employees(HIGH_DISTRACTION_SECONDS)
        if high:
            lines.append("Over 1 hour of distraction today:")
            lines += ["- %s: distracted %s" % (h["full_name"], fmt_duration(h["distraction_seconds"])) for h in high]
        else:
            ranking = []
            for row in self.db.get_today_totals_per_user():
                tracked = row["focus_seconds"] + row["distraction_seconds"] + row["away_seconds"]
                if tracked >= MIN_TRACKED_TODAY and row["distraction_seconds"] > 0:
                    ranking.append((row["distraction_seconds"] / tracked, row))
            ranking.sort(key=lambda pair: -pair[0])
            if ranking:
                lines.append("Nobody passed 1 hour of distraction today. The highest share of distraction:")
                for share, row in ranking[:3]:
                    lines.append("- %s: distracted %s (%d%% of tracked time)" % (
                        row["full_name"], fmt_duration(row["distraction_seconds"]), round(100 * share)))
        absent = self.db.get_absent_employees(days=3)
        if absent:
            lines.append("Not seen for 3+ days: " + ", ".join(a["full_name"] for a in absent) + ".")
        return "\n".join(lines) if lines else "Nobody stands out today: no heavy distraction and nobody missing for days."

    def _h_absent(self, text, user, state, tasks, people):
        today = [r["full_name"] for r in self.db.get_employee_status_today() if r["status"] == "absent"]
        long = [a["full_name"] for a in self.db.get_absent_employees(days=3)]
        if not today and not long:
            return "Everyone has been working today."
        lines = []
        if today:
            lines.append("No session yet today: " + ", ".join(today) + ".")
        if long:
            lines.append("Not seen for 3+ days: " + ", ".join(long) + ".")
        return "\n".join(lines)

    def _h_weekly_summary(self, text, user, state, tasks, people):
        report = self.db.get_weekly_report_all()
        if not report:
            return "There are no employees yet."
        lines = ["Last 7 days:"]
        tf = td = ta = 0
        for row in report[:MAX_LIST]:
            f, d, a = row["total_focus"], row["total_distraction"], row["total_away"]
            tf, td, ta = tf + f, td + d, ta + a
            if f + d + a == 0:
                lines.append("- %s: no tracked time" % row["full_name"])
            else:
                lines.append("- %s: focus %s, distracted %s, away %s, %d sessions, focus rate %s%%" % (
                    row["full_name"], fmt_duration(f), fmt_duration(d), fmt_duration(a),
                    row["total_sessions"], _rate(f, d, a)))
        lines += _more(len(report) - MAX_LIST)
        lines.append("Team total: focus %s, distracted %s, away %s." % (fmt_duration(tf), fmt_duration(td), fmt_duration(ta)))
        ranking, _minimum = self._ranking(True)
        if ranking:
            lines.append("Most focused: %s (%s%%)." % (ranking[0][0], ranking[0][4]))
        return "\n".join(lines)

    def _employee_text(self, person, user):
        today = next((r for r in self.db.get_employee_status_today() if r["id"] == person["id"]), None)
        week = next((r for r in self.db.get_weekly_report_all() if r["id"] == person["id"]), None)
        open_tasks = [t for t in self.db.get_tasks(person["id"]) if not t["is_done"]]
        overdue = [t for t in open_tasks if deadline_state(t.get("deadline_date"), t.get("deadline_time")) == "overdue"]
        lines = ["%s:" % person["full_name"]]
        if today is None or today["status"] == "absent":
            lines.append("- Today: no session yet.")
        else:
            lines.append("- Today: focus %s, distracted %s, away %s." % (
                fmt_duration(today["focus_seconds"]), fmt_duration(today["distraction_seconds"]),
                fmt_duration(today["away_seconds"])))
        if week and week["total_focus"] + week["total_distraction"] + week["total_away"] > 0:
            lines.append("- Last 7 days: focus %s, distracted %s, away %s, %d sessions, focus rate %s%%." % (
                fmt_duration(week["total_focus"]), fmt_duration(week["total_distraction"]),
                fmt_duration(week["total_away"]), week["total_sessions"],
                _rate(week["total_focus"], week["total_distraction"], week["total_away"])))
        else:
            lines.append("- Last 7 days: no tracked time.")
        lines.append("- Open tasks: %d%s." % (len(open_tasks), (" (%d overdue)" % len(overdue)) if overdue else ""))
        return "\n".join(lines)

    def _h_employee_status(self, text, user, state, tasks, people):
        found = match_people(text, people)
        # "and today?", "what about this week" -- the same person as before; but an
        # unknown name ("how is john doing") must not be silently taken for them.
        follow_up = (re.search(r"(he|she|him|her|his|they|them|also|and|how about|what about)",
                               normalize(text)) or len(normalize(text).split()) <= 3)
        if not found and state.get("last_person_id") and follow_up:
            found = [p for p in people if p["id"] == state["last_person_id"]]
        if not found:
            state["pending"] = "employee_status"
            return "Which employee do you mean?\n" + "\n".join("- " + p["full_name"] for p in people[:MAX_LIST])
        state["last_person_id"] = found[0]["id"]
        return self._employee_text(found[0], user)

    # ------------------------------------------------------------------ #
    #  Fallback
    # ------------------------------------------------------------------ #
    def _unknown(self, masked, user, is_manager, confidence):
        probs = self.classifier.probabilities(masked)
        allowed = [i for i in EXAMPLES if is_manager or i not in MANAGER_INTENTS]
        ranked = sorted(allowed, key=lambda i: -probs.get(i, 0.0))
        text = "I'm not sure I understood that. I can help with your tasks, deadlines, calendar"
        text += " and the team's performance." if is_manager else " and your own focus time."
        if probs.get(ranked[0], 0.0) >= 0.15:
            text += " Did you mean: \"%s\"?" % EXAMPLES[ranked[0]]
        else:
            text += " For example: \"%s\"" % EXAMPLES["list_tasks"]
        return Reply(text, UNKNOWN, confidence)
