"""Step-by-step plans for "how do I do this task?".

The assistant does not know the employee's field, so it cannot explain *how to
calculate* a number or *what a good report looks like*.  What it can do is give a
sensible, organised plan: it recognises the kind of work from the words in the
task (a document, a review, a meeting, an email, coding, ...), starts from what
the task description says, and spreads the steps over the time left until the
deadline.  Everything here is plain Python (no Qt, no database).
"""

from datetime import datetime

from assistant.entities import words
from assistant.formatting import format_deadline
from database.db_manager import deadline_due_datetime

# (name, trigger words, steps).  The first category with the most trigger words
# found in the task's title / description wins.
PLAYBOOKS = [
    ("document", {"report", "proposal", "summary", "document", "paper", "analysis",
                  "brief", "memo", "newsletter", "article", "documentation", "plan",
                  "write", "draft", "q1", "q2", "q3", "q4", "quarterly", "monthly", "weekly"}, [
        "Be clear what it has to cover and who will read it.",
        "Collect the facts, numbers and files you will need.",
        "Outline the sections before you write anything.",
        "Write a first draft without polishing it yet.",
        "Check the figures, the wording and the formatting.",
        "Send or hand it in, and confirm it arrived.",
    ]),
    ("presentation", {"presentation", "slides", "deck", "demo", "pitch", "talk",
                      "webinar", "present"}, [
        "Decide the one message the audience should remember.",
        "Outline the story: problem, solution, result.",
        "Build the slides or demo material.",
        "Rehearse out loud once, with a timer.",
        "Test the equipment and files before you start.",
    ]),
    ("review", {"review", "check", "audit", "proofread", "verify", "validate",
                "inspect", "approve", "qa", "test", "testing", "feedback"}, [
        "Agree what \"good\" looks like: the criteria or checklist.",
        "Go through everything once without changing anything.",
        "Write down each problem you find, with where it is.",
        "Prioritise: what must change, what is only a suggestion.",
        "Send your feedback and say when you can look again.",
    ]),
    ("meeting", {"meeting", "call", "interview", "standup", "kickoff", "workshop",
                 "sync", "conference"}, [
        "Write down the goal of the meeting and the questions you need answered.",
        "Prepare the facts or documents people will ask about.",
        "Send the agenda or invitation to everyone involved.",
        "Take notes during the meeting: decisions and who does what.",
        "Send the notes and actions afterwards.",
    ]),
    ("email", {"email", "e-mail", "message", "reply", "contact", "letter", "respond",
               "notify", "announce", "inform", "follow", "followup"}, [
        "Decide what you want the reader to do or know.",
        "Collect any numbers, dates or attachments to mention.",
        "Write it short: the request first, details after.",
        "Read it once more before you send it.",
        "Note when to follow up if there is no answer.",
    ]),
    ("software", {"code", "develop", "implement", "fix", "bug", "app", "flutter",
                  "website", "feature", "api", "script", "program", "deploy", "build",
                  "login", "screen", "database", "backend", "frontend", "refactor",
                  "auth", "authentication", "module", "function"}, [
        "Write down exactly what it should do when it is finished.",
        "Break it into small pieces you can finish one at a time.",
        "Build the smallest working version first.",
        "Test each piece, including the unusual cases.",
        "Clean up, commit your work and note anything left open.",
    ]),
    ("design", {"design", "mockup", "logo", "ui", "ux", "layout", "prototype",
                "wireframe", "poster", "redesign", "brand", "banner"}, [
        "Collect what it must show and any brand rules.",
        "Sketch two or three rough ideas quickly.",
        "Pick one and build it properly.",
        "Get feedback from one other person.",
        "Export the final files in the formats needed.",
    ]),
    ("research", {"research", "investigate", "study", "learn", "read", "explore",
                  "analyze", "analyse", "compare", "survey", "evaluate", "find"}, [
        "Write down the question you want answered.",
        "List where the answer could be found.",
        "Collect the material and note the key points as you read.",
        "Compare what you found and decide the answer.",
        "Write a short summary with your conclusion.",
    ]),
    ("finance", {"budget", "invoice", "payment", "expense", "expenses", "payroll",
                 "tax", "finance", "accounting", "cost", "costs", "pricing", "quote"}, [
        "Gather the source documents (invoices, statements, previous figures).",
        "Enter or check the numbers line by line.",
        "Re-add the totals and compare them with the last period.",
        "Mark anything that looks unusual and find out why.",
        "Hand it in with a one-line summary of the result.",
    ]),
    ("data", {"data", "entry", "records", "crm", "spreadsheet", "excel", "enter",
              "input", "clean", "sort", "inventory", "update", "list", "files"}, [
        "Look at the data and decide the exact format you need.",
        "Work through it in batches rather than all at once.",
        "Spot-check a few rows after each batch.",
        "Fix the errors you find and note the pattern.",
        "Save a copy and tell people the data is up to date.",
    ]),
    ("errand", {"buy", "order", "purchase", "pick", "deliver", "collect", "shop",
                "bring", "milk", "groceries", "book", "reserve"}, [
        "Write down exactly what you need and how much.",
        "Decide where and when you will do it.",
        "Do it, and keep the receipt or confirmation.",
        "Tick it off the list.",
    ]),
]

GENERIC_STEPS = [
    "Write down in one sentence what \"done\" means for this task.",
    "List the pieces it is made of and what you need for each.",
    "Start with the easiest piece to build momentum.",
    "Work on the hardest piece while you still have energy.",
    "Check the result against your \"done\" sentence, then hand it in.",
]


def choose_playbook(task):
    """``(name, steps)`` of the best matching playbook (or the generic one)."""
    title_words = set(words(task.get("title", "")))
    other_words = set(words(task.get("description") or ""))
    best_name, best_steps, best_score = "general", GENERIC_STEPS, 0
    for name, triggers, steps in PLAYBOOKS:
        score = 2 * len(title_words & triggers) + len(other_words & triggers)
        if score > best_score:
            best_name, best_steps, best_score = name, steps, score
    return best_name, best_steps


def _timing_note(task, now):
    """One sentence about the time left, built from the task's deadline."""
    due = deadline_due_datetime(task.get("deadline_date"), task.get("deadline_time"))
    if due is None:
        return "No deadline is set, so pick your own target date and write it down."
    when = format_deadline(task["deadline_date"], task.get("deadline_time"))
    if due < now:
        return ("It is already overdue (it was due %s). Do the smallest step that moves "
                "it forward first, and tell your manager if you need more time." % when)
    hours = (due - now).total_seconds() / 3600
    if hours <= 6:
        return "It is due %s, only a few hours away: skip polishing and aim to finish an hour early." % when
    days = (due.date() - now.date()).days
    if days <= 0:
        return "It is due %s, so plan to finish it today." % when
    if days <= 2:
        return ("It is due %s. Aim to have a first version done by the end of today and "
                "keep the last day for checking." % when)
    midpoint = (now + (due - now) / 2).strftime("%b %d").replace(" 0", " ")
    return ("It is due %s, about %d days from now. A good rhythm: first draft by %s, "
            "then use the last day to check it." % (when, days, midpoint))


def build_plan(task, now=None):
    """The full reply text for one task: intro, numbered steps, timing, honest note."""
    now = now or datetime.now()
    _name, steps = choose_playbook(task)
    description = (task.get("description") or "").strip()

    lines = ["Here is one way to tackle \"%s\":" % task["title"]]
    numbered = []
    if description:
        numbered.append("Start from what the task says: %s" % description.rstrip(".") + ".")
    numbered.extend(steps)
    for index, step in enumerate(numbered, 1):
        lines.append("%d. %s" % (index, step))
    lines.append("")
    if task.get("priority") == "urgent":
        lines.append("It is marked urgent, so start now.")
    lines.append(_timing_note(task, now))
    if not description:
        lines.append("This is a general plan. If you add details to the task, or ask your "
                     "manager for them, the plan can use them.")
    return "\n".join(lines)
