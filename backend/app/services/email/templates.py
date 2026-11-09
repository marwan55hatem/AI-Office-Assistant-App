"""E-mail templates: plain text and HTML, English and Arabic.

Every value that came from a user (titles, names) is HTML-escaped in the HTML part, and
the link is always the configured website address plus a fixed path.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, time

LANGUAGES = ("en", "ar")
TEMPLATES = ("task_urgent", "meeting_invite", "meeting_changed", "meeting_cancelled", "meeting_request_new",
             "meeting_request_accepted", "meeting_request_declined", "meeting_request_rescheduled",
             "meeting_request_cancelled", "test")
#: templates without an "Open" link (there is nothing left to open)
NO_LINK = ("meeting_cancelled", "meeting_request_cancelled")

_AR_DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
_AR_MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر",
              "نوفمبر", "ديسمبر")

TEXT = {
    "en": {
        "hello": "Hello {name},",
        "task_urgent.subject": "Urgent task: {title}",
        "task_urgent.lead": "{who} assigned you an urgent task.",
        "meeting_invite.subject": "New meeting: {title}",
        "meeting_invite.lead": "{who} invited you to a meeting.",
        "meeting_changed.subject": "Meeting changed: {title}",
        "meeting_changed.lead": "{who} changed a meeting you are invited to.",
        "meeting_cancelled.subject": "Meeting cancelled: {title}",
        "meeting_cancelled.lead": "{who} cancelled a meeting you were invited to.",
        "test.subject": "Office Assistant test e-mail",
        "test.lead": "This is a test e-mail from Office Assistant. If you can read it, e-mail is set up correctly.",
        "label.task": "Task", "label.meeting": "Meeting", "label.due": "Due", "label.when": "When",
        "label.who": "From",
        "label.topic": "Topic", "label.times": "Proposed times", "label.note": "Note", "label.reason": "Reason",
        "meeting_request_new.subject": "Meeting request: {title}",
        "meeting_request_new.lead": "{who} asked for a meeting with you.",
        "meeting_request_accepted.subject": "Meeting accepted: {title}",
        "meeting_request_accepted.lead": "{who} accepted the meeting. It is in your calendar.",
        "meeting_request_declined.subject": "Meeting request declined: {title}",
        "meeting_request_declined.lead": "{who} declined your meeting request.",
        "meeting_request_rescheduled.subject": "Other times proposed: {title}",
        "meeting_request_rescheduled.lead": "{who} proposed other times for your meeting request.",
        "meeting_request_cancelled.subject": "Meeting request cancelled: {title}",
        "meeting_request_cancelled.lead": "{who} cancelled the meeting request.",
        "no_deadline": "No deadline", "all_day": "All day",
        "open": "Open in Office Assistant",
        "app_hint": "You can also open the Office Assistant app on your computer.",
        "footer.optional": "You can turn off meeting e-mails in the app: Settings → Notifications.",
        "footer.urgent": "E-mails about urgent tasks are always sent.",
    },
    "ar": {
        "hello": "مرحباً {name}،",
        "task_urgent.subject": "مهمة عاجلة: {title}",
        "task_urgent.lead": "كلّفك {who} بمهمة عاجلة.",
        "meeting_invite.subject": "اجتماع جديد: {title}",
        "meeting_invite.lead": "دعاك {who} إلى اجتماع.",
        "meeting_changed.subject": "تم تعديل الاجتماع: {title}",
        "meeting_changed.lead": "عدّل {who} اجتماعاً أنت مدعو إليه.",
        "meeting_cancelled.subject": "تم إلغاء الاجتماع: {title}",
        "meeting_cancelled.lead": "ألغى {who} اجتماعاً كنت مدعواً إليه.",
        "test.subject": "رسالة تجريبية من Office Assistant",
        "test.lead": "هذه رسالة تجريبية من Office Assistant. إذا وصلتك فإعداد البريد يعمل بشكل صحيح.",
        "label.task": "المهمة", "label.meeting": "الاجتماع", "label.due": "موعد التسليم", "label.when": "الموعد",
        "label.who": "من",
        "label.topic": "الموضوع", "label.times": "المواعيد المقترحة", "label.note": "ملاحظة", "label.reason": "السبب",
        "meeting_request_new.subject": "طلب اجتماع: {title}",
        "meeting_request_new.lead": "طلب {who} اجتماعاً معك.",
        "meeting_request_accepted.subject": "تمت الموافقة على الاجتماع: {title}",
        "meeting_request_accepted.lead": "وافق {who} على الاجتماع، وأُضيف إلى تقويمك.",
        "meeting_request_declined.subject": "تم رفض طلب الاجتماع: {title}",
        "meeting_request_declined.lead": "رفض {who} طلب الاجتماع.",
        "meeting_request_rescheduled.subject": "مواعيد أخرى مقترحة: {title}",
        "meeting_request_rescheduled.lead": "اقترح {who} مواعيد أخرى لطلب الاجتماع.",
        "meeting_request_cancelled.subject": "تم إلغاء طلب الاجتماع: {title}",
        "meeting_request_cancelled.lead": "ألغى {who} طلب الاجتماع.",
        "no_deadline": "بدون موعد نهائي", "all_day": "طوال اليوم",
        "open": "افتح في Office Assistant",
        "app_hint": "يمكنك أيضاً فتح تطبيق Office Assistant على حاسوبك.",
        "footer.optional": "يمكنك إيقاف رسائل الاجتماعات من التطبيق: الإعدادات ← الإشعارات.",
        "footer.urgent": "تُرسل رسائل المهام العاجلة دائماً.",
    },
}

PATHS = {"task_urgent": "/tasks", "meeting_invite": "/calendar", "meeting_changed": "/calendar",
         "meeting_cancelled": "/calendar", "test": "", "meeting_request_new": "/meetings",
         "meeting_request_accepted": "/meetings", "meeting_request_declined": "/meetings",
         "meeting_request_rescheduled": "/meetings", "meeting_request_cancelled": "/meetings"}


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def format_day(day: date, language: str) -> str:
    if language == "ar":
        return f"{_AR_DAYS[day.weekday()]} {day.day} {_AR_MONTHS[day.month - 1]} {day.year}"
    return f"{day:%a} {day.day} {day:%b %Y}"


def format_when(day: str | None, start: str | None, end: str | None, language: str, empty_key: str) -> str:
    """``Mon 9 Nov 2026, 10:00–11:00``; times arrive as ISO strings from the payload."""
    t = TEXT[language]
    if not day:
        return t[empty_key]
    text = format_day(date.fromisoformat(day), language)
    if start:
        span = time.fromisoformat(start).strftime("%H:%M")
        if end:
            span += "–" + time.fromisoformat(end).strftime("%H:%M")
        return f"{text}، {span}" if language == "ar" else f"{text}, {span}"
    return f"{text} ({t['all_day']})" if empty_key == "all_day" else text


def format_moment(value: str, language: str) -> str:
    """An ISO date-time as the wall-clock time it was given in (the person's own time zone)."""
    moment = datetime.fromisoformat(value)
    clock = moment.strftime("%H:%M")
    day = format_day(moment.date(), language)
    return f"{day}، {clock}" if language == "ar" else f"{day}, {clock}"


def render(template: str, language: str, payload: dict, recipient_name: str, link_base: str) -> Rendered:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}")
    language = language if language in LANGUAGES else "en"
    t = TEXT[language]
    title = (payload.get("title") or "")[:200]
    who = (payload.get("who") or "")[:120]
    subject = t[f"{template}.subject"].format(title=title).replace("\n", " ")
    lead = t[f"{template}.lead"].format(who=who)
    rows = []
    if template == "task_urgent":
        rows = [(t["label.task"], title),
                (t["label.due"], format_when(payload.get("date"), payload.get("time"), None, language, "no_deadline"))]
    elif template.startswith("meeting_request_"):
        times = " · ".join(format_moment(v, language) for v in payload.get("times") or [])
        extra = {"meeting_request_new": [("label.times", times), ("label.note", payload.get("note"))],
                 "meeting_request_accepted": [("label.when", format_moment(payload["when"], language)
                                               if payload.get("when") else "")],
                 "meeting_request_declined": [("label.reason", payload.get("reason"))],
                 "meeting_request_rescheduled": [("label.times", times), ("label.note", payload.get("note"))],
                 "meeting_request_cancelled": [("label.reason", payload.get("reason"))]}[template]
        rows = [(t["label.topic"], title)] + [(t[key], str(value)[:1000]) for key, value in extra if value]
    elif template.startswith("meeting_"):
        rows = [(t["label.meeting"], title),
                (t["label.when"], format_when(payload.get("date"), payload.get("start"), payload.get("end"),
                                              language, "all_day")),
                (t["label.who"], who)]
    link = link_base.rstrip("/") + PATHS[template] if template not in NO_LINK else ""
    footer = t["footer.urgent"] if template == "task_urgent" else (t["footer.optional"] if template != "test" else "")

    lines = [t["hello"].format(name=recipient_name), "", lead, ""]
    lines += [f"{label}: {value}" for label, value in rows]
    if link:
        lines += ["", f"{t['open']}: {link}", t["app_hint"]]
    if footer:
        lines += ["", footer]
    text = "\n".join(lines).strip() + "\n"

    e = html.escape
    direction = "rtl" if language == "ar" else "ltr"
    align = "right" if language == "ar" else "left"
    gap = "padding:6px 0 6px 12px" if language == "ar" else "padding:6px 12px 6px 0"
    # values may be in another script than the e-mail (an English title in an Arabic e-mail):
    # dir="auto" keeps their punctuation and numbers in the right order
    table = "".join(
        f'<tr><td style="{gap};color:#6b7280;white-space:nowrap;vertical-align:top">{e(label)}</td>'
        f'<td style="padding:6px 0;color:#111827;font-weight:600"><span dir="auto">{e(value)}</span></td></tr>'
        for label, value in rows)
    details = f'<table style="border-collapse:collapse">{table}</table>' if rows else ""
    button = (f'<p style="margin:24px 0 8px"><a href="{e(link, quote=True)}" style="background:#1e40af;color:#ffffff;'
              f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">{e(t["open"])}</a></p>'
              f'<p style="margin:0;color:#6b7280;font-size:13px">{e(t["app_hint"])}</p>') if link else ""
    foot = (f'<p style="margin:28px 0 0;padding-top:16px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px">'
            f'{e(footer)}</p>') if footer else ""
    body = (f'<!DOCTYPE html><html lang="{language}" dir="{direction}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(subject)}</title></head>'
            f'<body style="margin:0;background:#f3f4f6;font-family:Segoe UI,Tahoma,Arial,sans-serif">'
            f'<div style="max-width:560px;margin:0 auto;padding:24px 16px">'
            f'<div style="background:#ffffff;border-radius:12px;padding:28px;text-align:{align}" dir="{direction}">'
            f'<p style="margin:0 0 4px;color:#1e40af;font-weight:700">Office Assistant</p>'
            f'<p style="margin:16px 0 8px;color:#111827">{e(t["hello"].format(name=recipient_name))}</p>'
            f'<p style="margin:0 0 16px;color:#111827">{e(lead)}</p>'
            f'{details}{button}{foot}</div></div></body></html>')
    return Rendered(subject=subject, text=text, html=body)
