import { api } from "../api.js";
import { esc, guard, icon, modal, sevPill } from "../ui.js";

const PERM_LABEL = { brand: "Manage Brand Brain & guidelines", create: "Create content", edit: "Edit content / apply fixes / submit", review: "Run brand review",
  decide_fix: "Accept or reject findings", comment: "Comment", request_revision: "Request changes", endorse: "Endorse (manager review)", approve: "Final approve / reject" };

export async function render(view, ctx) {
  const s = ctx.status;
  const roles = ["admin", "creator", "manager", "approver"];
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
        <div class="card"><div class="card-h"><h2>${icon("lock", "sm")} Privacy & responsible AI</h2></div><div class="card-b ink2">
          <ul style="margin:0;padding-left:18px" class="kbd-list">
            <li><b>Disclosure:</b> with AI on, content text, images and retrieved guideline excerpts are sent to the configured AI provider (${esc(s.provider_label)}) for review. Free tiers (e.g. Gemini free) may let the provider use submitted data to improve its products, so use Confidential mode for sensitive material. Nothing is sent in rule-engine mode.</li>
            <li><b>Confidential content</b> (toggle in Content Studio) is never sent to any external service; only local rule checks run.</li>
            <li>Brand assets, uploads and the database are stored locally in <code>data/</code>.</li>
            <li><b>Human control:</b> AI never edits content. Fixes apply only when a person accepts them, as a new version; the original is kept.</li>
            <li>Approving content with open serious findings requires a recorded override reason.</li>
            <li>Every finding shows its source, evidence and confidence. AI findings without a valid citation are labelled <i>Ungrounded</i> and down-weighted.</li>
            <li>Guideline changes proposed by the system need an admin's approval and are versioned.</li>
          </ul></div></div>
      </div>
      <div class="stack">
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
  const b = view.querySelector("#reset");
  b.onclick = async () => {
    const ok = await modal({ title: "Reset all data?", body: `<p class="ink2">This deletes every content item, review, comment and Brand Brain change, then reloads the demo dataset. It cannot be undone.</p>`, actions: [{ label: "Cancel", value: false }, { label: "Reset", cls: "danger solid", value: true }] });
    if (ok && await guard(() => api("/api/admin/reset-demo", { method: "POST" }), "Demo data restored")) location.hash = "#/";
  };
}
