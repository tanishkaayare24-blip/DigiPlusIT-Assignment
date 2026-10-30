// ContextRelay single-page UI (vanilla JS, hash routing).
const view = document.getElementById("view");
const CARD = "bg-white rounded-xl border border-slate-200 p-4";
const BTN = "px-3 py-1.5 rounded-lg text-sm font-medium";
const BTN_PRIMARY = `${BTN} bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50`;
const BTN_LIGHT = `${BTN} border border-slate-300 bg-white hover:bg-slate-100 disabled:opacity-50`;
const INPUT = "w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300";
const ITEM_STATUSES = ["open", "in_progress", "blocked", "done", "dropped"];
const NEXT_STATUS = { draft: ["scheduled", "archived"], scheduled: ["completed", "draft", "archived"], completed: ["archived"], archived: [] };
const state = { viewer: "", people: [], meeting: null, recap: null };

// ---------- helpers ----------
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (d) => (d ? new Date(d.length === 10 ? d + "T00:00:00" : d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
const fmtDateTime = (d) => (d ? new Date(d).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const label = (s) => String(s || "").replace(/_/g, " ");
const store = {
  get(k) { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

function toast(message, type = "info", requestId = "") {
  const colors = { info: "bg-slate-800", success: "bg-emerald-600", error: "bg-rose-600", warn: "bg-amber-600" };
  const el = document.createElement("div");
  el.className = `${colors[type]} text-white text-sm rounded-lg shadow-lg px-4 py-3`;
  el.innerHTML = `${esc(message)}${requestId ? `<div class="text-xs opacity-75 mt-1">Request ID: ${esc(requestId)}</div>` : ""}`;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "error" ? 7000 : 3500);
}

async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  } catch {
    toast("Cannot reach the server. Check your connection.", "error");
    throw new Error("network");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => `${d.field ? d.field + ": " : ""}${d.message.replace(/^Value error, /, "")}`).join(" · ")
      : data.detail || "Something went wrong.";
    toast(detail, "error", data.request_id || res.headers.get("X-Request-ID"));
    throw new Error(detail);
  }
  if (data && data.ai_mode) setAiMode(data.ai_mode);
  return data;
}

async function withBusy(btn, fn) {
  const original = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Working...`; }
  try { return await fn(); } catch { return null; } finally { if (btn) { btn.disabled = false; btn.innerHTML = original; } }
}

function setAiMode(mode, reason = "") {
  const banner = document.getElementById("ai-banner");
  const pill = document.getElementById("ai-pill");
  banner.classList.toggle("hidden", mode !== "basic");
  if (reason) document.getElementById("ai-banner-reason").textContent = `(${reason})`;
  pill.textContent = mode === "basic" ? "AI: basic mode" : "AI: on";
  pill.className = `px-2 py-1 rounded-full text-xs ${mode === "basic" ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`;
}

const STATUS_COLORS = {
  draft: "bg-slate-100 text-slate-700", scheduled: "bg-sky-100 text-sky-800", completed: "bg-emerald-100 text-emerald-800",
  archived: "bg-slate-200 text-slate-500", open: "bg-sky-100 text-sky-800", in_progress: "bg-indigo-100 text-indigo-800",
  blocked: "bg-rose-100 text-rose-800", done: "bg-emerald-100 text-emerald-800", dropped: "bg-slate-200 text-slate-500",
  meeting: "bg-violet-100 text-violet-800", handover: "bg-orange-100 text-orange-800",
  high: "bg-rose-50 text-rose-700", medium: "bg-amber-50 text-amber-700", low: "bg-slate-100 text-slate-600",
};
const pill = (v) => `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[v] || "bg-slate-100"}">${esc(label(v))}</span>`;
const BAND = { green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-rose-500" };
const healthBadge = (h, big = false) => h
  ? `<span title="Handoff Health Score" class="inline-flex items-center justify-center ${big ? "w-14 h-14 text-xl" : "w-9 h-9 text-xs"} rounded-full font-bold text-white ${BAND[h.band]}">${h.score}</span>` : "";
const empty = (text) => `<div class="text-sm text-slate-400 italic py-3">${esc(text)}</div>`;
const loading = () => { view.innerHTML = `<div class="text-slate-500 py-10 text-center"><span class="spinner"></span> Loading...</div>`; };

function dueCell(i) {
  if (!i.due_date) return `<span class="text-slate-400">no date</span>`;
  return i.days_overdue > 0
    ? `<span class="text-rose-600 font-medium">${fmtDate(i.due_date)} · ${i.days_overdue}d overdue</span>`
    : fmtDate(i.due_date);
}

function itemFlags(i) {
  return [
    i.ai_suggested ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-100 text-fuchsia-700">AI-suggested</span>` : "",
    i.carry_count ? `<span class="text-[10px] px-1.5 py-0.5 rounded ${i.carry_count >= 2 ? "bg-rose-100 text-rose-700" : "bg-slate-100 text-slate-600"}">carried ${i.carry_count}x</span>` : "",
  ].join(" ");
}

// ---------- modal ----------
function openModal(title, html) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("modal").classList.remove("hidden");
}
function closeModal() { document.getElementById("modal").classList.add("hidden"); }
document.getElementById("modal-close").onclick = closeModal;
document.getElementById("modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

// ---------- router ----------
async function route() {
  const hash = location.hash || "#/";
  const [, section, id] = hash.split("/");
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const active = (a.dataset.nav === "dashboard" && !section) || a.dataset.nav === section;
    a.classList.toggle("bg-indigo-50", active); a.classList.toggle("text-indigo-700", active);
  });
  loading();
  try {
    if (!section) await renderDashboard();
    else if (section === "meetings" && id) await renderMeeting(Number(id));
    else if (section === "meetings") await renderMeetings();
    else if (section === "items") await renderItems();
    else if (section === "kb") await renderKB();
    else view.innerHTML = empty("Page not found.");
  } catch (e) {
    view.innerHTML = `<div class="${CARD} text-center py-10"><p class="text-slate-600">This page could not be loaded.</p>
      <button class="${BTN_LIGHT} mt-3" onclick="route()">Try again</button></div>`;
  }
}
window.addEventListener("hashchange", route);

// ---------- dashboard ----------
async function renderDashboard() {
  const d = await api("GET", `/api/dashboard?person=${encodeURIComponent(state.viewer)}`);
  const r = d.radar;
  view.innerHTML = `
    <div class="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div><h1 class="text-2xl font-bold">Dashboard</h1>
        <p class="text-sm text-slate-500">What is at risk of being lost, and what you should do next.</p></div>
      <button class="${BTN_PRIMARY}" onclick="meetingForm()">+ New meeting / handover</button>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
      ${stat("Workspace health", `${r.workspace_score}/100`)}
      ${stat("Open items", d.stats.open_items)}
      ${stat("Overdue", d.stats.overdue, d.stats.overdue ? "text-rose-600" : "")}
      ${stat("No owner", d.stats.unowned, d.stats.unowned ? "text-amber-600" : "")}
    </div>
    <div class="grid lg:grid-cols-3 gap-5">
      <section class="${CARD} lg:col-span-2">
        <h2 class="font-semibold mb-1">Risk Radar</h2>
        <p class="text-xs text-slate-500 mb-3">Meetings and items most likely to lose context, across the whole workspace.</p>
        <h3 class="text-xs uppercase tracking-wide text-slate-400 mb-2">At-risk meetings</h3>
        <div class="space-y-2 mb-4">${r.meetings.map((m) => `
          <a href="#/meetings/${m.id}" class="flex items-start gap-3 p-2 rounded-lg hover:bg-slate-50">
            ${healthBadge(m)}
            <div class="min-w-0"><div class="font-medium">${esc(m.title)} ${pill(m.type)}</div>
              <ul class="text-xs text-slate-500 list-disc ml-4">${m.top_reasons.map((t) => `<li>${esc(t)}</li>`).join("") || "<li>No problems found</li>"}</ul></div>
          </a>`).join("") || empty("No meetings yet.")}</div>
        <h3 class="text-xs uppercase tracking-wide text-slate-400 mb-2">At-risk items</h3>
        <div class="divide-y">${r.items.map((i) => `
          <div class="py-2 flex flex-wrap items-center gap-2 text-sm">
            <button class="font-medium text-left hover:text-indigo-700" onclick="itemHistory(${i.id})">${esc(i.title)}</button>
            ${i.risk_reasons.map((x) => `<span class="text-[11px] px-1.5 py-0.5 rounded bg-rose-50 text-rose-700">${esc(x)}</span>`).join("")}
            <span class="ml-auto text-xs text-slate-500">${esc(i.owner || "unassigned")} · <a class="hover:underline" href="#/meetings/${i.meeting_id}">${esc(i.meeting_title)}</a></span>
          </div>`).join("") || empty("Nothing at risk. Nice!")}</div>
      </section>
      <div class="space-y-5">
        <section class="${CARD}">
          <h2 class="font-semibold mb-2">My open items ${state.viewer ? `<span class="text-xs font-normal text-slate-500">(${esc(state.viewer)})</span>` : ""}</h2>
          ${!state.viewer ? empty("Pick your name in 'Viewing as' (top right).") : d.my_items.map((i) => `
            <div class="py-2 border-b last:border-0 text-sm">
              <button class="font-medium text-left hover:text-indigo-700" onclick="itemHistory(${i.id})">${esc(i.title)}</button>
              <div class="flex flex-wrap gap-2 items-center mt-1 text-xs">${pill(i.status)} ${dueCell(i)} ${itemFlags(i)}</div>
            </div>`).join("") || empty("You have no open items.")}
        </section>
        <section class="${CARD}">
          <h2 class="font-semibold mb-2">Upcoming meetings</h2>
          ${d.upcoming.map((m) => `
            <a href="#/meetings/${m.id}" class="block py-2 border-b last:border-0 text-sm hover:text-indigo-700">
              <div class="font-medium">${esc(m.title)}</div>
              <div class="text-xs text-slate-500">${fmtDateTime(m.scheduled_at)} · ${pill(m.status)} · ${m.open_item_count} open items</div>
            </a>`).join("") || empty("No upcoming meetings.")}
        </section>
      </div>
    </div>`;
}
const stat = (name, value, cls = "") => `<div class="${CARD}"><div class="text-xs text-slate-500">${name}</div><div class="text-2xl font-bold ${cls}">${value}</div></div>`;

// ---------- meetings list ----------
async function renderMeetings() {
  const list = await api("GET", "/api/meetings");
  view.innerHTML = `
    <div class="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div><h1 class="text-2xl font-bold">Meetings & handovers</h1>
        <p class="text-sm text-slate-500">Every meeting and work handover, with its Handoff Health Score.</p></div>
      <button class="${BTN_PRIMARY}" onclick="meetingForm()">+ New meeting / handover</button>
    </div>
    <div class="${CARD} p-0 overflow-x-auto">
      <table class="w-full text-sm"><thead class="text-left text-xs text-slate-500 border-b"><tr>
        <th class="p-3">Health</th><th class="p-3">Title</th><th class="p-3">Type</th><th class="p-3">Status</th><th class="p-3">When</th><th class="p-3">Open items</th></tr></thead>
      <tbody>${list.map((m) => `
        <tr class="border-b last:border-0 hover:bg-slate-50 cursor-pointer" onclick="location.hash='#/meetings/${m.id}'">
          <td class="p-3">${healthBadge(m.health)}</td><td class="p-3 font-medium">${esc(m.title)}</td>
          <td class="p-3">${pill(m.type)}</td><td class="p-3">${pill(m.status)}</td>
          <td class="p-3 text-slate-500">${fmtDateTime(m.scheduled_at)}</td><td class="p-3">${m.open_item_count}</td>
        </tr>`).join("")}</tbody></table>
      ${list.length ? "" : `<div class="p-6">${empty("No meetings yet. Create your first one.")}</div>`}
    </div>`;
}

async function meetingForm(existing = null) {
  const all = await api("GET", "/api/meetings");
  const m = existing || { title: "", type: "meeting", agenda: "", raw_notes: "", decisions: [], participants: [], previous_meeting_id: null, scheduled_at: null };
  const prevOptions = all.filter((x) => x.id !== m.id)
    .map((x) => `<option value="${x.id}" ${x.id === m.previous_meeting_id ? "selected" : ""}>${esc(x.title)}</option>`).join("");
  openModal(existing ? "Edit meeting" : "New meeting or handover", `
    <form id="meeting-form" class="space-y-3">
      <div><label class="text-sm font-medium">Title</label><input name="title" required minlength="3" class="${INPUT}" value="${esc(m.title)}"></div>
      <div class="grid grid-cols-2 gap-3">
        <div><label class="text-sm font-medium">Type</label><select name="type" class="${INPUT}">
          <option value="meeting" ${m.type === "meeting" ? "selected" : ""}>Meeting</option>
          <option value="handover" ${m.type === "handover" ? "selected" : ""}>Work handover</option></select></div>
        <div><label class="text-sm font-medium">When</label><input type="datetime-local" name="scheduled_at" class="${INPUT}" value="${m.scheduled_at ? m.scheduled_at.slice(0, 16) : ""}"></div>
      </div>
      <div><label class="text-sm font-medium">Follows meeting (for carry-over)</label>
        <select name="previous_meeting_id" class="${INPUT}"><option value="">— none —</option>${prevOptions}</select></div>
      <div><label class="text-sm font-medium">Agenda</label><textarea name="agenda" rows="3" class="${INPUT}">${esc(m.agenda)}</textarea></div>
      <div><label class="text-sm font-medium">Participants</label>
        <div id="participants" class="space-y-2"></div>
        <button type="button" class="${BTN_LIGHT} mt-2" onclick="addParticipantRow()">+ Add participant</button></div>
      <div><label class="text-sm font-medium">Raw notes</label><textarea name="raw_notes" rows="4" class="${INPUT}">${esc(m.raw_notes)}</textarea></div>
      <div><label class="text-sm font-medium">Decisions <span class="text-xs text-slate-400">(one per line)</span></label>
        <textarea name="decisions" rows="3" class="${INPUT}">${esc((m.decisions || []).join("\n"))}</textarea></div>
      <div class="flex justify-end gap-2 pt-2"><button type="button" class="${BTN_LIGHT}" onclick="closeModal()">Cancel</button>
        <button class="${BTN_PRIMARY}" id="meeting-save">${existing ? "Save changes" : "Create"}</button></div>
    </form>`);
  (m.participants.length ? m.participants : [{}]).forEach(addParticipantRow);
  document.getElementById("meeting-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const participants = [...document.querySelectorAll(".p-row")].map((row) => ({
      name: row.querySelector("[data-f=name]").value.trim(), email: row.querySelector("[data-f=email]").value.trim(),
      role: row.querySelector("[data-f=role]").value.trim(), attended: row.querySelector("[data-f=attended]").value,
    })).filter((p) => p.name);
    const body = {
      title: f.get("title"), type: f.get("type"), agenda: f.get("agenda"), raw_notes: f.get("raw_notes"),
      decisions: f.get("decisions").split("\n").map((s) => s.trim()).filter(Boolean), participants,
      scheduled_at: f.get("scheduled_at") || null, previous_meeting_id: f.get("previous_meeting_id") ? Number(f.get("previous_meeting_id")) : null,
    };
    const saved = await withBusy(document.getElementById("meeting-save"), () =>
      existing ? api("PUT", `/api/meetings/${existing.id}`, body) : api("POST", "/api/meetings", body));
    if (!saved) return;
    closeModal();
    toast(existing ? "Meeting saved" : "Meeting created", "success");
    if (existing) route(); else location.hash = `#/meetings/${saved.id}`;
  };
}

function addParticipantRow(p = {}) {
  const row = document.createElement("div");
  row.className = "p-row grid grid-cols-12 gap-2";
  const opt = (v, t) => `<option value="${v}" ${p.attended === v ? "selected" : ""}>${t}</option>`;
  row.innerHTML = `
    <input data-f="name" placeholder="Name" class="${INPUT} col-span-3" value="${esc(p.name)}">
    <input data-f="email" placeholder="Email" class="${INPUT} col-span-3" value="${esc(p.email)}">
    <input data-f="role" placeholder="Role" class="${INPUT} col-span-3" value="${esc(p.role)}">
    <select data-f="attended" class="${INPUT} col-span-2">${opt("no_response", "No reply")}${opt("yes", "Attended")}${opt("no", "Missed")}</select>
    <button type="button" class="col-span-1 text-slate-400 hover:text-rose-600" onclick="this.parentElement.remove()" aria-label="Remove">&times;</button>`;
  document.getElementById("participants").appendChild(row);
}

// ---------- meeting detail ----------
async function renderMeeting(id) {
  const m = await api("GET", `/api/meetings/${id}`);
  state.meeting = m;
  const h = m.health;
  view.innerHTML = `
    <a href="#/meetings" class="text-sm text-slate-500 hover:text-indigo-700">&larr; All meetings</a>
    <div class="flex flex-wrap items-start gap-4 mt-2 mb-5">
      ${healthBadge(h, true)}
      <div class="flex-1 min-w-0">
        <h1 class="text-2xl font-bold">${esc(m.title)}</h1>
        <div class="flex flex-wrap items-center gap-2 mt-1 text-sm text-slate-500">${pill(m.type)} ${pill(m.status)} · ${fmtDateTime(m.scheduled_at)}
          ${m.previous_meeting ? `· follows <a class="text-indigo-700 hover:underline" href="#/meetings/${m.previous_meeting.id}">${esc(m.previous_meeting.title)}</a>` : ""}</div>
      </div>
      <div class="flex flex-wrap gap-2">
        ${NEXT_STATUS[m.status].map((s) => `<button class="${BTN_LIGHT}" onclick="changeStatus(this, '${s}')">Mark ${label(s)}</button>`).join("")}
        ${m.status !== "archived" ? `<button class="${BTN_LIGHT}" onclick="meetingForm(state.meeting)">Edit</button>` : ""}
        <button class="${BTN_LIGHT} text-rose-600" onclick="deleteMeeting()">Delete</button>
      </div>
    </div>
    <div class="grid lg:grid-cols-3 gap-5">
      <div class="lg:col-span-2 space-y-5">
        ${overviewCard(m)}
        ${itemsCard(m)}
        ${recapCard(m)}
      </div>
      <div class="space-y-5">
        ${healthCard(h)}
        ${nudgesCard(m)}
        ${participantsCard(m)}
        ${linksCard(m)}
        ${timelineCard(m)}
      </div>
    </div>`;
}

function overviewCard(m) {
  const list = (items, cls = "") => items.length ? `<ul class="list-disc ml-5 space-y-1 ${cls}">${items.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : empty("None recorded.");
  return `<section class="${CARD} space-y-4">
    <div><h2 class="font-semibold mb-1">Agenda</h2><p class="text-sm whitespace-pre-line">${esc(m.agenda) || '<span class="text-slate-400 italic">No agenda.</span>'}</p></div>
    ${m.summary ? `<div><h2 class="font-semibold mb-1">Summary</h2><p class="text-sm">${esc(m.summary)}</p></div>` : ""}
    <div><h2 class="font-semibold mb-1">Decisions</h2><div class="text-sm">${list(m.decisions)}</div></div>
    ${m.open_questions.length ? `<div><h2 class="font-semibold mb-1">Open questions</h2><div class="text-sm">${list(m.open_questions)}</div></div>` : ""}
    ${m.risks.length ? `<div><h2 class="font-semibold mb-1">Risks</h2><div class="text-sm text-rose-700">${list(m.risks)}</div></div>` : ""}
    <details><summary class="text-sm font-semibold cursor-pointer">Raw notes</summary>
      <p class="text-sm whitespace-pre-line mt-2 text-slate-600">${esc(m.raw_notes) || "No notes yet."}</p></details>
  </section>`;
}

function itemsCard(m) {
  const archived = m.status === "archived";
  return `<section class="${CARD}">
    <div class="flex flex-wrap items-center gap-2 mb-3">
      <h2 class="font-semibold">Action items</h2>
      <div class="ml-auto flex gap-2">
        ${!archived ? `<button class="${BTN_LIGHT}" onclick="carryOver(this)" title="Copy every unclosed item from the previous meeting into this one">&#8635; Carry over open items</button>
        <button class="${BTN_PRIMARY}" onclick="itemForm(${m.id})">+ Add item</button>` : ""}
      </div>
    </div>
    ${itemsTable(m.items, !archived)}
    ${m.carried_out_items.length ? `<p class="text-xs text-slate-400 mt-3">${m.carried_out_items.length} item(s) from here were carried forward to a later meeting.</p>` : ""}
  </section>`;
}

function itemsTable(items, editable = true, showMeeting = false) {
  if (!items.length) return empty("No action items.");
  return `<div class="overflow-x-auto"><table class="w-full text-sm"><thead class="text-left text-xs text-slate-500 border-b"><tr>
    <th class="py-2 pr-2">Item</th>${showMeeting ? '<th class="py-2 pr-2">Meeting</th>' : ""}<th class="py-2 pr-2">Owner</th><th class="py-2 pr-2">Due</th><th class="py-2 pr-2">Priority</th><th class="py-2 pr-2">Status</th><th></th></tr></thead>
    <tbody>${items.map((i) => `
      <tr class="border-b last:border-0 align-top">
        <td class="py-2 pr-2"><button class="font-medium text-left hover:text-indigo-700" onclick="itemHistory(${i.id})">${esc(i.title)}</button>
          <div class="mt-1 space-x-1">${itemFlags(i)}</div>${i.outcome ? `<div class="text-xs text-slate-500 mt-1">Outcome: ${esc(i.outcome)}</div>` : ""}</td>
        ${showMeeting ? `<td class="py-2 pr-2"><a class="text-indigo-700 hover:underline" href="#/meetings/${i.meeting_id}">${esc(i.meeting_title)}</a></td>` : ""}
        <td class="py-2 pr-2">${i.owner ? esc(i.owner) : '<span class="text-amber-600">unassigned</span>'}</td>
        <td class="py-2 pr-2 whitespace-nowrap">${dueCell(i)}</td>
        <td class="py-2 pr-2">${pill(i.priority)}</td>
        <td class="py-2 pr-2">${editable ? `<select class="border border-slate-300 rounded px-1 py-0.5 text-xs" onchange="setItemStatus(${i.id}, this)">
            ${ITEM_STATUSES.map((s) => `<option value="${s}" ${s === i.status ? "selected" : ""}>${label(s)}</option>`).join("")}</select>` : pill(i.status)}</td>
        <td class="py-2 text-right">${editable && !i.is_closed ? `<button class="text-xs text-indigo-700 hover:underline" onclick='itemForm(${i.meeting_id}, ${JSON.stringify(i).replace(/'/g, "&#39;")})'>Edit</button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>`;
}

function recapCard(m) {
  return `<section class="${CARD}" id="recap-card">
    <h2 class="font-semibold">AI recap</h2>
    <p class="text-xs text-slate-500 mb-2">Paste raw notes, a chat, an email or a transcript. The AI suggests a summary, decisions and action items.
      <strong>Nothing is saved until you review it and click Save.</strong></p>
    <textarea id="recap-text" rows="5" class="${INPUT}" placeholder="e.g. Riya: we agreed to push cutover a week. Action: Sam to update the budget by Friday...">${esc(m.raw_notes)}</textarea>
    <div class="flex justify-end mt-2"><button class="${BTN_PRIMARY}" onclick="generateRecap(this)" ${m.status === "archived" ? "disabled" : ""}>Generate recap</button></div>
    <div id="recap-review"></div>
  </section>`;
}

function healthCard(h) {
  return `<section class="${CARD}">
    <div class="flex items-center gap-3 mb-2">${healthBadge(h)}<div><h2 class="font-semibold">Handoff Health Score</h2>
      <p class="text-xs text-slate-500">How likely context is to get lost. 100 = safe.</p></div></div>
    ${h.reasons.length ? `<ul class="text-sm space-y-1.5">${h.reasons.map((r) => `
      <li class="flex gap-2"><span class="text-rose-600 font-mono text-xs w-8 shrink-0 text-right">-${r.penalty}</span><span>${esc(r.message)}</span></li>`).join("")}</ul>`
      : `<p class="text-sm text-emerald-700">No risks found. Context is well captured.</p>`}
  </section>`;
}

function nudgesCard(m) {
  return `<section class="${CARD}">
    <div class="flex items-center mb-2"><h2 class="font-semibold">Nudge Engine</h2>
      <button class="${BTN_LIGHT} ml-auto" onclick="generateNudges(this)">Draft nudges</button></div>
    <p class="text-xs text-slate-500 mb-2">Ready-to-send follow-ups for each risk above.</p>
    <div class="space-y-2">${m.nudges.map((n) => `
      <div class="border rounded-lg p-2 text-sm ${n.sent_at ? "opacity-60" : ""}">
        <div class="text-xs text-slate-500 mb-1">To <strong>${esc(n.recipient)}</strong> · ${label(n.reason_code)} ${n.generated_by === "basic" ? "· template" : "· AI"}</div>
        <p id="nudge-${n.id}">${esc(n.message)}</p>
        <div class="flex gap-2 mt-2">
          <button class="text-xs text-indigo-700 hover:underline" onclick="copyText('nudge-${n.id}')">Copy</button>
          ${n.sent_at ? `<span class="text-xs text-emerald-700">Sent ${fmtDateTime(n.sent_at + "Z")}</span>`
            : `<button class="text-xs text-emerald-700 hover:underline" onclick="markSent(${n.id})">Mark nudge sent</button>`}
        </div>
      </div>`).join("") || empty("No nudges drafted yet.")}</div>
  </section>`;
}

function participantsCard(m) {
  const att = { yes: "Attended", no: "Missed", no_response: "No reply" };
  const briefs = Object.fromEntries(m.briefs.map((b) => [b.person_name, b]));
  return `<section class="${CARD}">
    <h2 class="font-semibold mb-1">Participants & catch-up briefs</h2>
    <p class="text-xs text-slate-500 mb-2">Send a personal brief to anyone who missed this or is taking over.</p>
    ${m.participants.map((p) => `
      <div class="py-2 border-b last:border-0">
        <div class="flex items-center gap-2 text-sm">
          <div class="min-w-0"><div class="font-medium">${esc(p.name)}</div><div class="text-xs text-slate-500">${esc(p.role)} ${p.email ? "· " + esc(p.email) : ""}</div></div>
          <span class="ml-auto text-xs px-2 py-0.5 rounded-full ${p.attended === "yes" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}">${att[p.attended]}</span>
        </div>
        <div class="mt-1 flex gap-3">
          ${briefs[p.name] ? `<button class="text-xs text-indigo-700 hover:underline" onclick="showBrief('${esc(p.name)}')">View brief</button>
            <button class="text-xs text-slate-500 hover:underline" onclick="makeBrief(this, '${esc(p.name)}', true)">Regenerate</button>`
            : `<button class="text-xs text-indigo-700 hover:underline" onclick="makeBrief(this, '${esc(p.name)}', false)">Generate catch-up brief</button>`}
        </div>
      </div>`).join("") || empty("No participants.")}
  </section>`;
}

function linksCard(m) {
  return `<section class="${CARD}">
    <div class="flex items-center mb-2"><h2 class="font-semibold">Linked knowledge</h2>
      <button class="${BTN_LIGHT} ml-auto" onclick="suggestLinks(this)">Find related</button></div>
    ${m.links.map((l) => `
      <div class="py-2 border-b last:border-0 text-sm flex gap-2">
        <div class="min-w-0">
          ${l.kind === "doc" ? `<button class="font-medium text-left hover:text-indigo-700" onclick="viewDoc(${l.target_id})">&#128196; ${esc(l.title)}</button>`
            : `<a class="font-medium hover:text-indigo-700" href="#/meetings/${l.target_id}">&#128197; ${esc(l.title)}</a>`}
          <div class="text-xs text-slate-500">${esc(l.reason)} ${l.source === "ai" ? '<span class="text-fuchsia-600">· AI</span>' : ""}</div>
        </div>
        <button class="ml-auto text-slate-400 hover:text-rose-600 text-xs" title="Remove wrong link" onclick="removeLink(${l.id})">remove</button>
      </div>`).join("") || empty("No linked docs yet. Click 'Find related'.")}
  </section>`;
}

function timelineCard(m) {
  return `<section class="${CARD}">
    <h2 class="font-semibold mb-2">History</h2>
    <ol class="space-y-2 text-sm max-h-80 overflow-y-auto">${m.timeline.map((e) => `
      <li class="border-l-2 ${e.kind === "meeting" ? "border-indigo-300" : "border-slate-200"} pl-3">
        <div class="text-xs text-slate-400">${fmtDateTime(e.at + "Z")} · ${label(e.type)}</div><div>${esc(e.text)}</div></li>`).join("") || empty("No history yet.")}</ol>
  </section>`;
}

// ---------- meeting actions ----------
async function changeStatus(btn, status) {
  if (await withBusy(btn, () => api("POST", `/api/meetings/${state.meeting.id}/status`, { status }))) {
    toast(`Meeting marked ${label(status)}`, "success"); route();
  }
}
async function deleteMeeting() {
  if (!confirm("Delete this meeting? It will be hidden from all lists.")) return;
  try { await api("DELETE", `/api/meetings/${state.meeting.id}`); toast("Meeting deleted", "success"); location.hash = "#/meetings"; } catch { /* toast shown */ }
}
async function carryOver(btn) {
  const m = state.meeting;
  let from = m.previous_meeting_id;
  if (!from) {
    const list = (await api("GET", "/api/meetings")).filter((x) => x.id !== m.id);
    const choice = prompt(`Carry open items from which meeting? Enter its number:\n${list.map((x) => `${x.id}: ${x.title}`).join("\n")}`);
    if (!choice) return;
    from = Number(choice);
  }
  const res = await withBusy(btn, () => api("POST", `/api/meetings/${m.id}/carry-over`, { from_meeting_id: from }));
  if (res) { toast(res.carried ? `${res.carried} open item(s) carried over with their history` : "No open items left to carry over", res.carried ? "success" : "info"); route(); }
}

async function generateRecap(btn) {
  const text = document.getElementById("recap-text").value.trim();
  if (text.length < 20) { toast("Paste at least a few sentences of notes first.", "warn"); return; }
  const res = await withBusy(btn, () => api("POST", `/api/meetings/${state.meeting.id}/recap`, { text }));
  if (!res) return;
  state.recap = { ...res.recap, source_text: text, mode: res.ai_mode };
  renderRecapReview();
}

function renderRecapReview() {
  const r = state.recap;
  const box = document.getElementById("recap-review");
  const listEditor = (key, title) => `
    <div><h3 class="text-sm font-semibold mt-3 mb-1">${title}</h3>
      ${r[key].map((v, i) => `<label class="flex gap-2 items-start mb-1"><input type="checkbox" checked data-list="${key}" data-i="${i}" class="mt-2">
        <input class="${INPUT}" data-list-text="${key}" data-i="${i}" value="${esc(v)}"></label>`).join("") || empty("None found.")}</div>`;
  box.innerHTML = `
    <div class="mt-4 border-t pt-4">
      <div class="flex items-center gap-2 mb-2"><span class="text-[11px] px-2 py-0.5 rounded bg-fuchsia-100 text-fuchsia-700">${r.mode === "basic" ? "Basic-mode suggestion" : "AI-suggested"}</span>
        <span class="text-xs text-slate-500">Review, edit and untick anything wrong.</span></div>
      <h3 class="text-sm font-semibold mb-1">Summary</h3><textarea id="recap-summary" rows="3" class="${INPUT}">${esc(r.summary)}</textarea>
      ${listEditor("decisions", "Decisions")}
      <h3 class="text-sm font-semibold mt-3 mb-1">Action items</h3>
      ${r.action_items.map((a, i) => `
        <div class="border rounded-lg p-2 mb-2 recap-item" data-i="${i}">
          <div class="flex items-center gap-2 mb-2">
            <label class="text-xs flex items-center gap-1"><input type="radio" name="acc-${i}" value="accept" checked> Accept</label>
            <label class="text-xs flex items-center gap-1"><input type="radio" name="acc-${i}" value="reject"> Reject</label>
            <span class="ml-auto text-xs ${a.confidence < 0.5 ? "text-amber-600" : "text-slate-500"}">confidence ${Math.round(a.confidence * 100)}%</span></div>
          <div class="grid grid-cols-12 gap-2">
            <input class="${INPUT} col-span-12 md:col-span-5" data-f="title" value="${esc(a.title)}">
            <input class="${INPUT} col-span-5 md:col-span-3" data-f="owner" placeholder="Owner" value="${esc(a.owner)}" list="people-list">
            <input class="${INPUT} col-span-4 md:col-span-2" type="date" data-f="due_date" value="${a.due_date || ""}">
            <select class="${INPUT} col-span-3 md:col-span-2" data-f="priority">${["low", "medium", "high"].map((p) => `<option ${p === a.priority ? "selected" : ""}>${p}</option>`).join("")}</select>
          </div></div>`).join("") || empty("No action items found.")}
      ${listEditor("open_questions", "Open questions")}
      ${listEditor("risks", "Risks")}
      <datalist id="people-list">${state.people.map((p) => `<option value="${esc(p)}">`).join("")}</datalist>
      <div class="flex justify-end gap-2 mt-3">
        <button class="${BTN_LIGHT}" onclick="state.recap=null; document.getElementById('recap-review').innerHTML=''">Discard</button>
        <button class="${BTN_PRIMARY}" onclick="acceptRecap(this)">Save accepted items</button></div>
    </div>`;
}

async function acceptRecap(btn) {
  const pick = (key) => [...document.querySelectorAll(`[data-list="${key}"]`)].filter((c) => c.checked)
    .map((c) => document.querySelector(`[data-list-text="${key}"][data-i="${c.dataset.i}"]`).value.trim()).filter(Boolean);
  const items = [...document.querySelectorAll(".recap-item")].filter((el) => el.querySelector(`input[value=accept]`).checked)
    .map((el) => ({ title: el.querySelector("[data-f=title]").value.trim(), owner: el.querySelector("[data-f=owner]").value.trim(),
      due_date: el.querySelector("[data-f=due_date]").value || null, priority: el.querySelector("[data-f=priority]").value }));
  const body = { summary: document.getElementById("recap-summary").value.trim(), decisions: pick("decisions"),
    open_questions: pick("open_questions"), risks: pick("risks"), action_items: items, source_text: state.recap.source_text };
  if (await withBusy(btn, () => api("POST", `/api/meetings/${state.meeting.id}/recap/accept`, body))) {
    state.recap = null; toast(`Recap saved with ${items.length} action item(s)`, "success"); route();
  }
}

async function makeBrief(btn, person, regenerate) {
  const res = await withBusy(btn, () => api("POST", `/api/meetings/${state.meeting.id}/briefs`, { person_name: person, regenerate }));
  if (!res) return;
  await route();
  showBrief(person, res.brief);
}
function showBrief(person, brief = null) {
  const b = brief || state.meeting.briefs.find((x) => x.person_name === person);
  if (!b) return;
  const c = b.content;
  const sec = (t, arr) => arr.length ? `<h4 class="font-semibold mt-3 mb-1">${t}</h4><ul class="list-disc ml-5">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  openModal(`Catch-up brief for ${person}`, `
    <div class="text-sm" id="brief-text">
      <div class="text-[11px] inline-block px-2 py-0.5 rounded bg-fuchsia-100 text-fuchsia-700 mb-2">${b.generated_by === "basic" ? "Basic mode" : "AI-generated"} · ${fmtDateTime(b.created_at + "Z")}</div>
      <p class="font-semibold">${esc(c.headline)}</p><p class="mt-2">${esc(c.what_happened)}</p>
      ${sec("Decisions that affect you", c.decisions_affecting_you)}${sec("Your items", c.your_items)}
      ${sec("Overdue", c.overdue)}${sec("Do this first", c.do_first)}
    </div>
    <div class="flex justify-end gap-2 mt-4"><button class="${BTN_LIGHT}" onclick="copyText('brief-text')">Copy</button>
      <button class="${BTN_PRIMARY}" onclick="closeModal()">Done</button></div>`);
}

async function suggestLinks(btn) {
  const res = await withBusy(btn, () => api("POST", `/api/meetings/${state.meeting.id}/links/suggest`));
  if (res) { toast(res.added ? `${res.added} related item(s) linked` : "No new related documents found", res.added ? "success" : "info"); route(); }
}
async function removeLink(id) {
  try { await api("DELETE", `/api/links/${id}`); toast("Link removed", "success"); route(); } catch { /* toast shown */ }
}
async function generateNudges(btn) {
  const res = await withBusy(btn, () => api("POST", `/api/meetings/${state.meeting.id}/nudges`));
  if (res) { toast(res.nudges.length ? `${res.nudges.length} nudge(s) drafted` : "No nudges needed", "success"); route(); }
}
async function markSent(id) {
  try { await api("POST", `/api/nudges/${id}/sent`); toast("Logged as sent", "success"); route(); } catch { /* toast shown */ }
}
function copyText(elId) {
  const text = document.getElementById(elId).innerText;
  navigator.clipboard.writeText(text).then(() => toast("Copied to clipboard", "success"), () => toast("Copy failed - select the text manually", "warn"));
}

// ---------- items ----------
function itemForm(meetingId, item = null) {
  openModal(item ? "Edit action item" : "New action item", `
    <form id="item-form" class="space-y-3">
      <div><label class="text-sm font-medium">Title</label><input name="title" required minlength="3" class="${INPUT}" value="${esc(item?.title)}"></div>
      <div class="grid grid-cols-3 gap-3">
        <div><label class="text-sm font-medium">Owner</label><input name="owner" list="owners" class="${INPUT}" value="${esc(item?.owner)}">
          <datalist id="owners">${state.people.map((p) => `<option value="${esc(p)}">`).join("")}</datalist></div>
        <div><label class="text-sm font-medium">Due date</label><input type="date" name="due_date" class="${INPUT}" value="${item?.due_date || ""}"></div>
        <div><label class="text-sm font-medium">Priority</label><select name="priority" class="${INPUT}">
          ${["low", "medium", "high"].map((p) => `<option ${p === (item?.priority || "medium") ? "selected" : ""}>${p}</option>`).join("")}</select></div>
      </div>
      <div class="flex justify-end gap-2"><button type="button" class="${BTN_LIGHT}" onclick="closeModal()">Cancel</button>
        <button class="${BTN_PRIMARY}" id="item-save">Save</button></div>
    </form>`);
  document.getElementById("item-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { title: f.get("title"), owner: f.get("owner"), due_date: f.get("due_date") || null, priority: f.get("priority") };
    const ok = await withBusy(document.getElementById("item-save"), () =>
      item ? api("PATCH", `/api/items/${item.id}`, body) : api("POST", "/api/items", { ...body, meeting_id: meetingId }));
    if (ok) { closeModal(); toast("Item saved", "success"); route(); }
  };
}

async function setItemStatus(id, select) {
  const status = select.value;
  let outcome;
  if (status === "done" || status === "dropped") {
    outcome = prompt(`What was the outcome? (required to mark as ${status})`);
    if (!outcome || !outcome.trim()) { toast("An outcome is required to close an item.", "warn"); route(); return; }
  }
  try { await api("PATCH", `/api/items/${id}`, { status, outcome }); toast(`Item marked ${label(status)}`, "success"); } catch { /* toast shown */ }
  route();
}

async function itemHistory(id) {
  const i = await api("GET", `/api/items/${id}`);
  openModal("Item history", `
    <div class="text-sm">
      <div class="font-semibold text-base">${esc(i.title)}</div>
      <div class="flex flex-wrap gap-2 items-center mt-1 mb-3">${pill(i.status)} ${pill(i.priority)} ${itemFlags(i)} · ${esc(i.owner || "unassigned")} · ${dueCell(i)}</div>
      ${i.outcome ? `<p class="mb-3"><strong>Outcome:</strong> ${esc(i.outcome)}</p>` : ""}
      <h4 class="font-semibold mb-1">Carry-forward chain</h4>
      <ol class="flex flex-wrap gap-1 items-center mb-4">${i.chain.map((c, n) => `${n ? "&rarr;" : ""}
        <li><a href="#/meetings/${c.meeting_id}" onclick="closeModal()" class="text-xs px-2 py-1 rounded ${c.id === i.id ? "bg-indigo-100 text-indigo-800" : "bg-slate-100"}">#${c.id} ${esc(c.meeting_title)}</a></li>`).join("")}</ol>
      <h4 class="font-semibold mb-1">Full history</h4>
      <ol class="space-y-1.5 max-h-72 overflow-y-auto">${i.history.map((e) => `
        <li class="border-l-2 border-slate-200 pl-3"><span class="text-xs text-slate-400">${fmtDateTime(e.at + "Z")} · #${e.item_id}</span>
          <div><strong>${label(e.type)}</strong> ${e.from || e.to ? `${esc(e.from || "—")} &rarr; ${esc(e.to || "—")}` : ""} ${e.note ? `<span class="text-slate-500">${esc(e.note)}</span>` : ""}</div></li>`).join("")}</ol>
    </div>`);
}

async function renderItems() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const owner = params.get("owner") || "", status = params.get("status") || "", overdue = params.get("overdue") === "1";
  const q = new URLSearchParams({ ...(owner && { owner }), ...(status && { status }), ...(overdue && { overdue: "true" }) });
  const list = await api("GET", `/api/items?${q}`);
  const counts = Object.fromEntries(ITEM_STATUSES.map((s) => [s, list.filter((i) => i.status === s).length]));
  view.innerHTML = `
    <h1 class="text-2xl font-bold mb-1">Action items</h1>
    <p class="text-sm text-slate-500 mb-4">All live items across meetings. Carried-over items show their latest copy.</p>
    <div class="${CARD} mb-4 flex flex-wrap gap-3 items-end">
      <div><label class="text-xs text-slate-500">Owner</label><select id="f-owner" class="${INPUT}">
        <option value="">Anyone</option><option value="__none__" ${owner === "__none__" ? "selected" : ""}>Unassigned</option>
        ${state.people.map((p) => `<option ${p === owner ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></div>
      <div><label class="text-xs text-slate-500">Status</label><select id="f-status" class="${INPUT}"><option value="">Any</option>
        ${ITEM_STATUSES.map((s) => `<option value="${s}" ${s === status ? "selected" : ""}>${label(s)}</option>`).join("")}</select></div>
      <label class="flex items-center gap-2 text-sm pb-2"><input type="checkbox" id="f-overdue" ${overdue ? "checked" : ""}> Overdue only</label>
      <button class="${BTN_LIGHT}" onclick="location.hash='#/items'">Clear</button>
      <div class="ml-auto text-xs text-slate-500 pb-2">${ITEM_STATUSES.map((s) => `${label(s)}: <strong>${counts[s]}</strong>`).join(" · ")}</div>
    </div>
    <div class="${CARD}">${itemsTable(list, true, true)}</div>`;
  const apply = () => {
    const p = new URLSearchParams();
    const o = document.getElementById("f-owner").value, s = document.getElementById("f-status").value;
    if (o) p.set("owner", o); if (s) p.set("status", s); if (document.getElementById("f-overdue").checked) p.set("overdue", "1");
    location.hash = `#/items?${p}`;
  };
  ["f-owner", "f-status", "f-overdue"].forEach((id) => (document.getElementById(id).onchange = apply));
}

// ---------- knowledge base ----------
async function renderKB() {
  const q = new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
  const docs = await api("GET", `/api/kb?q=${encodeURIComponent(q)}`);
  view.innerHTML = `
    <div class="flex flex-wrap items-end justify-between gap-3 mb-4">
      <div><h1 class="text-2xl font-bold">Knowledge base</h1><p class="text-sm text-slate-500">Team docs that meetings and handovers link to.</p></div>
      <button class="${BTN_PRIMARY}" onclick="docForm()">+ New doc</button>
    </div>
    <form id="kb-search" class="mb-4"><input name="q" class="${INPUT}" placeholder="Search title, content or tags..." value="${esc(q)}"></form>
    <div class="grid md:grid-cols-2 gap-4">${docs.map((d) => `
      <div class="${CARD} cursor-pointer hover:border-indigo-300" onclick="viewDoc(${d.id})">
        <div class="font-semibold">${esc(d.title)}</div>
        <p class="text-sm text-slate-600 mt-1">${esc(d.snippet)}</p>
        <div class="mt-2 flex flex-wrap gap-1">${d.tags.map((t) => `<span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-100">#${esc(t)}</span>`).join("")}</div>
      </div>`).join("") || empty(q ? "No documents match your search." : "No documents yet.")}</div>`;
  document.getElementById("kb-search").onsubmit = (e) => { e.preventDefault(); location.hash = `#/kb?q=${encodeURIComponent(new FormData(e.target).get("q"))}`; };
}

async function viewDoc(id) {
  const d = await api("GET", `/api/kb/${id}`);
  openModal(d.title, `
    <div class="flex flex-wrap gap-1 mb-3">${d.tags.map((t) => `<span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-100">#${esc(t)}</span>`).join("")}</div>
    <p class="text-sm whitespace-pre-line">${esc(d.content)}</p>
    <h4 class="font-semibold text-sm mt-4 mb-1">Linked from</h4>
    ${d.linked_meetings.map((m) => `<a class="block text-sm text-indigo-700 hover:underline" onclick="closeModal()" href="#/meetings/${m.id}">${esc(m.title)}</a>`).join("") || empty("Not linked to any meeting yet.")}
    <div class="flex justify-end gap-2 mt-4">
      <button class="${BTN_LIGHT} text-rose-600" onclick="deleteDoc(${d.id})">Delete</button>
      <button class="${BTN_LIGHT}" onclick='docForm(${JSON.stringify(d).replace(/'/g, "&#39;")})'>Edit</button></div>`);
}

function docForm(doc = null) {
  openModal(doc ? "Edit doc" : "New doc", `
    <form id="doc-form" class="space-y-3">
      <div><label class="text-sm font-medium">Title</label><input name="title" required minlength="3" class="${INPUT}" value="${esc(doc?.title)}"></div>
      <div><label class="text-sm font-medium">Content</label><textarea name="content" rows="8" required minlength="10" class="${INPUT}">${esc(doc?.content)}</textarea></div>
      <div><label class="text-sm font-medium">Tags <span class="text-xs text-slate-400">(comma separated)</span></label><input name="tags" class="${INPUT}" value="${esc((doc?.tags || []).join(", "))}"></div>
      <div class="flex justify-end gap-2"><button type="button" class="${BTN_LIGHT}" onclick="closeModal()">Cancel</button><button class="${BTN_PRIMARY}" id="doc-save">Save</button></div>
    </form>`);
  document.getElementById("doc-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { title: f.get("title"), content: f.get("content"), tags: f.get("tags").split(",").map((t) => t.trim()).filter(Boolean) };
    const ok = await withBusy(document.getElementById("doc-save"), () => doc ? api("PUT", `/api/kb/${doc.id}`, body) : api("POST", "/api/kb", body));
    if (ok) { closeModal(); toast("Doc saved", "success"); route(); }
  };
}
async function deleteDoc(id) {
  if (!confirm("Delete this document?")) return;
  try { await api("DELETE", `/api/kb/${id}`); closeModal(); toast("Doc deleted", "success"); route(); } catch { /* toast shown */ }
}

// ---------- boot ----------
async function loadPeople() {
  state.people = await api("GET", "/api/people").catch(() => []);
  const sel = document.getElementById("viewer");
  state.viewer = store.get("viewer") || state.people[0] || "";
  sel.innerHTML = state.people.map((p) => `<option ${p === state.viewer ? "selected" : ""}>${esc(p)}</option>`).join("");
  sel.onchange = () => { state.viewer = sel.value; store.set("viewer", sel.value); route(); };
}

document.getElementById("reset-demo").onclick = async (e) => {
  if (!confirm("Reset all data back to the demo seed? Your changes will be lost.")) return;
  if (await withBusy(e.target, () => api("POST", "/api/demo/reset"))) { toast("Demo data reset", "success"); await loadPeople(); location.hash = "#/"; route(); }
};

(async function boot() {
  try { const s = await api("GET", "/api/ai/status"); setAiMode(s.mode, s.reason); } catch { setAiMode("basic"); }
  await loadPeople();
  route();
})();
