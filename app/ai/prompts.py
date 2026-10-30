"""Every prompt the app sends to the AI. Each one asks for JSON only, matching a schema in ai/schemas.py."""

JSON_RULES = (
    "Respond with a single JSON object only. No markdown, no code fences, no text before or after it. "
    "Use exactly the keys shown. Use only facts from the input; never invent people, dates or decisions."
)

RECAP_SYSTEM = f"""You turn messy meeting notes, chats, emails or transcripts into a structured recap for a team.
{JSON_RULES}
Shape:
{{"summary": "3-5 sentence plain-English summary",
  "decisions": ["each decision that was agreed"],
  "action_items": [{{"title": "verb-first task", "owner": "person name or empty string",
                    "due_date": "YYYY-MM-DD or null", "priority": "low|medium|high",
                    "confidence": 0.0-1.0}}],
  "open_questions": ["questions left unanswered"],
  "risks": ["risks, blockers or concerns raised"]}}
Resolve relative dates ("Friday", "next week") using today's date given in the input.
confidence = how sure you are that the item is a real, agreed task with that owner."""

RECAP_USER = """Today's date: {today}
Meeting: {title}
Known participants: {participants}

Raw text:
<<<
{text}
>>>"""

BRIEF_SYSTEM = f"""You write short, personal catch-up briefs for a teammate who missed a meeting or is taking over work.
Be concrete and kind. Mention dates and item titles. Max ~150 words in total.
{JSON_RULES}
Shape:
{{"headline": "one sentence for this person",
  "what_happened": "2-4 sentences",
  "decisions_affecting_you": ["..."],
  "your_items": ["item title - status - due date"],
  "overdue": ["overdue items they own or inherit"],
  "do_first": ["1-3 concrete next steps, most important first"]}}"""

BRIEF_USER = """Today's date: {today}
Write the brief for: {person}
Context (JSON):
{context}"""

LINK_SYSTEM = f"""You link a meeting to the most relevant knowledge-base documents and past meetings.
You get the meeting and a shortlist of candidates. Pick at most {{max_links}} that would genuinely help someone
understand or act on this meeting. Skip weak matches. Give a one-line reason for each.
{JSON_RULES}
Shape: {{"links": [{{"candidate_id": "doc:3 or meeting:2 (copy from the shortlist)", "reason": "one line"}}]}}"""

LINK_USER = """Meeting:
{meeting}

Candidates:
{candidates}"""

NUDGE_SYSTEM = f"""You write short, friendly, specific follow-up messages (nudges) that a team lead can paste into chat.
One nudge per input key. Address the person by first name. Name the exact item and the problem
(days overdue, times carried over, missing owner, missed meeting). End with one clear ask. Max 2 sentences.
{JSON_RULES}
Shape: {{"nudges": [{{"key": "copy the key from the input", "message": "..."}}]}}"""

NUDGE_USER = """Meeting: {title}
Problems to nudge about (JSON):
{problems}"""
