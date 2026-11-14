import { api } from "../api.js";
import { ago, esc, guard, icon, modal, sevPill } from "../ui.js";
import { openFeedback } from "../feedback.js";

const PERM_LABEL = { brand: "Manage Brand Brain & guidelines", create: "Create content", edit: "Edit content / apply fixes / submit", review: "Run brand review",
  decide_fix: "Accept or reject findings", comment: "Comment", request_revision: "Request changes", endorse: "Endorse (manager review)", approve: "Final approve / reject" };

export async function render(view, ctx) {
  const s = ctx.status;
  const roles = ["admin", "creator", "manager", "approver"];
  const admin = s.permissions.brand.includes(ctx.me.role);
  const [fb, health] = await Promise.all([admin ? api("/api/feedback").catch(() => null) : null, api("/api/health").catch(() => null)]);
  view.innerHTML = `
    <div class="page-head"><div><h1>Settings</h1><div class="sub">AI configuration, privacy, roles and demo data.</div></div></div>
    <div class="grid g2" style="align-items:start">
      <div class="stack">
        <div class="card"><div class="card-h"><h2>${icon("sparkles", "sm")} AI review</h2></div><div class="card-b">
          <div class="row"><span class="dot ${s.ai_configured ? "on" : "off"}"></span><b>${s.ai_configured ? "Connected" : "Not configured: rule engine mode"}</b></div>
          <table class="t" style="margin-top:10px"><tbody>
            <tr><td class="muted">Provider</td><td>${esc(s.provider_label)} <span class="muted">(${esc(s.provider)}, called from the server only)</span></td></tr>
            <tr><td class="muted">Model</td><td><code>${esc(s.model)}</code></td></tr><tr><td class="muted">Effort</td><td><code>${esc(s.effort)}</code></td></tr>
            <tr><td class="muted">Grounding</td><td>BM25 retrieval over the Brand Brain; cited ids are validated server-side</td></tr>
            <tr><td class="muted">Fallback</td><td>If the AI is unavailable, the deterministic rule-engine report is shown and labelled</td></tr></tbody></table>
          ${s.ai_configured ? "" : `<div class="banner info" style="margin-top:12px">${icon("key-round", "sm")}<div>To enable AI review for free: get a key at <b>aistudio.google.com</b> (Google AI Studio), put <code>INKLOOM_AI_PROVIDER=gemini</code> and <code>GEMINI_API_KEY=...</code> in <code>.env</code> (or Vercel → Environment Variables) and restart. Claude works too with <code>ANTHROPIC_API_KEY</code>. Keys stay on the server and never reach the browser.</div></div>`}
        </div></div>
        ${healthCard(health)}
        <div class="card"><div class="card-h"><h2>${icon("lock", "sm")} Privacy & responsible AI</h2></div><div class="card-b ink2">
          <ul style="margin:0;padding-left:18px" class="kbd-list">
            <li><b>Disclosure:</b> with AI on, content text, images and retrieved guideline excerpts are sent to the configured AI provider (${esc(s.provider_label)}) for review. Free tiers (e.g. Gemini free) may let the provider use submitted data to improve its products, so use Confidential mode for sensitive material. Nothing is sent in rule-engine mode.</li>
            <li><b>Confidential content</b> (toggle in Content Studio) is never sent to any external service; only local rule checks run.</li>
            <li>Content, uploads and the Brand Brain are stored in the app's own database (Supabase Postgres on the live site, SQLite locally); API keys stay on the server.</li>
            <li><b>Human control:</b> AI never edits content. Fixes apply only when a person accepts them, as a new version; the original is kept.</li>
            <li>Approving content with open serious findings requires a recorded override reason.</li>
            <li>Every finding shows its source, evidence and confidence. AI findings without a valid citation are labelled <i>Ungrounded</i> and down-weighted.</li>
            <li>Guideline changes proposed by the system need an admin's approval and are versioned.</li>
          </ul></div></div>
      </div>
      <div class="stack">
        ${feedbackCard(fb, admin)}
        <div class="card"><div class="card-h"><h2>${icon("users", "sm")} Roles & permissions</h2></div><div class="card-b" style="overflow-x:auto">
          <table class="t keep"><thead><tr><th>Action</th>${roles.map((r) => `<th>${r}</th>`).join("")}</tr></thead><tbody>
          ${Object.entries(s.permissions).map(([p, rs]) => `<tr><td>${PERM_LABEL[p] || p}</td>${roles.map((r) => `<td>${rs.includes(r) ? `<span style="color:var(--good)">✓</span>` : `<span class="muted">—</span>`}</td>`).join("")}</tr>`).join("")}
          </tbody></table><p class="small muted">Each person signs in with their own account (top bar → Account). Roles are enforced by the server, not just hidden in the UI.</p></div></div>
        <div class="card"><div class="card-h"><h2>${icon("calculator", "sm")} Scoring model</h2></div><div class="card-b">
          <p><code>${esc(s.scoring.formula)}</code></p>
          <div class="row wrap">${Object.entries(s.scoring.penalties).map(([k, v]) => `${sevPill(k)} <span class="small">${v}</span>`).join("&nbsp;&nbsp;")}</div></div></div>
        <div class="card"><div class="card-h"><h2>${icon("database", "sm")} Demo data</h2></div><div class="card-b">
          <p class="ink2">Voltaro Mobility, its people, figures and certificates are fictional. Resetting restores the seeded Brand Brain and the 9 sample submissions.</p>
          <button class="btn danger" id="reset" ${s.permissions.brand.includes(ctx.me.role) ? "" : "disabled title='Admin only'"}>${icon("rotate-ccw", "sm")} Reset demo data</button></div></div>
      </div>
    </div>`;
  view.querySelector("#fb-open")?.addEventListener("click", openFeedback);
  const b = view.querySelector("#reset");
  b.onclick = async () => {
    const ok = await modal({ title: "Reset all data?", body: `<p class="ink2">This deletes every content item, review, comment and Brand Brain change, then reloads the demo dataset. It cannot be undone.</p>`, actions: [{ label: "Cancel", value: false }, { label: "Reset", cls: "danger solid", value: true }] });
    if (ok && await guard(() => api("/api/admin/reset-demo", { method: "POST" }), "Demo data restored")) location.hash = "#/";
  };
}

function feedbackCard(fb, admin) {
  const head = `<div class="card-h"><h2>${icon("message-square-heart", "sm")} User testing feedback</h2>
    <div class="right row" style="gap:6px"><button class="btn sm" id="fb-open">${icon("plus", "sm")} Give feedback</button>
    ${admin && fb?.summary.count ? `<a class="btn sm ghost" href="/api/feedback.csv" download>${icon("download", "sm")} CSV</a>` : ""}</div></div>`;
  if (!admin) return `<div class="card">${head}<div class="card-b ink2">Testing Inkloom? Use <b>Give feedback</b> (or the Feedback button in the corner) to tell us what you tried and how it went. Brand admins see the results here.</div></div>`;
  if (!fb) return `<div class="card">${head}<div class="card-b muted">Could not load feedback.</div></div>`;
  const s = fb.summary;
  if (!s.count) return `<div class="card">${head}<div class="card-b empty small">${icon("inbox")}<div>No feedback yet. Ask testers to press the Feedback button after each task.</div></div></div>`;
  return `<div class="card">${head}<div class="card-b">
    <div class="grid g4" style="gap:10px;margin-bottom:12px">
      <div class="kpi"><div class="lbl">Responses</div><div class="val">${s.count}</div></div>
      <div class="kpi"><div class="lbl">Testers</div><div class="val">${s.testers}</div></div>
      <div class="kpi"><div class="lbl">Avg. ease</div><div class="val">${s.avg_rating}<small>/5</small></div></div>
      <div class="kpi"><div class="lbl">Task completed</div><div class="val">${s.completed_share}<small>%</small></div></div>
    </div>
    <table class="t keep"><thead><tr><th>Task</th><th>Responses</th><th>Avg. ease</th><th>Completed</th></tr></thead><tbody>
      ${s.by_task.map((t) => `<tr><td>${esc(t.task)}</td><td>${t.count}</td><td>${t.avg}/5</td><td>${t.completed_share}%</td></tr>`).join("")}</tbody></table>
    <div class="section-lbl" style="margin-top:14px">Latest comments</div>
    <div class="stack" style="gap:8px">${fb.rows.filter((r) => r.comment).slice(0, 8).map((r) => `<div class="src"><b>${esc(r.tester || r.user_name)}</b>
      <span class="muted small">· ${esc(r.task)} · ${r.rating}/5 · ${esc(r.completed || "n/a")} · ${esc(r.device || "")} · ${ago(r.created_at)}</span>
      <div class="ink2" style="margin-top:3px">${esc(r.comment)}</div></div>`).join("") || `<div class="muted small">No comments yet.</div>`}</div>
  </div></div>`;
}

function healthCard(h) {
  if (!h) return "";
  const r = h.reviews;
  const okShare = r.ai_attempted ? Math.round((r.ai_ok / r.ai_attempted) * 100) : null;
  return `<div class="card"><div class="card-h"><h2>${icon("activity", "sm")} System health</h2><span class="pill ${okShare == null || okShare >= 80 ? "good" : "medium"} right">${okShare == null ? "No AI reviews yet" : `${okShare}% AI reviews succeeded`}</span></div><div class="card-b">
    <table class="t keep"><tbody>
      <tr><td class="muted">Database</td><td>${h.database.backend === "postgres" ? "PostgreSQL (Supabase)" : "SQLite (local)"} · ${h.database.round_trip_ms} ms round trip</td></tr>
      <tr><td class="muted">AI model</td><td>${esc(h.ai.provider)} <code>${esc(h.ai.model)}</code>${h.ai.fallback_model ? `, fallback <code>${esc(h.ai.fallback_model)}</code>` : ""}</td></tr>
      <tr><td class="muted">Time limit</td><td>${h.ai.budget_s} s per review, then the rule report is used</td></tr>
      <tr><td class="muted">Last ${r.recent} reviews</td><td>${r.ai_ok} with AI, ${r.fell_back_to_rules} fell back to rules${r.recent - r.ai_attempted ? `, ${r.recent - r.ai_attempted} rules only (confidential or no AI)` : ""}</td></tr>
      <tr><td class="muted">AI review time</td><td>${r.median_ai_s == null ? "—" : `median ${r.median_ai_s} s · 90th percentile ${r.p90_ai_s} s`}</td></tr>
      ${r.last_error ? `<tr><td class="muted">Last AI error</td><td class="small">${esc(r.last_error)}</td></tr>` : ""}
    </tbody></table></div></div>`;
}
