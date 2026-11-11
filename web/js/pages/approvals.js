import { api } from "../api.js";
import { ago, diffHtml, esc, guard, icon, icons, modal, scoreBadge, statusPill, toast } from "../ui.js";

export async function render(view, ctx) {
  const tab = new URLSearchParams(location.hash.split("?")[1] || "").get("tab") || "queue";
  const [list, integ] = await Promise.all([api("/api/content"), api("/api/integrity")]);
  const pending = list.filter((c) => c.status === "pending_approval");
  const revise = list.filter((c) => ["needs_revision", "modified_after_approval"].includes(c.status));
  const done = list.filter((c) => ["approved", "rejected"].includes(c.status));
  const role = ctx.me.role;
  const openAlerts = integ.alerts.filter((a) => !a.resolved);
  const T = (k, l, ic, n) => `<button class="${tab === k ? "active" : ""}" data-tab="${k}">${icon(ic, "sm")} ${l}${n != null ? ` <span class="n">${n}</span>` : ""}</button>`;

  view.innerHTML = `
    <div class="page-head"><div><h1>Approval Center</h1><div class="sub">AI recommends. Humans decide. Every decision is recorded, and approved content is sealed with SHA-256.</div></div>
      <div class="actions"><span class="pill indigo">${icon("user", "sm")} You: ${esc(ctx.me.title)}</span></div></div>
    <div class="tabs">${T("queue", "Approval queue", "inbox", pending.length)}${T("revise", "Needs revision", "undo-2", revise.length)}${T("done", "Decided", "check-check", done.length)}${T("integrity", "Integrity Shield", "shield-check", openAlerts.length || null)}</div>
    <div id="pane"></div>`;
  const pane = view.querySelector("#pane");

  if (tab === "integrity") {
    pane.innerHTML = `
      <div class="grid g3" style="margin-bottom:16px">
        <div class="card kpi"><div class="lbl"><span class="ic">${icon("lock", "sm")}</span>Sealed approvals</div><div class="val">${integ.protected.length}</div><div class="foot">SHA-256 recorded at approval</div></div>
        <div class="card kpi"><div class="lbl"><span class="ic">${icon("shield-check", "sm")}</span>Verified intact</div><div class="val">${integ.results.filter((r) => r.status === "intact").length}</div><div class="foot">Checked just now</div></div>
        <div class="card kpi"><div class="lbl"><span class="ic" style="background:var(--critical-soft);color:var(--critical)">${icon("shield-alert", "sm")}</span>Open alerts</div><div class="val">${openAlerts.length}</div><div class="foot">Changed after approval</div></div>
      </div>
      <div class="card" style="margin-bottom:16px"><div class="card-h"><h2>Protected content</h2><button class="btn sm right" data-verify-all>${icon("refresh-cw", "sm")} Verify all</button></div><div class="card-b">
        <table class="t"><thead><tr><th>Content</th><th>Approved version</th><th>SHA-256 at approval</th><th>Status</th><th></th></tr></thead><tbody>
        ${integ.protected.map((p) => { const r = integ.results.find((x) => x.content_id === p.id); return `<tr><td><a href="#/reports/${p.id}"><b>${esc(p.title)}</b></a></td><td>v${p.approved_version}</td>
          <td><span class="hash" title="${p.approved_hash}">${p.approved_hash.slice(0, 24)}…</span></td>
          <td>${r?.status === "intact" ? `<span class="pill good">${icon("shield-check", "sm")} Intact</span>` : `<span class="pill critical">${icon("shield-alert", "sm")} Modified</span>`}</td>
          <td>${role === "admin" && p.status === "approved" ? `<button class="btn sm ghost" data-tamper="${p.id}" title="Demo: edit the database directly, bypassing the app">${icon("bug", "sm")} Simulate tampering</button>` : ""}</td></tr>`; }).join("")}
        </tbody></table>${integ.protected.length ? "" : `<div class="empty">Nothing approved yet.</div>`}
        <p class="small muted">The fingerprint covers title, text, alt text and the SHA-256 of every attached file. "Simulate tampering" (admin, demo only) edits the stored text directly in the database, the way an out-of-band change would.</p></div></div>
      <div class="card"><div class="card-h"><h2>${icon("siren", "sm")} Integrity alerts</h2></div><div class="card-b stack" style="gap:12px">
        ${integ.alerts.length ? integ.alerts.map((a) => `<div class="finding ${a.resolved ? "" : "critical"}"><div class="row"><b>${esc(a.title)}</b>${a.resolved ? `<span class="pill good">Resolved by re-approval</span>` : `<span class="pill critical">Open</span>`}<span class="muted small right">${ago(a.detected_at)}</span></div>
          <div class="small muted" style="margin:6px 0">Expected <span class="hash">${a.expected.slice(0, 16)}…</span> → found <span class="hash">${a.actual.slice(0, 16)}…</span></div>
          ${a.diff?.body?.some((d) => d.op !== "equal") ? `<div class="section-lbl">What changed (body)</div><div class="doc" style="font-size:14px">${diffHtml(a.diff.body)}</div>` : ""}
          ${a.diff?.alt_text?.some((d) => d.op !== "equal") ? `<div class="section-lbl" style="margin-top:8px">What changed (alt text)</div><div class="doc" style="font-size:14px">${diffHtml(a.diff.alt_text)}</div>` : ""}
          <div class="f-actions"><a class="btn sm" href="#/reports/${a.content_id}">${icon("arrow-right", "sm")} Open for re-review</a></div></div>`).join("")
          : `<div class="empty">${icon("shield-check")}<div>No integrity alerts. All approved content matches its seal.</div></div>`}
      </div></div>`;
  } else {
    const rows = tab === "queue" ? pending : tab === "revise" ? revise : done;
    pane.innerHTML = `${tab === "queue" ? `<div class="banner info" style="margin-bottom:14px">${icon("info", "sm")}<div>${role === "approver" || role === "admin" ? "As an approver you give the final decision. Open an item to see the report, evidence and history." : role === "manager" ? "As a manager you can comment, endorse or request changes. Final approval belongs to the approver role." : "Switch to Meera (Manager) or Vikram (Approver) in the top bar to act on this queue."}</div></div>` : ""}
      <div class="card"><table class="t"><thead><tr><th>Score</th><th>Content</th><th>Status</th><th>Open serious</th><th>Owner</th><th>Updated</th><th></th></tr></thead><tbody>
      ${rows.map((c) => `<tr class="click" data-href="#/reports/${c.id}"><td>${scoreBadge(c.score)}</td><td><b>${esc(c.title)}</b> ${c.is_demo ? `<span class="tag-demo">demo</span>` : ""}<div class="small muted">${esc(c.channel || "")} · v${c.current_version}</div></td>
        <td>${statusPill(c.status, c.status_label)}</td><td>${c.critical ? `<span class="pill high">${c.critical}</span>` : `<span class="pill good">0</span>`}</td><td>${esc(c.owner || "")}</td><td class="small muted">${ago(c.updated_at)}</td>
        <td class="right">${icon("chevron-right", "sm")}</td></tr>`).join("")}
      </tbody></table>${rows.length ? "" : `<div class="empty">${icon("inbox")}<div>Nothing here.</div></div>`}</div>`;
  }
  view.onclick = async (e) => {
    const t = e.target.closest("[data-tab],[data-href],[data-verify-all],[data-tamper]");
    if (!t) return;
    if (t.dataset.tab) { location.hash = `#/approvals?tab=${t.dataset.tab}`; return; }
    if (t.dataset.href) { location.hash = t.dataset.href; return; }
    if (t.hasAttribute("data-verify-all")) {
      const r = await guard(() => api("/api/integrity"));
      if (r) { const bad = r.results.filter((x) => x.status !== "intact").length; toast(bad ? `${bad} item(s) changed after approval` : "All approved content verified intact", bad ? "err" : "ok"); render(view, ctx); }
      return;
    }
    if (t.dataset.tamper) {
      const ok = await modal({ title: "Simulate unauthorised change (demo)", body: `<p class="ink2">This writes directly to the database, bypassing Inkloom's workflow, the way someone might edit an approved post in a CMS after sign-off. It appends: <i>"Now with a guaranteed 200 km range!"</i></p><p class="small muted">Then click <b>Verify all</b> to see the Integrity Shield catch it.</p>`,
        actions: [{ label: "Cancel", value: false }, { label: "Tamper with it", cls: "danger solid", value: true }] });
      if (ok && await guard(() => api(`/api/content/${t.dataset.tamper}/simulate-tamper`, { method: "POST", body: {} }), "Database row changed behind the app's back")) render(view, ctx);
    }
  };
  icons();
}
