"""Basic mode: simple rules and regexes that produce the same shapes as the AI when the AI is unavailable."""
import re
from datetime import date, timedelta

from app.ai.schemas import BriefOut, LinkPick, LinksOut, NudgesOut, NudgeText, RecapItemOut, RecapOut

_BULLET = re.compile(r"^\s*(?:[-*•>]+|\d+[.)])\s*")
_DECISION = re.compile(r"\b(decided|agreed|decision|approved|we will go with|we'll go with|confirmed|final call)\b", re.I)
_RISK = re.compile(r"\b(risk|blocker|blocked|concern|delay|delayed|worried|depends on|dependency|issue)\b", re.I)
_ACTION_PREFIX = re.compile(r"^(?:action(?: item)?|todo|to-do|ai|task|next step)\s*[:\-]\s*", re.I)
_ACTION_VERB = re.compile(r"\b(will|needs? to|should|must|to do|can you|please|owns?|take care of|follow up)\b", re.I)
_MENTION = re.compile(r"@([A-Z][a-z]+)")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_HIGH = re.compile(r"\b(urgent|asap|critical|high priority|p0|p1|blocker)\b", re.I)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _lines(text: str) -> list[str]:
    parts: list[str] = []
    for raw in text.splitlines():
        line = _BULLET.sub("", raw).strip()
        if line:
            parts.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z@])", line) if s.strip())
    return parts


def _guess_due(line: str, today: date) -> date | None:
    if m := _ISO_DATE.search(line):
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    low = line.lower()
    if "tomorrow" in low:
        return today + timedelta(days=1)
    if "next week" in low:
        return today + timedelta(days=7)
    if re.search(r"\b(eod|today|end of day)\b", low):
        return today
    for i, day in enumerate(_WEEKDAYS):
        if re.search(rf"\b{day}\b", low):
            return today + timedelta(days=(i - today.weekday()) % 7 or 7)
    return None


def _guess_owner(line: str, people: list[str]) -> str:
    if m := _MENTION.search(line):
        for person in people:
            if person.split()[0].lower() == m.group(1).lower():
                return person
        return m.group(1)
    for person in people:
        first = person.split()[0]
        if re.search(rf"\b{re.escape(first)}\b", line, re.I):
            return person
    return ""


def _clean_title(line: str, owner: str) -> str:
    title = _ACTION_PREFIX.sub("", line)
    if owner:
        first = re.escape(owner.split()[0])
        title = re.sub(rf"^@?{first}\w*\s*(?:[:\-,]|\bwill\b|\bto\b)?\s*", "", title, flags=re.I)
    title = title.rstrip(".").strip()
    return (title[:1].upper() + title[1:])[:300]


class FallbackHeuristicClient:
    """Rule-based stand-in for the AI. Output is lower quality but always valid."""

    mode = "basic"

    def recap(self, text: str, people: list[str], today: date) -> RecapOut:
        decisions, questions, risks, items = [], [], [], []
        for line in _lines(text):
            explicit = bool(_ACTION_PREFIX.match(line))
            owner = _guess_owner(line, people)
            if line.endswith("?") and not explicit:
                questions.append(line)
            elif _DECISION.search(line) and not explicit:
                decisions.append(line)
            elif explicit or (owner and _ACTION_VERB.search(line)):
                title = _clean_title(line, owner)
                if len(title) >= 3:
                    items.append(RecapItemOut(title=title, owner=owner, due_date=_guess_due(line, today),
                                              priority="high" if _HIGH.search(line) else "medium",
                                              confidence=0.6 if explicit else 0.4))
            if _RISK.search(line) and line not in risks:
                risks.append(line)
        sentences = _lines(text)[:3]
        summary = " ".join(sentences)[:600] or "No summary available."
        summary += f" (Basic mode found {len(decisions)} decisions and {len(items)} possible action items.)"
        return RecapOut(summary=summary, decisions=decisions, action_items=items,
                        open_questions=questions, risks=risks[:6])

    def brief(self, ctx: dict) -> BriefOut:
        person = ctx["person"]
        mine = ctx["your_items"]
        overdue = [f"{i['title']} ({i['days_overdue']} days overdue)" for i in mine if i["days_overdue"] > 0]
        do_first = []
        if overdue:
            do_first.append(f"Sort out the overdue item first: {overdue[0]}.")
        do_first += [f"Confirm you can own '{i['title']}' by {i['due_date'] or 'a date you agree'}."
                     for i in mine if i["days_overdue"] <= 0][:2]
        if not do_first:
            do_first.append("Read the decisions below and reply to the organiser with any questions.")
        why = "you missed this meeting" if ctx["attendance"] != "yes" else "you are picking up this work"
        summary = ctx["summary"] or f"{ctx['title']} covered: {ctx['agenda'] or 'see notes'}."
        return BriefOut(
            headline=f"{person.split()[0]}, here is what you need to know about '{ctx['title']}' ({why}).",
            what_happened=summary[:1200],
            decisions_affecting_you=ctx["decisions"][:6],
            your_items=[f"{i['title']} - {i['status']} - due {i['due_date'] or 'no date'}" for i in mine],
            overdue=overdue,
            do_first=do_first[:3],
        )

    def links(self, shortlist: list[dict], max_links: int) -> LinksOut:
        picks = [LinkPick(candidate_id=c["candidate_id"],
                          reason=f"Shares keywords: {', '.join(c['keywords'][:4]) or 'related topic'}")
                 for c in shortlist[:max_links]]
        return LinksOut(links=picks)

    def nudges(self, problems: list[dict]) -> NudgesOut:
        return NudgesOut(nudges=[NudgeText(key=p["key"], message=_template(p)) for p in problems])


def _template(p: dict) -> str:
    first = (p.get("recipient") or "team").split()[0]
    item = p.get("item_title", "")
    code = p["code"]
    if code == "overdue":
        extra = f" and has been carried over {p['carry_count']} times" if p.get("carry_count", 0) >= 2 else ""
        return (f"Hi {first}, '{item}' is {p['days_overdue']} days overdue{extra}. "
                "Can you confirm a new date or hand it off?")
    if code == "stale_carry":
        return (f"Hi {first}, '{item}' has been carried over {p['carry_count']} meetings in a row. "
                "Is it still needed, or should we drop or re-scope it?")
    if code == "no_owner":
        return f"Hi {first}, '{item}' has no owner yet. Could you assign someone before the next meeting?"
    if code == "no_due_date":
        return f"Hi {first}, '{item}' has no due date. Can you add a realistic date so it doesn't slip?"
    if code == "missed_no_brief":
        return (f"Hi {first}, we missed you at '{p['meeting_title']}'. A catch-up brief is ready in ContextRelay - "
                "could you read it and confirm your items?")
    if code == "bus_factor":
        return (f"Hi {first}, you currently own {p['share']}% of the open items here. "
                "Can we move one or two to someone else to reduce the load?")
    return f"Hi {first}, a quick follow-up on '{p.get('meeting_title', 'our meeting')}': {p.get('message', '')}"


fallback_client = FallbackHeuristicClient()
