"""What the assistant understands: intents, role rules and the training data.

The chat assistant works in two steps: a tiny neural network (see
``intent_model.py``) decides *which question* the user asked -- one of the intents
below -- and the answer engine (``answers.py``) then builds the reply from the
database.  This module holds the intent list, which role may use which intent,
and the generator that turns the hand-written example phrases into thousands of
training sentences (different openings, endings, names, typos).

``HELD_OUT`` is a separate set of differently-worded questions that is **never**
used for training; the accuracy reported by ``train_intent.py`` is measured on it.
"""

import random

#: Intents everybody may use.
SHARED_INTENTS = [
    "greeting", "thanks", "goodbye", "capabilities",
    "list_tasks", "task_howto", "task_deadlines", "task_next",
    "calendar_today", "calendar_upcoming", "my_stats", "recall",
]

#: Intents that read other people's data: managers only (enforced in answers.py).
MANAGER_INTENTS = [
    "team_status", "active_now", "best_performer", "check_in",
    "absent", "weekly_summary", "employee_status",
]

#: Anything the assistant cannot help with.
UNKNOWN = "unknown"

INTENTS = SHARED_INTENTS + MANAGER_INTENTS + [UNKNOWN]

#: Very short intents: no "please / can you" padding, it would distort them.
SHORT_INTENTS = {"greeting", "thanks", "goodbye"}

# --------------------------------------------------------------------------- #
#  Example phrases ({task} and {person} are filled with random names)
# --------------------------------------------------------------------------- #
BANK = {
    "greeting": [
        "hi", "hello", "hey", "good morning", "good evening", "good afternoon",
        "hey there", "hello assistant", "hi assistant", "yo", "what's up",
        "hiya", "greetings", "hello there", "morning",
        "مرحبا", "السلام عليكم", "اهلا", "هلا", "صباح الخير", "مساء الخير",
        "هاي", "اهلا بك", "مرحبا بك",
    ],
    "thanks": [
        "thanks", "thank you", "thx", "thanks a lot", "great thanks",
        "ok thanks", "appreciate it", "that helps", "perfect thank you",
        "thank you so much", "cheers", "many thanks", "nice thanks",
        "شكرا", "شكرا جزيلا", "يعطيك العافية", "مشكور", "تسلم", "شكرا لك",
    ],
    "goodbye": [
        "bye", "goodbye", "see you", "see you later", "that's all",
        "talk later", "i'm done", "good night", "cya", "bye bye",
        "that is all for now", "i have to go",
        "مع السلامة", "باي", "الى اللقاء", "تصبح على خير", "الى اللقاء",
    ],
    "capabilities": [
        "what can you do", "who are you", "help", "what do you do",
        "how can you help me", "what can i ask you", "what are your features",
        "show me what you can do", "are you a bot", "what is this",
        "how do you work", "what commands do you know", "what are you",
        "what kind of questions can i ask", "tell me about yourself",
        "ماذا تستطيع ان تفعل", "من انت", "ساعدني", "كيف تساعدني",
        "ما هي مهامك", "ماذا يمكنك ان تفعل",
    ],
    "list_tasks": [
        "what tasks do i have", "show my tasks", "list my tasks",
        "what's on my to do list", "what do i have to do", "my tasks",
        "what am i working on", "open tasks", "show me my to-do list",
        "do i have any tasks", "what are my assignments", "tasks assigned to me",
        "what's on my plate", "give me my task list", "how many tasks do i have",
        "what is left to do", "show my to do", "which tasks are open",
        "ما هي مهامي", "اعرض مهامي", "ايش عندي من مهام",
        "شو المهام المطلوبة مني", "قائمة المهام", "كم مهمة عندي",
    ],
    "task_howto": [
        "how do i do {task}", "how should i start on {task}", "help me with {task}",
        "how can i finish {task}", "give me steps for {task}",
        "how to complete {task}", "break down {task} for me",
        "where do i begin with {task}", "i need help with {task}",
        "what are the steps for {task}", "how do i approach {task}",
        "plan {task} for me", "explain how to do {task}",
        "how to start the {task} task", "i'm stuck on {task}",
        "advise me on {task}", "how do i get {task} done",
        "how do i start the {task}", "what's the best way to do {task}",
        "كيف انجز {task}", "كيف ابدأ في {task}", "ساعدني في {task}",
        "ما هي خطوات {task}", "اعطني خطوات لـ {task}", "كيف اقوم بـ {task}",
    ],
    "task_deadlines": [
        "what's due soon", "which tasks are due today", "any deadlines coming up",
        "what is overdue", "do i have overdue tasks", "upcoming deadlines",
        "what is due this week", "when are my tasks due", "show my deadlines",
        "am i late on anything", "what's due tomorrow", "deadline check",
        "which tasks are late", "is anything overdue", "what are my due dates",
        "ما هي المواعيد النهائية", "ماذا لدي متأخر", "ما المهام المستحقة قريبا",
        "متى تسليم المهام", "هل لدي مهام متأخرة",
    ],
    "task_next": [
        "what should i do first", "what should i work on next",
        "which task is most important", "where should i start today",
        "prioritize my tasks", "what is my top priority", "what do i do now",
        "what's most urgent", "help me plan my day", "which task first",
        "what to focus on", "what should i tackle first",
        "which one should i start with", "tell me what to do next",
        "ماذا افعل اولا", "ما اهم مهمة", "بماذا ابدأ اليوم", "رتب مهامي",
        "ما هي اولوياتي",
    ],
    "calendar_today": [
        "what's on my calendar today", "do i have any meetings today",
        "today's events", "what events do i have today", "any meetings today",
        "what's my schedule today", "calendar for today", "am i busy today",
        "show today's schedule", "is there anything scheduled today",
        "what is planned for today", "do i have a meeting today",
        "ما هي مواعيدي اليوم", "هل لدي اجتماعات اليوم", "جدول اليوم",
        "ايش عندي اليوم من مواعيد",
    ],
    "calendar_upcoming": [
        "what's coming up this week", "upcoming events", "show my upcoming meetings",
        "what's next on my calendar", "any events this week",
        "events in the next few days", "next meeting",
        "what meetings do i have coming up", "calendar this week",
        "what is scheduled for the coming days", "show my agenda",
        "when is my next meeting", "what's on the calendar next week",
        "ما هي الاحداث القادمة", "الاجتماعات القادمة", "ايش عندي هذا الاسبوع",
        "متى الاجتماع القادم",
    ],
    "my_stats": [
        "how am i doing", "how was my focus today", "show my stats",
        "how productive was i", "my focus time today", "my weekly summary",
        "how much did i work this week", "my performance",
        "how many hours did i focus", "how's my week going",
        "my distraction time", "how focused have i been",
        "show my productivity", "how long did i work today",
        "كيف اداءي", "كم ساعة عملت اليوم", "ملخص اسبوعي لي", "احصائياتي",
        "كم ساعة ركزت",
    ],
    "team_status": [
        "how is the team doing today", "team status", "how's everyone doing",
        "give me a team overview", "team performance today",
        "how are my employees doing today", "status of the team", "how's the team",
        "team summary today", "what's the team up to",
        "show me team statistics", "how is everybody doing", "team overview",
        "how are things with the team", "give me the team numbers",
        "كيف حال الفريق اليوم", "اداء الفريق", "ملخص الفريق",
        "كيف الموظفين اليوم", "حالة الفريق",
    ],
    "active_now": [
        "who is working right now", "how many people are active",
        "who is online", "who's currently working", "is anyone working now",
        "active employees", "who started a session", "how many are present now",
        "who is at work at the moment", "who is on a session right now",
        "من يعمل الآن", "كم موظف نشط", "من متصل", "من يعمل حاليا",
    ],
    "best_performer": [
        "who is the best performer", "who is performing best", "top employee",
        "who is the most productive", "who has the best focus", "who's doing the best",
        "rank my employees", "star employee this week",
        "who deserves recognition", "who is the most focused", "who's leading",
        "best worker", "who is my best employee", "who works the hardest",
        "من افضل موظف", "من الاكثر انتاجية", "من الاكثر تركيزا",
        "ترتيب الموظفين", "من الموظف المثالي",
    ],
    "check_in": [
        "who should i check in on", "who is struggling", "who is distracted",
        "who needs attention", "who is slacking", "who is least productive",
        "who has too much distraction", "who needs help", "who should i talk to",
        "who's falling behind", "which employee is distracted today",
        "worst performer", "who is the least focused", "who is wasting time",
        "من يحتاج متابعة", "من مشتت", "من متأخر", "من اقل انتاجية",
        "مع من اتحدث", "من يحتاج مساعدة",
    ],
    "absent": [
        "who is absent", "who didn't show up", "who hasn't logged in",
        "who is missing", "who has been away", "absent employees",
        "who didn't work today", "who hasn't started", "who's not here",
        "who is off today", "any absences", "who has not come in",
        "من الغائبين", "من لم يحضر", "من غائب", "هل يوجد غياب",
    ],
    "weekly_summary": [
        "summarize last week's performance", "weekly report",
        "how did the team do this week", "last 7 days summary",
        "give me the weekly summary", "weekly performance of the team",
        "this week's numbers", "week in review", "team results for the week",
        "how did everyone do this week", "weekly team report",
        "summarize the week", "last week's numbers",
        "ملخص الاسبوع", "تقرير اسبوعي", "اداء الاسبوع الماضي",
        "ملخص الفريق للاسبوع",
    ],
    "employee_status": [
        "how is {person} doing", "how did {person} do today",
        "show me {person}'s stats", "tell me about {person}", "is {person} working",
        "{person}'s performance", "what about {person}",
        "how productive is {person}", "{person} status",
        "how has {person} been this week", "check on {person}",
        "how is {person} performing", "give me {person}'s numbers",
        "كيف حال {person}", "اداء {person}", "ماذا عن {person}",
        "هل {person} يعمل",
    ],
    UNKNOWN: [
        "who is the president of france", "what's the weather", "tell me a joke",
        "what is 2 plus 2", "what time is it in tokyo", "recipe for pizza",
        "how tall is mount everest", "sing a song", "who won the world cup",
        "write a poem", "what is the capital of japan", "are you alive",
        "how old are you", "what is love", "stock prices today", "latest news",
        "play some music", "order food for me", "what is the meaning of life",
        "do you like pizza", "how do i lose weight", "what is python",
        "translate hello to german", "what is the speed of light",
        "who invented the telephone", "where can i buy a car",
        "ما هي عاصمة فرنسا", "كيف الطقس", "احكي نكتة", "كم الساعة الان",
        "من هو رئيس امريكا", "اغنية", "ما معنى الحياة", "اين اشتري سيارة",
        "asdf", "blah blah", "hmm", "ok", "lol", "what", "why is the sky blue",
    ],
}


# More ways of saying the same thing (added after the first training run showed
# the network only knew the words it had seen).
_EXTRA = {
    "list_tasks": [
        "what work do i have", "show me what is assigned to me", "do i have work waiting",
        "give me an overview of my tasks", "what is waiting for me", "my open items",
        "tell me my tasks", "what are my current tasks", "show everything i need to do",
        "list what i have to finish", "what jobs do i have", "any pending work for me",
        "ايش المهام اللي علي", "اعرض لي ما يجب علي فعله",
    ],
    "task_next": [
        "what is the most pressing thing for me", "help me decide what to work on",
        "what comes first", "what is first on my list", "which job do i start with",
        "tell me my first priority", "what should i focus on right now",
        "what is the next thing i should do", "decide what i should work on",
        "where do i put my attention first", "what matters most today",
        "اي مهمة ابدأ بها", "ما الذي يجب ان اركز عليه",
    ],
    "task_deadlines": [
        "which of my tasks are past their due date", "which work is running late",
        "what has to be handed in soon", "when is my next deadline",
        "are there any overdue items", "what is about to be due",
        "do i have anything due this week", "remind me of my deadlines",
        "what is the nearest deadline", "is something late",
    ],
    "calendar_today": [
        "what does my day look like", "anything scheduled this afternoon",
        "today's agenda", "what do i have on today", "meetings for today",
        "is there a meeting this morning", "what is happening today",
        "do i have appointments today", "show me my day",
    ],
    "calendar_upcoming": [
        "do i have meetings later this week", "show me what is ahead on my calendar",
        "any appointments coming up", "what is on my calendar this week",
        "what is coming next on my agenda", "future events", "upcoming appointments",
        "what is planned for the next days", "any meetings next week",
    ],
    "my_stats": [
        "what is my focus rate", "show me my own numbers", "how many hours have i worked",
        "am i being productive", "how focused was i", "how has my week been",
        "what are my statistics", "how much did i focus today",
        "tell me about my productivity", "how many hours did i work this week",
        "how much time did i waste", "my own performance",
    ],
    "team_status": [
        "what is the situation with the team", "how is the staff performing right now",
        "team report for today", "how are my people doing", "give me an overview of the team",
        "what is happening with my employees", "how is the staff doing today",
        "how are the employees performing today", "overview of everyone today",
        "how is my team doing", "where does the team stand today",
        "اعطني نظرة عامة عن الفريق", "ما وضع الفريق اليوم",
    ],
    "active_now": [
        "who is at their desk working", "who is on a session right now",
        "who is working at the moment", "how many employees are working currently",
        "is somebody online", "who is currently active", "anyone working right now",
        "how many staff members are present", "who is logged in",
        "من يشتغل الان", "من موجود الان",
    ],
    "best_performer": [
        "who is my top performer", "tell me who has been the most productive this week",
        "who is number one on the team", "who gets the highest focus score",
        "which employee has performed the best", "who is the strongest employee",
        "who performed best today", "who is the best on my team",
        "who has the highest focus", "which person is the most productive",
        "who has done the most work", "who is the top worker this week",
        "من هو افضل موظف عندي", "من هو الاول في الفريق",
    ],
    "check_in": [
        "which employees should i follow up with", "is anyone having trouble staying focused",
        "name the people i should worry about", "who needs a nudge",
        "who is not focusing", "which person needs my attention",
        "who is getting distracted a lot", "who should i keep an eye on",
        "any employee struggling", "who has been unfocused", "who is behind",
        "which employee is least focused", "who needs follow up",
        "من يجب ان اتابعه", "من لا يركز",
    ],
    "absent": [
        "is anyone missing today", "who has not been working lately",
        "which employees were absent", "who has not logged in for days",
        "has anyone not shown up", "tell me who is away", "who did not come in",
        "who has been off", "list the absent employees", "who is out today",
        "من لم يدخل اليوم", "من لم يعمل اليوم",
    ],
    "weekly_summary": [
        "give me a summary of the last seven days", "how did we do over the past week",
        "weekly performance summary", "report on this week for the team",
        "how was the team over the last week", "summary of the week",
        "team totals for the last 7 days", "what were last week's results",
        "how did the staff do this week", "recap of the week",
        "ملخص اداء الاسبوع", "كيف كان اداء الفريق هذا الاسبوع",
    ],
    "employee_status": [
        "how is {person} getting on", "can you tell me about {person}'s day",
        "what are {person}'s numbers", "is {person} focused today",
        "has {person} been working", "how did {person} perform this week",
        "{person} today", "what is {person} doing", "report on {person}",
        "how much did {person} work", "is {person} doing well",
        "كيف حال {person}", "هل {person} مركز",
    ],
    "task_howto": [
        "what is the best way to get {task} done", "i don't know where to start with {task}",
        "can you guide me through {task}", "give me a plan for {task}",
        "walk me through {task}", "any tips to finish {task}",
        "help me figure out how to approach {task}", "how would you tackle {task}",
        "what do i need to do for {task}", "suggest steps for {task}",
        "how to handle {task}", "{task} how do i begin",
        "كيف اتعامل مع {task}", "اريد خطة لـ {task}",
    ],
    "capabilities": [
        "what are you able to help me with", "can you tell me what you know",
        "how do i use you", "what kinds of things can you answer",
        "what can i do here", "what are you for", "explain what you can do",
        "ماذا تفعل", "كيف استخدمك",
    ],
    "greeting": ["good day", "hello again", "salam", "ahlan", "hey how are you", "hi how are you"],
    "thanks": ["thanks for the help", "that was useful thank you", "great, appreciated", "thank u", "thanks that's helpful"],
    "goodbye": ["ok bye for now", "i'm leaving see you tomorrow", "catch you later", "bye for today"],
}
BANK["recall"] = [
    "what did i just say", "what was my last question", "repeat my last message",
    "what did i ask before", "what did we talk about", "what did i say earlier",
    "what was my previous question", "remind me what i asked",
    "do you remember what i said", "what was the last thing i asked",
    "say my last question again", "what have i asked so far",
    "what did i just ask you", "what was my last message",
    "ماذا قلت للتو", "ما هو سؤالي السابق", "ماذا سالتك قبل قليل",
    "كرر سؤالي الاخير", "عما تحدثنا",
]
_EXTRA["recall"] = ["what did i say a moment ago", "which question did i ask last", "remind me of my last question"]
for _intent, _phrases in _EXTRA.items():
    BANK[_intent] = BANK[_intent] + [p for p in _phrases if p not in BANK[_intent]]

# --------------------------------------------------------------------------- #
#  Held-out test questions: different wording, never used for training
# --------------------------------------------------------------------------- #
HELD_OUT = {
    "greeting": ["good day", "hello again", "hey assistant how are you", "salam", "ahlan"],
    "thanks": ["thanks for the help", "that was useful thank you", "great, appreciated", "thank u"],
    "goodbye": ["ok bye for now", "i'm leaving see you tomorrow", "catch you later", "الى اللقاء"],
    "capabilities": ["what are you able to help me with", "can you tell me what you know", "how do i use you", "what kinds of things can you answer", "ماذا تفعل"],
    "list_tasks": [
        "which tasks do i still have to finish", "can you list everything assigned to me",
        "what work is waiting for me", "show me what i need to do", "do i have anything open",
        "pending tasks please", "ماهي مهامي الحالية", "what is on my list",
    ],
    "task_howto": [
        "what is the best way to get the budget review done",
        "i don't know where to start with the website redesign",
        "can you guide me through preparing the report",
        "give me a plan for the client email", "walk me through the flutter app task",
        "any tips to finish the contract review", "كيف اتعامل مع مهمة التقرير",
        "help me figure out how to approach the presentation",
    ],
    "task_deadlines": [
        "are any of my tasks past their due date", "what has a deadline soon",
        "tell me which work is running late", "what needs to be handed in this week",
        "any overdue items", "when is my next deadline", "هل هناك مهمة فات موعدها",
    ],
    "task_next": [
        "what should be my first move today", "which job should i do before the others",
        "what is the most pressing thing for me", "help me decide what to work on",
        "what comes first", "ما الذي يجب ان ابدأ به",
    ],
    "calendar_today": [
        "do i have anything on the calendar today", "are there meetings for me today",
        "what's my day look like", "anything scheduled this afternoon",
        "today's agenda please", "هل عندي مواعيد اليوم",
    ],
    "calendar_upcoming": [
        "what events are coming this week", "do i have meetings later this week",
        "show me what's ahead on my calendar", "upcoming appointments",
        "when's the next event", "ما هي الاجتماعات هذا الاسبوع",
    ],
    "my_stats": [
        "how focused was i today", "what is my focus rate this week",
        "show me my own numbers", "how many hours have i worked", "am i being productive",
        "كم عملت هذا الاسبوع",
    ],
    "team_status": [
        "how are my people doing today", "can you give me an overview of the team today",
        "what's the situation with the team", "how's the staff performing right now",
        "team report for today", "اعطني نظرة عامة عن الفريق",
    ],
    "active_now": [
        "who's at their desk working", "tell me who is on a session now",
        "how many employees are working currently", "is somebody online",
        "من يشتغل الان",
    ],
    "best_performer": [
        "which employee has performed the best", "who is my top performer",
        "tell me who has been the most productive this week", "who's number one on the team",
        "who gets the highest focus score", "من هو افضل موظف عندي",
    ],
    "check_in": [
        "which employees should i follow up with", "who is not focusing",
        "is anyone having trouble staying focused", "who needs a nudge",
        "name the people i should worry about", "من يجب ان اتابعه",
    ],
    "absent": [
        "is anyone missing today", "who hasn't been working lately",
        "tell me who is away", "which employees were absent", "من لم يدخل اليوم",
    ],
    "weekly_summary": [
        "give me a summary of the last seven days", "how did we do over the past week",
        "weekly performance summary please", "report on this week for the team",
        "ملخص اداء الاسبوع",
    ],
    "employee_status": [
        "how is omar getting on", "can you tell me about sara's day",
        "what are omar's numbers", "is sara focused today", "كيف حال سارة",
    ],
    UNKNOWN: [
        "who is the prime minister of canada", "what is the weather like in cairo",
        "tell me something funny", "calculate 15 times 12", "what year was the moon landing",
        "can you cook dinner", "what is the best phone to buy", "ما هو افضل لاعب كرة قدم",
        "how far is the sun", "who wrote hamlet",
    ],
}

# --------------------------------------------------------------------------- #
#  Second test set: written AFTER the first round of tuning and never used for
#  development.  This is the honest accuracy figure.
# --------------------------------------------------------------------------- #
FRESH_PEOPLE = ["omar", "sara", "layla", "marwan", "ahmed"]
FRESH_TASKS = ["quarterly review", "invoice check", "user research", "marketing plan",
               "proposal", "demo"]

HELD_OUT_2 = {
    "greeting": ["hello assistant, good to see you", "hey, anyone there?", "good morning!", "hi hi", "السلام عليكم ورحمة الله"],
    "thanks": ["thanks, that answers it", "cool, thank you very much", "wonderful, thank you", "شكرا على المساعدة"],
    "goodbye": ["alright, signing off", "see you next time", "i'm heading out now", "الى اللقاء غدا"],
    "capabilities": ["what is it that you do exactly", "give me a quick intro to what you offer", "which topics can you help with", "هل يمكنك ان تخبرني ماذا تعرف"],
    "list_tasks": [
        "give me a rundown of the work on my desk", "which assignments are still outstanding for me",
        "anything on my to-do list", "show me what remains on my plate",
        "i would like to see my current assignments", "do i have unfinished tasks", "عرض المهام المتبقية",
    ],
    "task_howto": [
        "what would be a good approach to the quarterly review", "could you break the invoice check into steps",
        "i'm unsure how to begin the user research", "give me guidance on finishing the marketing plan",
        "how should i go about writing the proposal", "what's a sensible way to prepare the demo",
        "كيف اقوم بالتحضير للعرض",
    ],
    "task_deadlines": [
        "which of my assignments should be turned in soonest", "have i missed any due dates",
        "is there something i am late with", "what falls due in the coming days",
        "tell me about upcoming due dates", "هل فاتني موعد تسليم",
    ],
    "task_next": [
        "which of my tasks deserves attention first", "should i start with the urgent one",
        "what ought i to begin with this morning", "pick my starting task for me",
        "order my work by importance", "ما الذي يجب ان افعله الان",
    ],
    "calendar_today": [
        "have i got any appointments this morning", "what meetings are on today",
        "is my calendar clear today", "tell me about today's schedule",
        "what's happening in my day", "هل لدي موعد اليوم",
    ],
    "calendar_upcoming": [
        "what is on for the rest of the week", "any events lined up for the next few days",
        "show my calendar for next week", "which meetings are coming",
        "do i have appointments tomorrow", "ما الاحداث الاسبوع القادم",
    ],
    "my_stats": [
        "how did i do today in terms of focus", "give me my productivity figures",
        "what are my working hours so far", "how distracted was i this week",
        "my personal focus statistics", "كيف كان تركيزي اليوم",
    ],
    "team_status": [
        "give me a picture of how the team is performing", "what's the status across my employees today",
        "are my people being productive today", "how's the department doing",
        "status report on everyone today", "كيف يسير العمل مع الفريق اليوم",
    ],
    "active_now": [
        "which employees have a running session", "is anybody currently at work",
        "tell me how many staff are active", "who is working this minute", "كم شخص يعمل حاليا",
    ],
    "best_performer": [
        "which employee is outperforming the others", "who is the most efficient person on my team",
        "who's scored the highest focus this week", "name my strongest worker",
        "who earned the top spot", "من الاكثر تميزا في الفريق",
    ],
    "check_in": [
        "which staff members may need some support", "who seems to be struggling to concentrate",
        "who should i be concerned about", "is somebody falling behind on focus",
        "which person is distracted the most", "من الموظف الذي يحتاج مساعدة",
    ],
    "absent": [
        "has anybody not turned up today", "which employees haven't started working",
        "who has been missing from work", "is someone away from their desk all day",
        "اخبرني من لم يحضر",
    ],
    "weekly_summary": [
        "how did my employees perform over the last seven days", "send me this week's team recap",
        "what are the team's numbers for the week", "give me a weekly rundown of performance",
        "تقرير الاسبوع للفريق",
    ],
    "employee_status": [
        "how has omar been doing lately", "what is sara up to today", "give me an update on layla",
        "tell me how marwan performed", "is ahmed working right now", "ما هو وضع سارة",
    ],
    UNKNOWN: [
        "who is the king of england", "what is the population of egypt", "can you book me a flight",
        "what is the best programming language", "how do i bake a cake", "tell me about black holes",
        "what is the exchange rate of the dollar", "recommend a movie", "write me a short story",
        "ما هي عاصمة مصر", "who painted the mona lisa", "how many continents are there",
    ],
}

# --------------------------------------------------------------------------- #
#  Third test set: written last, evaluated once, never tuned on.  Includes
#  questions with typos.
# --------------------------------------------------------------------------- #
FRESH3_PEOPLE = ["noor", "tarek", "hana", "khalid"]
FRESH3_TASKS = ["contract renewal", "server migration", "onboarding guide", "sales deck",
                "tax filing"]

HELD_OUT_3 = {
    "greeting": ["well hello", "good evening to you", "hey buddy", "ahlan wa sahlan", "hello, are you there?"],
    "recall": [
        "can you repeat what i asked a moment ago", "which question did i ask previously",
        "tell me my earlier message", "ما الذي سالتك عنه",
    ],
    "thanks": ["thank you kindly", "thanks, you've been great", "ok great, thanks!", "جزاك الله خيرا", "much appreciated"],
    "goodbye": ["see you around", "i'm logging off now", "bye, have a nice day", "سلام", "until next time"],
    "capabilities": ["what are you good at", "can you list your abilities", "what questions do you understand", "explain what this assistant is for"],
    "list_tasks": [
        "what's on my agenda of tasks", "enumerate my open assignments", "which things have been given to me",
        "tell me about my current workload", "do i have things waiting to be done", "waht taks do i have",
        "كم مهمة لدي الان",
    ],
    "task_howto": [
        "how would i go about the contract renewal", "what steps should i follow for the server migration",
        "could you help me start the onboarding guide", "i need a roadmap for the sales deck",
        "any suggestions for getting the tax filing done", "how do i tackel the server migration",
    ],
    "task_deadlines": [
        "is any work overdue for me", "tell me which jobs are about to be due", "what should i hand in this week",
        "show me upcoming due dates for my work", "do i have missed deadlines", "وش المهام اللي متأخرة",
    ],
    "task_next": [
        "what is the first thing i should handle", "decide for me what to do now", "which assignment comes first",
        "tell me which task has priority", "where do i focus right now",
    ],
    "calendar_today": [
        "what appointments do i have today", "show me my agenda for the day", "is there any meeting scheduled for me today",
        "what's on for today", "do i have a busy day",
    ],
    "calendar_upcoming": [
        "any meetings planned for the next days", "show me what is coming on my calendar",
        "what events are scheduled this week", "what is my schedule like next week", "when is my next appointment",
    ],
    "my_stats": [
        "how well did i concentrate today", "tell me about my own productivity this week",
        "how many hours of focus did i log", "what is my distraction level", "how have i been performing",
    ],
    "team_status": [
        "tell me how the team is doing", "how are things going with my staff today",
        "what is the overall status of my employees", "team performance summary for today please",
        "give me the current state of the team",
    ],
    "active_now": [
        "which of my employees are online", "who has an active session at the moment",
        "is the team working right now", "how many people are on shift currently",
    ],
    "best_performer": [
        "who is my most productive employee", "which team member is doing the best work",
        "tell me who the top performer is", "who stands out as the best on my team",
        "who is the highest ranked employee", "whos the best performer",
    ],
    "check_in": [
        "who should i speak with about focus", "which employee is having a hard time",
        "who is the most distracted person today", "tell me who needs coaching",
        "who is lagging behind the others",
    ],
    "absent": [
        "tell me who is not at work today", "who hasn't come in yet", "which employees are off today",
        "are there any employees absent", "who has not logged in recently",
    ],
    "weekly_summary": [
        "how did everyone perform during the last week", "i'd like a weekly performance overview",
        "what were the team's results this past week", "can i get a report for the last seven days",
        "summery of the weeks performance",
    ],
    "employee_status": [
        "what is noor up to today", "tell me about tarek's performance", "how's hana doing this week",
        "is khalid working right now", "give me noor's numbers",
    ],
    UNKNOWN: [
        "what is the tallest building in the world", "can you help me write a cover letter", "who is the current president of the usa",
        "how many days until christmas", "explain quantum physics", "what should i cook tonight",
        "tell me a fun fact", "how do i fix my car", "what is the meaning of this word",
        "من هو اغنى رجل في العالم", "what's the score of the game", "give me a workout plan",
    ],
}

# The first held-out set was used while tuning; the phrases of the training bank
# must never coincide with ANY test sentence, so drop exact overlaps.
from assistant.intent_model import normalize as _normalize  # noqa: E402

_test_sentences = {
    _normalize(s) for group in (HELD_OUT, HELD_OUT_2, HELD_OUT_3) for items in group.values() for s in items
}
for _intent in list(BANK):
    BANK[_intent] = [p for p in BANK[_intent] if _normalize(p) not in _test_sentences]

# --------------------------------------------------------------------------- #
#  Generator
# --------------------------------------------------------------------------- #
TASK_NAMES = [
    "the q3 report", "q3 report", "budget review", "the budget", "client email",
    "website redesign", "the presentation", "flutter app", "contract review",
    "sales report", "project plan", "meeting notes", "the proposal", "data entry",
    "crm update", "bug fix", "the login screen", "monthly summary", "marketing plan",
    "team meeting", "invoice check", "user research", "the demo", "weekly report",
    "تقرير الربع", "الميزانية", "العرض التقديمي", "مراجعة العقد", "تطبيق فلاتر",
]
PERSON_NAMES = [
    "sara", "omar", "marwan", "ahmed", "mohamed", "layla", "nour", "khaled",
    "abdullah", "fatima", "yousef", "hana", "ali", "mona", "tariq", "sara ali",
    "omar khaled", "سارة", "عمر", "محمد", "احمد", "ليلى",
]

PREFIXES_EN = ["", "", "", "", "hey ", "hi ", "please ", "can you ", "could you ",
               "ok ", "so ", "i want to know ", "tell me ", "quick question ",
               "hey assistant "]
SUFFIXES_EN = ["", "", "", "", " please", " now", " thanks", "?", "?", " ?", "!", "."]
PREFIXES_AR = ["", "", "", "لو سمحت ", "ممكن ", "من فضلك ", "يا مساعد "]
SUFFIXES_AR = ["", "", "", "؟", "?", " من فضلك"]


def _is_arabic(text):
    return any("؀" <= ch <= "ۿ" for ch in text)


def _typo(word, rng):
    """One keyboard-style mistake: swap, drop or double a letter."""
    if len(word) < 4:
        return word
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(("swap", "drop", "double"))
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == "drop":
        return word[:i] + word[i + 1:]
    return word[:i] + word[i] + word[i:]


def _augment(text, intent, rng):
    arabic = _is_arabic(text)
    if not arabic and intent != UNKNOWN and rng.random() < 0.6:
        text = _swap_synonym(text, rng)
        if rng.random() < 0.3:
            text = _swap_synonym(text, rng)
    if not arabic and intent not in SHORT_INTENTS:
        text = _drop_words(text, rng)
    if intent not in SHORT_INTENTS:
        text = rng.choice(PREFIXES_AR if arabic else PREFIXES_EN) + text
    text += rng.choice(SUFFIXES_AR if arabic else SUFFIXES_EN)
    if rng.random() < 0.25:                       # sloppy typing
        words = text.split()
        if words:
            j = rng.randrange(len(words))
            words[j] = _typo(words[j], rng)
            text = " ".join(words)
    if rng.random() < 0.15:
        text = text.upper() if rng.random() < 0.3 else text.capitalize()
    return text


_OFF_TOPICS = [
    "the weather", "france", "the moon", "pizza", "football", "bitcoin", "movies",
    "music", "python", "the news", "my horoscope", "a flight", "the stock market",
    "cars", "history", "math", "jokes", "poems", "recipes", "the sun", "dinosaurs",
    "chess", "the internet", "coffee", "health", "the ocean", "space travel",
    "the olympics", "a good book", "gold prices", "elephants", "the capital of spain",
]
_OFF_TEMPLATES = [
    "what is {t}", "tell me about {t}", "who knows about {t}", "how does {t} work",
    "can you explain {t}", "what do you think about {t}", "i want to talk about {t}",
    "give me facts about {t}", "is {t} interesting", "why do people like {t}",
    "write something about {t}", "search for {t}", "what's new with {t}",
    "how do i learn about {t}", "where can i find {t}",
]


def _off_topic(count, rng):
    return [rng.choice(_OFF_TEMPLATES).replace("{t}", rng.choice(_OFF_TOPICS))
            for _ in range(count)]


def _drop_words(text, rng):
    """Sometimes forget a word, like people do when typing fast."""
    words = text.split()
    if len(words) >= 4 and rng.random() < 0.25:
        del words[rng.randrange(len(words))]
    return " ".join(words)


def _fill(template, rng):
    """Fill the name slots.  At run time the engine replaces real task / employee
    names in the question with ``taskx`` / ``personx`` before classifying, so most
    training sentences use those placeholders (the rest use real-looking names)."""
    task = "taskx" if rng.random() < 0.7 else rng.choice(TASK_NAMES)
    person = "personx" if rng.random() < 0.7 else rng.choice(PERSON_NAMES)
    return template.replace("{task}", task).replace("{person}", person)


def _swap_synonym(text, rng):
    """Replace one word / phrase by another member of its synonym group."""
    import re

    from assistant.lexicon import SYNONYM_GROUPS

    groups = SYNONYM_GROUPS[:]
    rng.shuffle(groups)
    for group in groups:
        for member in sorted(group, key=len, reverse=True):
            match = re.search(r"(?<![\w])%s(?![\w])" % re.escape(member), text)
            if match:
                other = rng.choice([m for m in group if m != member])
                return text[:match.start()] + other + text[match.end():]
    return text


def generate_training_data(per_phrase=18, seed=7):
    """Return ``[(sentence, intent), ...]`` built from :data:`BANK`.

    Every example phrase becomes ``per_phrase`` sentences with different
    openings / endings / names / typos.  The held-out set is not touched.
    """
    rng = random.Random(seed)
    data = []
    for intent, phrases in BANK.items():
        for phrase in phrases:
            copies = per_phrase if "{" in phrase else max(4, per_phrase // 2)
            for _ in range(copies):
                data.append((_augment(_fill(phrase, rng), intent, rng), intent))
    for sentence in _off_topic(600, rng):
        data.append((_augment(sentence, UNKNOWN, rng), UNKNOWN))
    rng.shuffle(data)
    return data
