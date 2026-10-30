# ContextRelay

## 1. What this app does

Teams lose context when work changes hands. Someone misses a meeting, someone goes on leave, or an action item never reaches the next agenda.

ContextRelay records what was discussed and decided. It passes that context to the right people. Then it keeps following up on open items until they are closed.

**Features**
- Meetings and work handovers, with a lifecycle (Draft → Scheduled → Completed → Archived)
- Action items with owner, due date, priority, a required outcome when closing, and a full history
- One-click **carry over** of open items to the next meeting (history is kept)
- **AI recap**: paste messy notes, get a summary, decisions and action items, then review them before saving
- **AI catch-up brief** for anyone who missed a meeting or is taking over
- **Knowledge base**, plus AI that links meetings to the right docs and past meetings
- **Handoff Health Score** (0-100) and a **Nudge Engine** that writes ready-to-send follow-ups
- **Risk Radar** dashboard for the whole workspace
- Works without AI too (a "basic mode" based on simple rules)

## 2. How to run it locally

You need **Python 3.10 or newer**. These commands are for Windows PowerShell. On Mac or Linux, see the notes after the list.

```powershell
# 1. Go to the project folder
cd Digi_Plus

# 2. Create a virtual environment (a private folder for this app's packages)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install the packages
pip install -r requirements-dev.txt

# 4. (Optional) Turn on real AI
copy .env.example .env
#    Open .env and set AI_API_KEY=your-key
#    Use AI_PROVIDER=anthropic or AI_PROVIDER=gemini.
#    Skip this step and the app runs in "basic mode".

# 5. Start the app
uvicorn app.main:app --reload
```

Now open **http://127.0.0.1:8000** in your browser.

The first start creates the database (`data/contextrelay.db`) and fills it with demo data, so there is something to look at straight away.

On Mac or Linux, use `source .venv/bin/activate` instead of step 2's activate line, and `cp` instead of `copy`.

**A 10-second tour:** open the dashboard and look at the Risk Radar. Then click the red **Handover: Priya → Sam** meeting. You will see its health score, the reasons behind it, and the buttons for nudges, briefs and links.

## 3. How I approached the problem

The real problem is not "taking notes". It is **context getting lost between people and between meetings**. So I asked three questions:

1. **Capture**: what was decided and who owns what? → meetings, decisions, action items, AI recap.
2. **Transfer**: does the person who was not there get the context? → catch-up briefs, knowledge links, carry-over.
3. **Follow up**: does anything slip through? → the history log, the health score, nudges, the Risk Radar.

Most tools stop at step 1. I spent the extra effort on steps 2 and 3, because that is where context is actually lost.

I also decided early that **the AI must never be a single point of failure**. Every AI feature has a rule-based backup, and the AI never saves anything without a human checking it first.

## 4. Architecture in simple words

The browser shows one web page. That page calls the API (a set of URLs that send back data). The API reads and writes the database. When it needs a summary or a message, it asks the AI. If the AI fails, it uses simple rules instead.

```
  Browser (index.html + app.js)
        |  fetch JSON
        v
  FastAPI routers  (app/routers)      <- checks input with Pydantic, adds a request ID
        |
        v
  Services         (app/services)     <- business rules: lifecycle, carry-over, health score
     |                     |
     v                     v
  SQLite database     AI runner (app/ai/runner.py)
  (app/models)          |-> Anthropic or Gemini   (real AI)
                        |-> if it fails twice: FallbackHeuristicClient (rules)
                        v
               validated JSON -> back to services -> back to the browser
```

Folders: `core/` (settings, logging, errors, DB), `models/` (tables), `schemas/` (input checks), `ai/` (prompts, providers, fallback), `services/` (logic), `routers/` (URLs), `static/` (UI).

## 5. Tech stack and why

| Piece | Why I picked it |
|---|---|
| **Python + FastAPI** | Quick to write. It checks input automatically and gives free API docs at `/docs`. |
| **SQLAlchemy + SQLite** | A real SQL database in one file. No server to install. Easy to switch to Postgres later. |
| **Pydantic v2** | Checks every request **and every AI answer** against a fixed shape. |
| **HTML + Tailwind (CDN) + plain JavaScript** | No build step. One page, easy to read, works anywhere. |
| **Anthropic / Gemini SDKs** | The official libraries, so timeouts and errors are handled properly. |
| **pytest** | A simple, standard tool for tests. |
| **Docker** | The same app runs the same way on any host (Render, Railway, Fly). |

## 6. AI configuration

The AI is set up only through environment variables (settings read when the app starts):

| Variable | Example | Meaning |
|---|---|---|
| `AI_PROVIDER` | `anthropic` / `gemini` / `none` | Which AI to use. `none` = basic mode. |
| `AI_MODEL` | `claude-opus-5-5` | Model name. If empty: `claude-opus-5-5` for Anthropic, `gemini-2.5-flash` for Gemini. |
| `AI_API_KEY` | `sk-ant-...` | Your secret key. Put it in `.env`, never in the code. |
| `AI_TIMEOUT_SECONDS` | `20` | How long to wait before giving up on one attempt. |

**How prompts work.** All prompts live in one file, `app/ai/prompts.py`. Each prompt tells the AI to answer with **JSON only** (structured data with fixed keys), and shows the exact shape.

**How bad answers are handled** (`app/ai/runner.py`):
1. Call the AI (20-second timeout).
2. Strip any extra text and parse the JSON.
3. Check it with a Pydantic model (`app/ai/schemas.py`). Small mistakes are fixed: a bad date becomes empty, "URGENT" becomes "medium", and confidence is kept between 0 and 1.
4. If the call failed, timed out or returned invalid JSON, **retry once**.
5. If it fails again, use the **FallbackHeuristicClient** (`app/ai/fallback.py`). It uses regex and rules to give the same shape of answer.
6. The UI shows a yellow banner: **"AI unavailable - basic mode"**.

**Basic mode** works with no key at all. It finds decisions ("agreed", "decided"), questions (lines ending in "?"), risks ("blocker", "delay"), and action items ("Action:", "@Name", "Sam will..."). It also writes briefs and nudges from templates.

**Safety rule:** an AI recap is only a *suggestion*. Each item has an "AI-suggested" badge and Accept / Reject buttons. Nothing is saved until you click **Save accepted items**.

## 7. Data source and database

All data is in a SQLite file (`data/contextrelay.db`). It is created automatically.

| Table | What it stores | Links to |
|---|---|---|
| `meetings` | Title, type (meeting/handover), status, agenda, notes, summary, decisions, risks | `previous_meeting_id` → the meeting before it |
| `participants` | Name, email, role, attended (yes / no / no_response) | `meeting_id` |
| `action_items` | Title, owner, due date, status, priority, outcome, carry_count | `meeting_id`, `origin_item_id` (first in chain), `parent_item_id`, `carried_to_id` |
| `item_events` | Every change: created, reassigned, status change, carried over, closed, nudged | `item_id`, `chain_id` |
| `meeting_events` | Created, status changed, recap accepted, brief generated... | `meeting_id` |
| `kb_docs` | Knowledge base docs: title, content, tags | — |
| `links` | Meeting → doc or meeting, with a one-line reason | `meeting_id`, `doc_id`, `target_meeting_id` |
| `briefs` | Cached catch-up briefs per person | `meeting_id` |
| `nudges` | Drafted follow-up messages and when they were sent | `meeting_id`, `item_id` |

Meetings and docs use **soft delete**: they are hidden, not erased.

**Seed data** (`app/services/seed.py`) is a payments-vendor migration project. Dates are relative to today, so "overdue" is always overdue.
- **3 linked meetings:** Kickoff → Weekly Sync #2 → Handover (Priya → Sam)
- **A missed meeting:** Daniel missed Sync #2, and Priya never replied
- **Someone on leave:** Priya, whose budget item is reassigned to Sam
- **An overdue item carried over twice:** "Finalise vendor contract with PayFlow"
- **10 action items** (13 rows including the carried copies) and **8 KB docs**
- A **Reset demo data** button (top right) brings all of this back

## 8. Logging

- **Where:** `logs/app.log` (it rotates at 2 MB and keeps 5 files) and the console.
- **Format:** one JSON object per line. This is a real line from the app:

```json
{"timestamp": "2026-10-30T06:19:01.638+00:00", "level": "INFO", "logger": "app.meetings", "message": "2 items carried 2 -> 4", "request_id": "8c433766-706b-4f19-9979-3c5a6eb565d6", "event": "items_carried_over", "from_meeting_id": 2, "to_meeting_id": 4, "count": 2, "item_ids": [14, 15]}
```

- **Request ID:** every request gets a UUID (a random unique ID). If the client sends an `X-Request-ID` header, the app uses that one instead. The ID goes on every log line for that request, in the `X-Request-ID` response header, and in every error body. When a user sees an error toast, it shows the ID, so you can find the matching logs.
- **Levels:** DEBUG (cache hits, raw AI output length), INFO (business events, requests), WARNING (validation errors, AI retries and fallbacks), ERROR (unexpected crashes, with exception type and route).
- **Business events:** `meeting_created`, `meeting_status_changed`, `item_created`, `item_reassigned`, `item_closed` (with outcome), `items_carried_over`, `brief_generated`, `recap_generated`, `links_suggested`, `nudges_generated`, `nudge_sent`.
- **AI calls:** `provider`, `model`, `purpose` (recap/brief/link/nudge), `attempt`, `latency_ms`, `outcome` (success/retry/error/fallback), `tokens_in`/`tokens_out`. **Prompts are never logged.** Only their length (`input_chars`) is.
- **Secrets:** keys come only from env vars. The log formatter removes the real key value, `sk-ant-...` and `AIza...` keys, `Bearer` tokens and `Authorization`/`api_key` values. `.gitignore` keeps `.env`, `logs/` and `data/` out of git.

## 9. My special feature: Handoff Health Score + Nudge Engine

Every meeting gets a score from **0 to 100** that shows how likely its context is to be lost. It starts at 100, and each problem takes points away. The rules are simple and visible, and every lost point comes with a plain-English reason.

| Rule | Penalty | Max |
|---|---|---|
| Open item with no owner | -10 each | 30 |
| Open item with no due date | -5 each | 20 |
| Overdue item | -10 each | 30 |
| Item carried over 2+ times (stale) | -8 each | 24 |
| Person missed it or never replied, and has no catch-up brief (completed meetings and handovers) | -8 each | 24 |
| Decisions recorded but no KB doc linked | -10 | 10 |
| Handover with no knowledge links at all | -15 | 15 |
| Bus factor: one person owns more than 60% of open items (with 3 or more owned) | -10 | 10 |

**Badge colours:** green 75-100, amber 50-74, red below 50. The rules are in `app/core/constants.py` and `app/services/health.py`.

**Nudge Engine:** click **Draft nudges**. Each problem that has a person attached becomes a short, ready-to-send message. For example:
> "Hi Riya, 'Finalise vendor contract with PayFlow' is 10 days overdue and has been carried over 2 times. Can you confirm a new date or hand it off?"

The AI writes these messages. If the AI is down, templates write them. Each nudge has **Copy** and **Mark nudge sent** buttons. Marking it sent saves a time and adds a `nudge_sent` event to the item's history.

**Risk Radar** (on the dashboard) ranks the worst meetings and the riskiest items across the whole workspace.

**Why it matters:** it moves the app from *recording* what happened to *preventing* context loss, which is the actual problem. Fixing a problem raises the score straight away. For example, generating Daniel's brief removes the "missed meeting" penalty.

## 10. How each requirement is met

| Requirement | Where |
|---|---|
| Meetings/handovers CRUD + soft delete | `routers/meetings.py`, `services/meetings.py` |
| Lifecycle with 409 on invalid moves | `core/constants.py` `MEETING_TRANSITIONS`, `services/meetings.change_status` |
| Action items, outcome required to close | `schemas/api.py` `ItemUpdate`, `services/items.py` |
| Full item history | `item_events` table, item history modal in the UI |
| Carry-forward keeping the ID chain | `services/meetings.carry_over`, "Carry over open items" button |
| AI recap with review/accept | `services/ai_features.generate_recap` / `accept_recap`, Recap panel |
| Catch-up brief, cached, regenerate | `services/ai_features.get_or_create_brief`, Participants card |
| KB CRUD + TF-IDF shortlist + AI picks links | `routers/workspace.py`, `services/retrieval.py`, `services/ai_features.suggest_links` |
| Remove wrong links | `DELETE /api/links/{id}`, "remove" button |
| Error shape `{error, detail, request_id}` | `core/errors.py` |
| AI timeout, 1 retry, fallback, banner | `ai/runner.py`, `ai/fallback.py`, yellow banner in `index.html` |
| Seed data + reset button | `services/seed.py`, `POST /api/demo/reset` |
| Health score, nudges, Risk Radar | `services/health.py`, dashboard + meeting page |
| JSON logs, request ID, redaction, rotation | `core/logging.py`, `core/middleware.py` |
| `/health`, Dockerfile, render.yaml, Procfile | `routers/workspace.py`, repo root |
| Tests | `tests/` (15 tests) |

## 11. Assumptions

- One team, one workspace, no login. "Viewing as" (top right) picks whose items show as "my items".
- People are matched by name. The same name means the same person.
- An item counts as overdue when its due date is before today and it is not Done or Dropped.
- Carry-over **copies** open items into the new meeting. The old copy is marked as "carried" and becomes read-only, so each piece of work has one live version.
- Nudges are copied and sent by a person, for example in Slack. The app does not send email.
- The "missed meeting" penalty only counts once a meeting is completed, or for handovers. Before a meeting happens, nobody has missed it yet.

## 12. Known limitations and what I would build next

- No user accounts or permissions. Next: sign-in, and a "me" that comes from the login.
- Nudges are not sent automatically. Next: Slack/email integration and scheduled reminders.
- Linking works at meeting level, using item titles in the search. Linking each item to its own docs would be the next step.
- TF-IDF is keyword based. Next: embeddings (meaning-based search) for better matches.
- SQLite is fine for a demo. On free hosting the file resets when the app restarts. Next: Postgres.
- The UI has been checked by loading the page and by `node --check`, not by automated browser tests. Next: Playwright tests.
- Basic-mode recap is rough. It is a safety net, not a replacement for the AI.

## 13. Deployment

**Render (Docker):**
1. Push this repo to GitHub.
2. On Render: **New → Blueprint** → pick the repo. `render.yaml` sets up everything.
3. In the service's **Environment** tab, set `AI_API_KEY` (and `AI_PROVIDER` / `AI_MODEL` if you want something different).
4. Deploy. Render checks `/health` to know the app is up.

**Any Docker host:**
```bash
docker build -t contextrelay .
docker run -p 8000:8000 -e AI_PROVIDER=anthropic -e AI_API_KEY=your-key contextrelay
```

**Railway / Heroku-style hosts** use the `Procfile`.

Live URL: `https://<your-app>.onrender.com` *(add it after deploying)*

## 14. How to run the tests

```powershell
.\.venv\Scripts\Activate.ps1
pytest
```

The tests use their own temporary database and never call a real AI. They cover:
- input checks and the error shape
- the request ID
- the meeting lifecycle
- the required outcome and item history
- soft delete
- carry-over and the item chain
- the health score maths
- briefs fixing the score
- nudges
- AI success, AI invalid JSON → retry → fallback, AI timeout → fallback
- secret redaction

---

## Explain it in an interview

**60-second pitch.**
"Teams lose context when work changes hands. ContextRelay captures what was decided, passes it on, and follows up until things are done. You paste messy notes, and the AI turns them into decisions and action items. You review them before anything is saved. People who missed the meeting get a personal catch-up brief. Open items carry over to the next meeting with their full history. The part I'm proudest of is the Handoff Health Score. Every meeting gets a 0-100 score from clear rules, like overdue items, missing owners, or someone who missed it and has no brief. The Nudge Engine then turns each problem into a ready-to-send message. So the app doesn't just record what happened. It actively prevents context from being lost. And if the AI is down, everything still works in a rule-based basic mode."

**1. Why this stack?**
FastAPI and Pydantic give fast development and automatic input checks. SQLite needs no setup. A no-build front end keeps the project small and easy to review. Everything fits in one Docker image.

**2. How does the AI fail safely?**
Every AI answer must pass a Pydantic schema. If the call fails, times out (after 20 seconds) or returns bad JSON, the app retries once. Then it switches to a rule-based fallback that gives the same shape of answer. The UI shows a "basic mode" banner. Recap suggestions are never saved without a human clicking Save.

**3. How does the score work?**
It starts at 100 and subtracts fixed penalties for eight risk rules. Each rule has a cap, so one problem can't hide all the others. Every penalty comes with a sentence explaining it, so the score is easy to understand and to argue with.

**4. How does carry-forward keep history?**
The open item is copied into the new meeting. The copy gets `parent_item_id` (the item it came from) and `origin_item_id` (the first item in the chain), and `carry_count` goes up by one. The old item gets `carried_to_id` and becomes read-only. All events share a `chain_id`, so the history view shows the whole journey across meetings.

**5. What would you improve?**
Logins, automatic Slack/email nudges, Postgres, meaning-based search with embeddings, linking each item to its own docs, and browser tests.
