"""Word groups ("concepts") that help the classifier cope with new wording.

A network trained on a few hundred example questions only knows the words it has
seen.  The lexicon lists the many ways people say the same thing -- "team",
"staff", "employees", "my people" are all ``TEAM``; "best", "top", "strongest" are
all ``BEST`` -- and the classifier gets one extra feature per concept found in the
question.  A word it never saw in training ("staff") therefore still lights up the
same concept as a word it did see ("team").

``SYNONYM_GROUPS`` is used the other way round, when the training data is
generated: a word in an example phrase is swapped for a random member of its
group, so the network sees far more wordings than were typed by hand.

Patterns are written in normal spelling (English and Arabic) and normalised with
the same function as the questions, so diacritics and letter variants match.
"""

import re

# concept -> alternatives (regex fragments, matched on whole words)
_CONCEPT_PATTERNS = {
    "TEAM": r"team|staff|employees?|everyone|everybody|people|colleagues?|workers?|personnel|crew|my people|الفريق|فريق|موظف|موظفين|الموظفين|الموظفون|الموظف",
    "SELF": r"my|mine|myself|i|me|am i|do i|have i|انا|اني|لي|عندي|مهامي|اداءي|احصائياتي",
    "BEST": r"best|top|strongest|leading|leader|star|number one|no\.? ?1|#1|most productive|most focused|highest|hardest|outstanding|excellent|recognition|deserves?|rank|افضل|الاكثر انتاجيه|الاكثر تركيزا|المثالي|ترتيب|الاول",
    "WORST": r"worst|least|weakest|struggling|slacking|behind|falling|lagging|distracted|distraction|unfocused|not focus\w*|wasting|worry|nudge|follow up|check in|check on|attention|needs? help|trouble|مشتت|متاخر|اقل|يحتاج متابعه|يحتاج مساعده|اتابعه|اتحدث",
    "ABSENT": r"absent|absences?|absence|missing|away|not here|didn'?t show|did not show|hasn'?t logged|not (?:come|come in|started)|off today|never logged|haven'?t (?:come|started)|غائب|الغائبين|غياب|لم يحضر|لم يدخل|لم يبدا",
    "ACTIVE": r"online|active|currently|right now|at the moment|present|on a session|at (?:their|his|her) desk|at work|working now|حاليا|الان|متصل|نشط|يعمل|يشتغل",
    "WEEK": r"week|weekly|last 7 days|seven days|past week|this week|last week|الاسبوع|اسبوعي|الاسبوعي|اسبوع",
    "TODAY": r"today|this morning|this afternoon|tonight|today's|اليوم",
    "TOMORROW": r"tomorrow|غدا",
    "TASK": r"tasks?|work|jobs?|assignments?|to do|todo|to-do|plate|list|مهمه|مهام|مهامي|شغل",
    "HOWTO": r"how|steps?|plan|guide|walk me through|tips?|approach|advice|advise|begin|start|where do i|stuck|break ?down|figure out|way to|كيف|خطوات|ابدا|ساعدني",
    "DEADLINE": r"due|deadlines?|overdue|late|past due|hand(?:ed)? in|running late|due date|موعد|المواعيد|تسليم|مستحق|متاخر|فات",
    "PRIORITY": r"first|priority|priorities|urgent|important|most pressing|focus on|prioriti[sz]e|next|start with|tackle|decide|اولا|اولويه|اولويات|اهم|بماذا",
    "CALENDAR": r"calendar|meetings?|events?|schedule[d]?|agenda|appointments?|planned|busy|جدول|اجتماع|اجتماعات|الاجتماعات|الاحداث|حدث|مواعيدي",
    "STATS": r"stats|statistics|numbers|performance|performing|productivity|productive|focus|focused|hours|worked|اداء|احصائيات|ركزت|عملت|انتاجيه",
    "SUMMARY": r"summary|summari[sz]e|report|overview|review|situation|ملخص|تقرير|نظره",
    "GREET": r"hi|hello|hey|morning|evening|afternoon|greetings|salam|ahlan|yo|hiya|anyone there|anybody there|good day|good to see you|مرحبا|اهلا|هلا|السلام|هاي|صباح|مساء",
    "THANKS": r"thanks?|thx|cheers|appreciate\w*|thank u|wonderful|helpful|useful|that helps|answers it|perfect|شكرا|مشكور|تسلم|يعطيك|ممتاز",
    "BYE": r"bye|goodbye|see you|later|good night|leaving|cya|catch you|signing off|sign off|heading out|head out|next time|call it a day|that'?ll be all|that is all|i'?m off|log off|مع السلامه|باي|اللقاء|تصبح|الى اللقاء",
    "CAPS": r"what can you|who are you|features|commands|what do you do|what are you|how do i use you|able to|your abilities|what you offer|topics can you|what you know|what is it that you do|intro|ماذا تستطيع|من انت|ماذا تفعل|ماذا يمكنك|ماذا تعرف",
    "RECALL": r"just said|just say|just ask\w*|last question|last message|previous (?:question|message)|asked (?:before|earlier|previously)|earlier message|remember|repeat|so far|what did i (?:say|ask)|moment ago|talked about|ماذا قلت|سؤالي|سالتك|تحدثنا|كرر|السابق",
    "WHO": r"who|which (?:employee|person|one|employees|people)|من",
}

_CONCEPTS = None


def concept_tags(normalised_text):
    """Concepts that occur in an already-normalised sentence, e.g. ``["TEAM", "BEST"]``."""
    global _CONCEPTS
    if _CONCEPTS is None:
        from assistant.intent_model import normalize

        _CONCEPTS = {
            name: re.compile(r"(?<!\w)(?:%s)(?!\w)" % normalize(pattern))
            for name, pattern in _CONCEPT_PATTERNS.items()
        }
    return [name for name, regex in _CONCEPTS.items() if regex.search(normalised_text)]


# Words that can replace each other when training sentences are generated.
SYNONYM_GROUPS = [
    ["team", "staff", "employees", "people", "everyone", "colleagues", "my people", "workers"],
    ["best", "top", "strongest", "leading", "number one", "most productive", "highest performing"],
    ["performer", "employee", "worker", "person", "member", "one"],
    ["tasks", "jobs", "assignments", "work items", "things to do"],
    ["task", "job", "assignment"],
    ["show", "list", "give me", "display", "tell me", "let me see"],
    ["doing", "performing", "getting on", "going", "managing"],
    ["today", "this morning", "right now", "at the moment"],
    ["week", "seven days", "7 days", "few days"],
    ["due", "scheduled", "expected", "coming up"],
    ["overdue", "late", "past due", "behind schedule"],
    ["meetings", "events", "appointments", "calls"],
    ["struggling", "falling behind", "not focused", "distracted", "slacking", "off track"],
    ["absent", "missing", "away", "not here", "off"],
    ["first", "next", "before the others", "right now"],
    ["important", "urgent", "pressing", "critical", "top priority"],
    ["start", "begin", "kick off", "get going"],
    ["finish", "complete", "get done", "wrap up", "do"],
    ["help", "assist", "guide", "advise", "support"],
    ["check in on", "follow up with", "talk to", "keep an eye on", "look into"],
    ["summary", "overview", "report", "rundown", "recap"],
    ["working", "active", "online", "on a session"],
    ["last question", "previous question", "earlier question", "last message", "previous message"],
    ["just say", "just asked", "said earlier", "asked before"],
    ["bye", "goodbye", "see you", "talk later", "signing off", "heading out", "catch you later", "i'm leaving"],
    ["thanks", "thank you", "thx", "much appreciated", "cheers", "thanks a lot"],
    ["hi", "hello", "hey", "good day", "greetings", "hey there"],
    ["what can you do", "what do you offer", "what are you able to do", "how can you help"],
    ["rundown", "overview", "list", "summary"],
    ["desk", "plate", "list", "queue"],
    ["assignments", "tasks", "work", "items"],
    ["soonest", "first", "earliest", "next"],
    ["turned in", "handed in", "due", "submitted"],
    ["worked", "focused", "been productive", "spent working"],
    ["productive", "focused", "efficient", "hard working"],
    ["numbers", "stats", "statistics", "figures", "results"],
]
