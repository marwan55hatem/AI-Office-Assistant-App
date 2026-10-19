"""Stand-alone test of the chat backend and the assistant engine.

Run from the project folder (it uses a throw-away database, never your real one)::

    python chat/selftest.py

It checks the chat storage, every kind of question for an employee and for a
manager, that an employee can never reach team data, and that all numbers in the
replies agree with an independent SQL calculation.  No Qt is involved.
"""

import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_LLM"] = "0"       # the first sections test the engine alone; the LLM section switches it on

from assistant.formatting import fmt_duration  # noqa: E402
from chat.chat_client import ChatClient  # noqa: E402
from database.db_manager import DatabaseManager  # noqa: E402

RESULTS = {}


def check(label, condition, detail=""):
    RESULTS[label] = bool(condition)
    print(("PASS  " if condition else "FAIL  ") + label + (("   " + str(detail)) if not condition and detail else ""))


def add_session(db, user_id, days_ago, focus, distraction, away, running=False):
    day = (date.today() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    db.conn.execute(
        "INSERT INTO sessions (user_id, date, start_time, end_time, focus_seconds,"
        " distraction_seconds, away_seconds) VALUES (?, ?, '09:00:00', ?, ?, ?, ?)",
        (user_id, day, None if running else "10:00:00", focus, distraction, away),
    )
    db.conn.commit()


def sql_week(db, user_id):
    row = db.conn.execute(
        "SELECT COALESCE(SUM(focus_seconds),0), COALESCE(SUM(distraction_seconds),0),"
        " COALESCE(SUM(away_seconds),0) FROM sessions WHERE user_id=? AND date >= ?",
        (user_id, (date.today() - timedelta(days=6)).strftime("%Y-%m-%d")),
    ).fetchone()
    return tuple(row)


def sql_today(db, user_id):
    row = db.conn.execute(
        "SELECT COALESCE(SUM(focus_seconds),0), COALESCE(SUM(distraction_seconds),0),"
        " COALESCE(SUM(away_seconds),0) FROM sessions WHERE user_id=? AND date = ?",
        (user_id, date.today().strftime("%Y-%m-%d")),
    ).fetchone()
    return tuple(row)


def main():
    with tempfile.TemporaryDirectory() as folder:
        db = DatabaseManager(os.path.join(folder, "chat_selftest.db"))
        manager = db.get_user("manager", "1234", "manager")["id"]
        marwan = db.get_user("marwan", "1234", "employee")["id"]

        def employee(username, name):
            db.create_signup_request(username, "1234", name)
            uid = db.get_user(username, "1234", "employee")["id"]
            db.approve_user(uid)
            return uid

        sara, omar, layla = employee("sara", "Sara Ali"), employee("omar", "Omar Khaled"), employee("layla", "Layla Hassan")

        # ---- sessions: known numbers --------------------------------------
        add_session(db, marwan, 0, 2700, 300, 0)                    # today 45m / 5m / 0
        add_session(db, marwan, 1, 21600, 1800, 600)                # yesterday
        add_session(db, marwan, 2, 18000, 3600, 0)
        add_session(db, sara, 0, 1800, 4200, 300, running=True)     # today, running: 30m focus, 70m distracted
        add_session(db, sara, 1, 10800, 7200, 0)
        add_session(db, omar, 10, 3600, 0, 0)                       # not seen for days
        # ---- tasks ---------------------------------------------------------
        now = datetime.now()
        d = lambda days, hhmm=None: ((now + timedelta(days=days)).strftime("%Y-%m-%d"), hhmm)
        db.add_task(marwan, "Prepare Q3 report", assigned_by=manager,
                    description="Numbers from finance are in the shared drive.",
                    deadline_date=d(4)[0], deadline_time="14:00")
        db.add_task(marwan, "Finish the Flutter app", priority="urgent", assigned_by=manager,
                    description="Complete all auth screens.", deadline_date=(now + timedelta(hours=5)).strftime("%Y-%m-%d"),
                    deadline_time=(now + timedelta(hours=5)).strftime("%H:%M"))   # always inside "24 hours", at any time of day
        db.add_task(marwan, "Buy milk")
        db.add_task(marwan, "Old overdue thing", assigned_by=manager, deadline_date=d(-1)[0], deadline_time="09:00")
        done = db.add_task(marwan, "Review budget", assigned_by=manager)
        db.toggle_task(done)
        db.add_task(sara, "Secret Sara task", assigned_by=manager)
        # ---- calendar ------------------------------------------------------
        e1 = db.create_calendar_event("Team day", d(0)[0], manager)
        db.set_calendar_attendees(e1, [marwan, sara])
        e2 = db.create_calendar_event("Kickoff", d(1)[0], manager, start_time="14:00", end_time="15:00",
                                      description="Project kickoff in room 2")
        db.set_calendar_attendees(e2, [marwan])

        # =================================================================
        print("\n--- chat storage -------------------------------------------")
        client = ChatClient(db, marwan)
        chat = client.new_chat()
        check("new chat has the default title", chat.title == "New Chat" and chat.message_count == 0)
        client.send_message(chat.id, "Hello, who are you?")
        stream = client.stream_reply(chat.id, delay=0)
        shown = "".join(stream)
        check("stream yields the full reply, chunk by chunk", shown == stream.full_text and len(list(iter(stream))) > 3)
        client.save_reply(chat.id, stream.full_text)
        client.send_message(chat.id, "What tasks do I have?")
        stream = client.stream_reply(chat.id, delay=0)
        client.save_reply(chat.id, stream.full_text)
        msgs = client.get_messages(chat.id)
        check("3+ messages read back in order", [m.role for m in msgs] == ["user", "assistant", "user", "assistant"])
        check("limit returns the last N", [m.role for m in client.get_messages(chat.id, 2)] == ["user", "assistant"])
        check("auto-title is the first 40 characters", client.auto_title(chat.id) == "Hello, who are you?")
        check("rename works", client.rename_chat(chat.id, "My questions")[0] and client.list_chats()[0].title == "My questions")
        check("blank rename refused", not client.rename_chat(chat.id, "   ")[0])
        other = ChatClient(db, sara)
        try:
            other.delete_chat(chat.id)
            check("another user cannot delete my chat", False)
        except PermissionError:
            check("another user cannot delete my chat", True)
        try:
            other.get_messages(chat.id)
            check("another user cannot read my chat", False)
        except PermissionError:
            check("another user cannot read my chat", True)
        check("list shows count + snippet", client.list_chats()[0].message_count == 4 and client.list_chats()[0].last_message)
        check("delete removes chat and messages", client.delete_chat(chat.id)[0] and client.list_chats() == []
              and db.count_ai_messages(chat.id) == 0)

        # =================================================================
        print("\n--- employee questions (Marwan) ----------------------------")
        team_calls = []
        for name in ("get_employee_status_today", "get_weekly_report_all", "get_today_totals_per_user",
                     "get_all_employees", "get_active_employees_today", "get_high_distraction_employees",
                     "get_absent_employees", "get_today_totals", "get_active_session_count_today",
                     "get_pending_users", "get_all_users"):
            original = getattr(db, name)
            setattr(db, name, (lambda n, f: (lambda *a, **k: (team_calls.append(n), f(*a, **k))[1]))(name, original))

        cc = ChatClient(db, marwan)
        cid = cc.new_chat().id

        def say(text):
            cc.send_message(cid, text)
            stream = cc.stream_reply(cid, delay=0)
            cc.save_reply(cid, stream.full_text)
            return stream.intent, stream.full_text

        intent, text = say("what did i just say")
        check("recall at the start of a chat", intent == "recall" and "start of our conversation" in text, text)
        intent, text = say("hello")
        check("greeting uses the first name", intent == "greeting" and "Marwan" in text)
        intent, text = say("What did I just say?")
        check("recall repeats the previous question", intent == "recall" and 'You just asked: "hello"' in text
              and "a greeting" in text and "Before that" in text, text)
        intent, text = say("What tasks do I have?")
        check("lists the 4 open tasks", intent == "list_tasks" and "4 open tasks" in text and all(
            t in text for t in ("Prepare Q3 report", "Finish the Flutter app", "Buy milk", "Old overdue thing")), text)
        check("does not list done or other people's tasks", "Review budget" not in text and "Secret Sara task" not in text)
        check("shows assigner, urgency, deadline and description", "assigned by Admin Manager" in text and "[URGENT]" in text
              and (now + timedelta(hours=5)).strftime("%H:%M") in text and "Complete all auth screens" in text and "personal" in text)
        intent, text = say("How should I start on the Q3 report?")
        check("how-to: recognises the task", intent == "task_howto" and "Prepare Q3 report" in text, text)
        check("how-to: uses the description", "Numbers from finance are in the shared drive" in text)
        check("how-to: gives numbered steps (document plan)", all(("%d. " % n) in text for n in range(1, 7)) and "Outline the sections" in text)
        check("how-to: uses the deadline", "days from now" in text and "first draft by" in text)
        intent, text = say("how do i do the flutter app")
        check("how-to: software plan + urgency", "Test each piece" in text and "marked urgent" in text, text)
        intent, text = say("how do I start?")
        check("how-to without a task asks which one", "Which task do you mean?" in text and "Buy milk" in text)
        intent, text = say("the milk one")
        check("follow-up answers the question", intent == "task_howto" and "Buy milk" in text and "Do it, and keep the receipt" in text, text)
        intent, text = say("what's due soon")
        check("deadlines: overdue + 24h + week blocks", intent == "task_deadlines" and "Overdue:" in text and "Old overdue thing" in text
              and "Due within 24 hours:" in text and "Finish the Flutter app" in text and "Prepare Q3 report" in text, text)
        intent, text = say("what should i do first")
        check("next: overdue task first, with the reason", intent == "task_next" and "I'd start with \"Old overdue thing\"" in text and "overdue" in text, text)
        intent, text = say("what's on my calendar today")
        check("calendar today", intent == "calendar_today" and "Team day" in text and "Kickoff" not in text, text)
        intent, text = say("what's coming up this week")
        check("calendar upcoming", intent == "calendar_upcoming" and "Kickoff" in text and "14:00" in text and "Team day" in text, text)
        f, dsum, a = sql_today(db, marwan)
        wf, wd, wa = sql_week(db, marwan)
        intent, text = say("how was my focus today")
        check("my stats (today) match SQL", intent == "my_stats" and fmt_duration(f) in text and fmt_duration(dsum) in text, text)
        intent, text = say("show my weekly summary")
        check("my stats (week) match SQL", fmt_duration(wf) in text and fmt_duration(wd) in text and "Last 7 days" in text, text)
        intent, text = say("who is the president of france")
        check("off-topic: honest 'not sure', no invented tasks", intent == "unknown" and "not sure" in text.lower() and "Prepare" not in text)
        intent, text = say("مرحبا")
        check("Arabic greeting understood", intent == "greeting")
        intent, text = say("ما هي مهامي")
        check("Arabic task list understood", intent == "list_tasks" and "Buy milk" in text)
        intent, text = say("waht taks do i hav")
        check("typos: still the task list", intent == "list_tasks", intent)

        print("\n--- privacy: an employee asks about the team ----------------")
        for question in ("who is the best performer", "How is the team doing today?", "who is absent",
                         "who should I check in on", "summarize last week's performance",
                         "how is Sara doing", "who is working right now"):
            intent, text = say(question)
            leaked = [n for n in ("Sara", "Omar", "Layla", "Secret") if n in text]
            check("employee refused: %r" % question, intent == "denied" and "only available to managers" in text and not leaked, text)
        check("no team data was even READ for the employee", team_calls == [], team_calls)

        # =================================================================
        print("\n--- manager questions --------------------------------------")
        mc = ChatClient(db, manager)
        mid = mc.new_chat().id

        def msay(text):
            mc.send_message(mid, text)
            stream = mc.stream_reply(mid, delay=0)
            mc.save_reply(mid, stream.full_text)
            return stream.intent, stream.full_text

        intent, text = msay("How is the team doing today?")
        employees = db.get_all_employees()
        check("team status: employee count + totals", intent == "team_status" and "Team today (%d employees)" % len(employees) in text, text)
        tf = sum(sql_today(db, u)[0] for u in (marwan, sara, omar, layla))
        td = sum(sql_today(db, u)[1] for u in (marwan, sara, omar, layla))
        check("team status: total focus / distraction from SQL", "Total focus %s" % fmt_duration(tf) in text and "distracted %s" % fmt_duration(td) in text, text)
        check("team status: absent employees named", "Omar Khaled: absent today" in text and "Layla Hassan: absent today" in text)
        check("team status: per-employee numbers", "Marwan Hatem: focus 45m, distracted 5m, away 0m" in text, text)
        check("team status: high distraction flagged", "High distraction (over 1h today): Sara Ali" in text)
        intent, text = msay("who is working right now")
        check("active now = the running session", intent == "active_now" and "Sara Ali" in text and "Marwan" not in text, text)

        # best performer, computed independently
        rows = []
        for uid, name in ((marwan, "Marwan Hatem"), (sara, "Sara Ali"), (omar, "Omar Khaled"), (layla, "Layla Hassan")):
            f, dd, aa = sql_week(db, uid)
            if f + dd + aa >= 3600:
                rows.append((round(100.0 * f / (f + dd + aa)), f, name))
        rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
        intent, text = msay("Who is the best performer?")
        check("best performer: right person and numbers", intent == "best_performer" and ("1. %s" % rows[0][2]) in text
              and fmt_duration(rows[0][1]) in text and ("%d%%" % rows[0][0]) in text, text)
        check("best performer: says what it measures", "tracked camera and screen time only" in text)
        check("best performer: ranking order matches SQL", all(("%d. %s" % (i + 1, r[2])) in text for i, r in enumerate(rows[:3])))
        intent, text = msay("who deserves recognition today")
        check("best performer (today) is answered", intent == "best_performer" and "today" in text, text)
        intent, text = msay("Who should I check in on?")
        check("check-in names the distracted employee", intent == "check_in" and "Sara Ali" in text and "1h 10m" in text, text)
        check("check-in also lists people missing for days", "Omar Khaled" in text and "Layla Hassan" in text)
        intent, text = msay("who is absent?")
        check("absent: today + 3 days", intent == "absent" and "Omar Khaled" in text and "Layla Hassan" in text, text)
        intent, text = msay("Summarize last week's performance")
        total_f = sum(sql_week(db, u)[0] for u in (marwan, sara, omar, layla))
        total_d = sum(sql_week(db, u)[1] for u in (marwan, sara, omar, layla))
        check("weekly summary: team totals from SQL", intent == "weekly_summary" and "Team total: focus %s, distracted %s" % (fmt_duration(total_f), fmt_duration(total_d)) in text, text)
        intent, text = msay("How is Sara doing?")
        sf, sd, sa = sql_today(db, sara)
        check("employee status: Sara's numbers", intent == "employee_status" and "Sara Ali" in text and "focus %s" % fmt_duration(sf) in text, text)
        intent, text = msay("and Omar?")
        check("follow-up 'and Omar?'", intent == "employee_status" and "Omar Khaled" in text and "no session yet" in text, text)
        intent, text = msay("how is john doing")
        check("an unknown name asks which employee is meant", "Which employee" in text and "Sara Ali" in text, text)
        intent, text = msay("what tasks do i have")
        check("manager's own tasks are separate (none)", "no open tasks" in text.lower())
        intent, text = msay("hello")
        check("manager greeting mentions the team", "team's performance" in text)

        # =================================================================
        print("\n--- language model: routing, memory, privacy ---------------")
        from llm.prompts import STOPPED_MARK
        db.add_task(layla, "Layla private task", assigned_by=manager, description="Layla secret details")

        def llm_client(uid, ready=True):
            c = ChatClient(db, uid)
            c.backend.llm_enabled = True
            c.backend._model_present = (lambda: True) if ready else (lambda: False)
            return c, c.new_chat().id

        def route(c, cid, text, answer=None, source=None):
            """Send ``text``; returns the stream.  ``answer`` is stored as the reply (like the UI does)."""
            c.send_message(cid, text)
            s = c.stream_reply(cid, delay=0)
            c.save_reply(cid, answer if answer is not None else (s.full_text or "(model reply)"), source or s.source)
            return s

        lc, lid = llm_client(marwan)
        s = route(lc, lid, "How do I build a CNN model?")
        check("general question -> language model", s.kind == "llm" and s.source == "llm" and s.intent == "general")
        check("...prompt = system + the question only", [m["role"] for m in s.messages] == ["system", "user"] and s.messages[-1]["content"] == "How do I build a CNN model?")
        check("...engine's own answer is kept as the fallback", "not sure" in s.fallback_text.lower())
        for q, want in (("What tasks do I have?", "list_tasks"), ("how do I start?", "task_howto"), ("hello", "greeting"),
                        ("What's due soon?", "task_deadlines"), ("how much did I focus today", "my_stats")):
            s = route(lc, lid, q)
            check("app question stays with the engine: %s" % q, s.kind == "text" and s.source == "engine" and s.intent == want, (s.intent, s.full_text))
        s = route(lc, lid, "How should I start on the Q3 report?")
        check("a named task still gets its plan from the engine", s.kind == "text" and "Prepare Q3 report" in s.full_text and "1. " in s.full_text)

        for q in ("What is overfitting?", "what is dropout", "What is a loss function?", "how does backpropagation work", "and how can I prevent it?"):
            s = route(lc, lid, q)
            check("general topic is not mistaken for a data question: %s" % q, s.kind == "llm", (s.intent, s.full_text[:60]))
        for q in ("what is due soon", "what is my deadline", "do I have any tasks", "which tasks are urgent", "what is on my calendar today"):
            s = route(lc, lid, q)
            check("data question stays with the engine even after model answers: %s" % q, s.kind == "text", (s.intent, s.full_text[:60]))

        lay, lay_id = llm_client(layla)
        s = route(lay, lay_id, "how to build a cnn model")
        check("a user with ONE open task asking a general how-to is not given that task's plan", s.kind == "llm" and "Layla" not in "".join(m["content"] for m in s.messages))
        s = route(lay, lay_id, "how do i start")
        check("...but 'how do I start' still means the single task", s.kind == "text" and "Layla private task" in s.full_text)

        s = route(lc, lid, "Who is the best performer?")
        check("employee team question: refused by the engine, never sent to the model", s.kind == "text" and s.intent == "denied" and "only available to managers" in s.full_text)
        off, off_id = llm_client(marwan, ready=False)
        s = route(off, off_id, "How do I build a CNN model?")
        check("model files missing -> the engine answers (honest 'not sure')", s.kind == "text" and "not sure" in s.full_text.lower())
        dis, dis_id = llm_client(marwan)
        dis.backend.llm_enabled = False
        s = route(dis, dis_id, "How do I build a CNN model?")
        check("switched off -> the engine answers", s.kind == "text" and s.source == "engine")

        # memory: only the model's own earlier turns are given back to it
        mem, mem_id = llm_client(marwan)
        route(mem, mem_id, "What tasks do I have?")                                    # engine turn (contains task data)
        route(mem, mem_id, "Explain overfitting", answer="Overfitting means memorising the training data.")
        s = route(mem, mem_id, "and how do I prevent it?", answer="Use dropout." + STOPPED_MARK)
        roles = [m["role"] for m in s.messages]
        check("follow-up gets the model's earlier Q&A", roles == ["system", "user", "assistant", "user"] and s.messages[1]["content"] == "Explain overfitting"
              and s.messages[2]["content"] == "Overfitting means memorising the training data.", s.messages)
        check("...but not the engine's task answer", not any("Prepare Q3 report" in m["content"] for m in s.messages))
        s = route(mem, mem_id, "and what is dropout?")
        check("the '(stopped)' mark is removed from remembered replies", s.messages[4]["content"] == "Use dropout." and len(s.messages) == 6)
        for i in range(8):
            route(mem, mem_id, "Explain topic number %d" % i, answer="Answer %d" % i)
        s = route(mem, mem_id, "one more question")
        check("memory is limited to the last 6 pairs", len(s.messages) == 1 + 2 * 6 + 1 and s.messages[1]["content"] == "Explain topic number 2")
        sources = [m.source for m in mem.get_messages(mem_id)]
        check("each stored reply says who wrote it", "engine" in sources and "llm" in sources and sources[0] == "")

        # privacy: whatever the model is given contains no database content
        questions = ["How do I build a CNN model?", "what is overfitting", "who is the president of France", "explain RAG", "write a python loop"]
        private = ["Secret Sara task", "Prepare Q3 report", "Flutter", "Buy milk", "Old overdue", "Numbers from finance", "Layla private", "Layla secret",
                   "Sara Ali", "Omar Khaled", "Layla Hassan", "Marwan", "Admin Manager", "distracted", "focus time"]
        pm, pm_id = llm_client(manager)
        pe, pe_id = llm_client(marwan)
        pl, pl_id = llm_client(layla)
        leak = []
        for pc, pcid in ((pe, pe_id), (pm, pm_id), (pl, pl_id)):
            route(pc, pcid, "How is the team doing today?" if pc is pm else "what tasks do I have")      # data-bearing engine turn first
            for q in questions:
                s = route(pc, pcid, q)
                blob = json.dumps(s.messages, ensure_ascii=False)
                leak += [(q, p) for p in private if p.lower() in blob.lower()]
        check("the model's prompt never contains tasks, people or team numbers (employee, manager, 1-task user)", not leak, leak[:4])
        s = route(pm, pm_id, "How is the team doing today?")
        check("manager's team question is still answered by the engine from SQL", s.kind == "text" and s.intent == "team_status" and "Team today" in s.full_text)
        # ---- documents (RAG) ------------------------------------------------
        print("\n--- documents: retrieval, citation, privacy ----------------")
        from knowledge.store import KnowledgeBase
        kb = KnowledgeBase(db)
        kb.add_text("cnn_basics.md", "# CNN\n\n## Building a CNN in PyTorch\n\nTo build a CNN in PyTorch define a class that inherits from nn.Module and stack Conv2d, ReLU and MaxPool2d layers.\n\n"
                    "## Pooling layers\n\nPooling shrinks the feature maps.", "everyone", manager)
        kb.add_text("salary_bands.md", "# Confidential salary bands\n\nThe salary band for a senior engineer is level L5 with a bonus multiplier of 1.4.", "managers", manager)
        kb.add_text("expense_policy.txt", "# Expense policy\n\nTravel expenses must be claimed within 14 days.", "everyone", manager)

        de, de_id = llm_client(marwan)
        s = route(de, de_id, "How do I build a CNN model in PyTorch?", answer="Define a class that inherits from nn.Module. [cnn_basics.md]" )
        user_turn = s.messages[-1]["content"]
        check("document question: the model gets the passage and the question", s.kind == "llm" and s.intent == "documents"
              and "cnn_basics.md" in user_turn and "Conv2d" in user_turn and user_turn.rstrip().endswith("Question: How do I build a CNN model in PyTorch?"), user_turn[:200])
        check("...and the reply will name the source file", s.sources == ["cnn_basics.md"])
        check("...the passage is in the question turn, the system prompt is unchanged", "Conv2d" not in s.messages[0]["content"])
        s2 = route(de, de_id, "and what about pooling?")
        check("a follow-up gets the earlier answer WITHOUT its passages or the Sources line", s2.kind == "llm" and s2.messages[2]["content"] == "Define a class that inherits from nn.Module. [cnn_basics.md]"
              and not any("Conv2d" in m["content"] for m in s2.messages[:-1]) and "Pooling shrinks" in s2.messages[-1]["content"], [m["content"][:60] for m in s2.messages])
        from llm.prompts import clean_reply, with_sources
        check("with_sources / clean_reply round-trip", clean_reply(with_sources("Answer.", ["a.md", "b.md"])) == "Answer." and with_sources("Answer.", []) == "Answer.")
        check("a reply that merely mentions 'Sources:' in the middle is left alone", clean_reply("Sources: are important\nmore text") == "Sources: are important\nmore text")

        s = route(de, de_id, "What is the salary band for a senior engineer?")
        blob = json.dumps(s.messages, ensure_ascii=False)
        check("employee asking about the manager-only document: nothing from it reaches the model", "L5" not in blob and "salary_bands" not in blob and "multiplier" not in blob and s.sources == [], blob[-200:])
        dm, dm_id = llm_client(manager)
        s = route(dm, dm_id, "What is the salary band for a senior engineer?")
        check("the manager gets it, with the file named", s.kind == "llm" and "L5" in s.messages[-1]["content"] and s.sources == ["salary_bands.md"], s.sources)
        s = route(de, de_id, "What is the salary band for a senior engineer?")
        check("...and an employee still gets nothing (same question, same database)", "L5" not in json.dumps(s.messages))

        no_llm, no_id = llm_client(marwan, ready=False)
        s = route(no_llm, no_id, "How do I build a CNN model in PyTorch?")
        check("no model available: the passage is quoted with its source", s.kind == "text" and s.intent == "documents" and "Conv2d" in s.full_text and s.full_text.endswith("Sources: cnn_basics.md"), s.full_text[-120:])
        s = route(no_llm, no_id, "What is the salary band for a senior engineer?")
        check("no model, employee, manager-only document: honest 'not sure', no leak", "L5" not in s.full_text and "not sure" in s.full_text.lower())
        s = route(de, de_id, "What is the capital of Japan?")
        check("a question the documents do not answer gets a plain model prompt", s.kind == "llm" and s.intent == "general" and s.sources == [] and s.messages[-1]["content"] == "What is the capital of Japan?")
        s = route(de, de_id, "What tasks do I have?")
        check("data questions are untouched by documents", s.kind == "text" and s.intent == "list_tasks")
        s = route(de, de_id, "How should I start on the Q3 report?")
        check("...a named task keeps its engine plan", s.kind == "text" and s.intent == "task_howto")
        for q in ("who is the best performer", "how is the team doing today"):
            s = route(de, de_id, q)
            check("employee team question stays refused with documents present: %s" % q, s.kind == "text" and s.intent == "denied")
        kb.remove(next(d["id"] for d in kb.documents(True) if d["filename"] == "cnn_basics.md"))
        s = route(de, de_id, "How do I build a CNN model in PyTorch?")
        check("after removing the document the model gets a plain prompt again", s.sources == [] and "Conv2d" not in json.dumps(s.messages))
        db.conn.execute("DELETE FROM knowledge_docs"); db.conn.commit()

        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(ai_messages)").fetchall()}
        check("ai_messages.source column exists", "source" in cols)

        # ---- speed + isolation -------------------------------------------
        start = time.perf_counter()
        for q in ("what tasks do i have", "how should i start on the Q3 report", "what is due soon"):
            for _ in range(10):
                say(q)
        per_reply = (time.perf_counter() - start) / 30
        check("replies are fast (%.0f ms each)" % (per_reply * 1000), per_reply < 0.5)
        check("no Qt was imported", not any(m.startswith("PyQt5") for m in sys.modules))
        db.close()

    ok = sum(RESULTS.values())
    print("\nSUMMARY %d / %d passed" % (ok, len(RESULTS)))
    return ok == len(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
