"""Realistic demo data. Dates are relative to today so 'overdue' stays overdue whenever you run it."""
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import constants as C
from app.core.db import Base, engine
from app.core.logging import log_event
from app.models.entities import ActionItem, KBDoc, Link, Meeting, MeetingEvent, Participant
from app.services.items import add_event

logger = logging.getLogger("app.seed")

PEOPLE = {
    "riya": ("Riya Sharma", "riya@atlas.example", "Project lead (organiser)"),
    "arjun": ("Arjun Mehta", "arjun@atlas.example", "Backend lead"),
    "priya": ("Priya Nair", "priya@atlas.example", "Procurement & budget (on leave)"),
    "daniel": ("Daniel Okafor", "daniel@atlas.example", "QA engineer"),
    "meera": ("Meera Iyer", "meera@atlas.example", "Security"),
    "sam": ("Sam Lee", "sam@atlas.example", "Procurement (covering for Priya)"),
}

DOCS = [
    ("PayFlow Vendor Evaluation Summary", ["vendor", "payments", "payflow", "decision"],
     "We compared three card-processing vendors: PayFlow, CardNest and Quickpay. PayFlow won on fees (1.6% vs 2.1%), "
     "sandbox quality and EU data residency. Risks: PayFlow needs a signed contract before production API keys are "
     "issued, and their onboarding session must be booked two weeks ahead. Owner of the vendor relationship: Riya."),
    ("Payments Migration Runbook", ["payments", "migration", "runbook", "cutover"],
     "Step-by-step plan for moving checkout from the old gateway to PayFlow. 1) Freeze schema changes. 2) Set up "
     "sandbox accounts and test cards. 3) Run the regression test plan on checkout. 4) Dual-run for one week. "
     "5) Cutover on a Tuesday morning with a rollback window of 4 hours. Data migration scripts live in the atlas-db repo."),
    ("Procurement & Contract Approval Policy", ["procurement", "contract", "policy", "legal"],
     "Any vendor contract above 20,000 EUR per year needs legal review and sign-off from the finance director. "
     "Typical turnaround is 5 working days. Contracts must be stored in the shared contracts folder. If the contract "
     "owner goes on leave, they must hand over open negotiations with a written status note."),
    ("Budget Forecasting Guide", ["budget", "finance", "forecast"],
     "The quarterly budget forecast is updated every month by the budget owner. Include vendor fees, one-off "
     "migration costs and a 10% contingency. Send the updated sheet to finance by the 5th working day of the month."),
    ("QA Regression Testing Checklist", ["qa", "testing", "regression", "checkout"],
     "Before any payments release: run the checkout regression suite, test 3DS flows, refunds, partial captures and "
     "currency rounding. Use the vendor sandbox with test cards. Log results in the QA tracker and get sign-off from the QA lead."),
    ("Security Review Process for Third-Party APIs", ["security", "api", "vendor", "review"],
     "Every new third-party API needs a security review: data flow diagram, auth method, key rotation plan, PCI scope "
     "check and penetration test summary from the vendor. Security signs off in writing before production keys are used."),
    ("Team Handover Checklist", ["handover", "leave", "process"],
     "When someone goes on leave or changes role: list every open item with status and due date, name a new owner for "
     "each, share links to key documents, note open negotiations or risks, and book a 30-minute handover call. "
     "The person taking over confirms each item in writing."),
    ("Invoice Approval Workflow", ["finance", "invoice", "approval", "procurement"],
     "Vendor invoices are approved in two steps: the budget owner checks the amount against the contract, then finance "
     "approves payment. Invoices without a purchase order number are rejected. Approval SLA is 3 working days."),
]


def _at(days: int, hour: int = 10) -> datetime:
    return datetime.combine(date.today() + timedelta(days=days), time(hour, 0))


def _people(*rows: tuple[str, str]) -> list[Participant]:
    out = []
    for key, attended in rows:
        name, email, role = PEOPLE[key]
        out.append(Participant(name=name, email=email, role=role, attended=attended))
    return out


def _item(db: Session, meeting: Meeting, title: str, owner: str, due: int | None, status: str = "open",
          priority: str = "medium", outcome: str = "", parent: ActionItem | None = None) -> ActionItem:
    item = ActionItem(meeting_id=meeting.id, title=title, owner=PEOPLE[owner][0] if owner else "",
                      due_date=date.today() + timedelta(days=due) if due is not None else None,
                      status=status, priority=priority, outcome=outcome, created_at=meeting.scheduled_at)
    if parent:
        item.origin_item_id, item.parent_item_id, item.carry_count = parent.chain_id, parent.id, parent.carry_count + 1
    db.add(item)
    db.flush()
    if parent:
        parent.carried_to_id = item.id
        note = f"Carried from '{parent.meeting.title}' to '{meeting.title}' (carry #{item.carry_count})"
        add_event(db, parent, C.EV_CARRIED, str(parent.meeting_id), str(meeting.id), note)
        add_event(db, item, C.EV_CARRIED, str(parent.meeting_id), str(meeting.id), note)
    else:
        add_event(db, item, C.EV_CREATED, to_value=title)
    if status in C.CLOSED_ITEM_STATUSES:
        item.closed_at = meeting.scheduled_at + timedelta(days=3)
        add_event(db, item, C.EV_CLOSED, "open", status, note=outcome)
    elif status != "open" and not parent:
        add_event(db, item, C.EV_STATUS, "open", status)
    return item


def seed(db: Session) -> None:
    docs = [KBDoc(title=t, tags=tags, content=c) for t, tags, c in DOCS]
    db.add_all(docs)

    m1 = Meeting(title="Atlas Kickoff: Payments Vendor Migration", type="meeting", status="completed",
                 scheduled_at=_at(-21), agenda="1. Pick a card-processing vendor\n2. Agree timeline\n3. Assign owners",
                 raw_notes="Compared PayFlow, CardNest, Quickpay. Team agreed PayFlow is best on fees and sandbox. "
                           "Riya to finalise the contract. Arjun drafts the data migration plan. Meera reviews PayFlow API security.",
                 summary="The team chose PayFlow as the new card processor and set a 6-week target for cutover. "
                         "Owners were assigned for the contract, the data migration plan and the security review.",
                 decisions=["Go with PayFlow for card processing", "Target cutover 6 weeks after kickoff"],
                 risks=["PayFlow will not issue production keys until the contract is signed"],
                 participants=_people(("riya", "yes"), ("arjun", "yes"), ("priya", "yes"), ("meera", "yes"), ("daniel", "yes")))
    db.add(m1)
    db.flush()
    contract = _item(db, m1, "Finalise vendor contract with PayFlow", "riya", -10, priority="high")
    _item(db, m1, "Draft data migration plan", "arjun", -14, "done", outcome="Plan approved and stored in the runbook.")
    _item(db, m1, "Security review of PayFlow API", "meera", -12, "done", "high", outcome="Signed off, key rotation every 90 days.")
    _item(db, m1, "Share kickoff slides with stakeholders", "riya", -18, "dropped", "low",
          outcome="Not needed - summary email sent instead.")

    m2 = Meeting(title="Atlas Weekly Sync #2", type="meeting", status="completed", previous_meeting_id=m1.id,
                 scheduled_at=_at(-7), agenda="1. Contract status\n2. Sandbox setup\n3. Test plan\n4. Budget",
                 raw_notes="Contract still waiting on legal. Arjun started sandbox setup. Daniel absent - test plan owner. "
                           "Priya did not reply; budget forecast blocked until she is back.",
                 summary="Contract is stuck in legal review. Sandbox setup is in progress. Schema changes will freeze after "
                         "sprint 14 and QA will test only in the PayFlow sandbox. Budget forecast is blocked while Priya is away.",
                 decisions=["Freeze schema changes after sprint 14", "QA will use the PayFlow sandbox only"],
                 open_questions=["Who approves invoices while Priya is on leave?"],
                 risks=["Contract delay could push the cutover date"],
                 participants=_people(("riya", "yes"), ("arjun", "yes"), ("daniel", "no"), ("priya", "no_response"), ("meera", "yes")))
    db.add(m2)
    db.flush()
    contract2 = _item(db, m2, contract.title, "riya", -10, priority="high", parent=contract)
    _item(db, m2, "Set up PayFlow sandbox accounts and test cards", "arjun", 3, "in_progress")
    _item(db, m2, "Write regression test plan for checkout", "daniel", -2, priority="high")
    budget = _item(db, m2, "Update Q3 budget forecast with PayFlow fees", "priya", -1, "blocked")
    _item(db, m2, "Publish API error-code reference", "arjun", -3, "done", "low", outcome="Published in the runbook appendix.")

    m3 = Meeting(title="Handover: Priya -> Sam (Procurement & Budget)", type="handover", status="scheduled",
                 previous_meeting_id=m2.id, scheduled_at=_at(1, 14),
                 agenda="Priya is on leave for 3 weeks. Sam takes over the vendor contract support, budget forecast and invoices.",
                 raw_notes="", decisions=[],
                 participants=_people(("priya", "no"), ("sam", "yes"), ("riya", "yes")))
    db.add(m3)
    db.flush()
    _item(db, m3, contract.title, "riya", -10, priority="high", parent=contract2)
    budget3 = _item(db, m3, budget.title, "priya", -1, "blocked", parent=budget)
    add_event(db, budget3, C.EV_REASSIGNED, budget3.owner, PEOPLE["sam"][0], note="Priya on leave")
    budget3.owner = PEOPLE["sam"][0]
    _item(db, m3, "Confirm invoice approval workflow while Priya is away", "", None)
    _item(db, m3, "Book PayFlow onboarding session", "riya", 5)

    db.add_all([
        Link(meeting_id=m1.id, doc_id=docs[0].id, reason="Explains why PayFlow was chosen", score=0.42, source="seed"),
        Link(meeting_id=m2.id, doc_id=docs[4].id, reason="Checklist the regression test plan must follow", score=0.31, source="seed"),
        Link(meeting_id=m2.id, target_meeting_id=m1.id, reason="Kickoff where the vendor decision was made", score=0.28, source="seed"),
    ])
    for m in (m1, m2, m3):
        db.add(MeetingEvent(meeting_id=m.id, event_type="created", note="Seeded demo data", created_at=m.scheduled_at - timedelta(days=2)))
    db.commit()
    log_event(logger, "demo_seeded", "Demo data seeded", meetings=3, kb_docs=len(docs))


def seed_if_empty(db: Session) -> None:
    if db.scalars(select(Meeting).limit(1)).first() is None and db.scalars(select(KBDoc).limit(1)).first() is None:
        seed(db)


def reset_demo(db: Session) -> None:
    db.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed(db)
    log_event(logger, "demo_reset", "Demo data reset")
