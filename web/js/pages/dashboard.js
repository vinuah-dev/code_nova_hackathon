import { api } from "../api.js";
import { CAT, ago, avatar, bars, esc, icon, ring, scoreBadge, band } from "../ui.js";

export async function render(view, ctx) {
  const [an, list] = await Promise.all([api("/api/analytics"), api("/api/content")]);
  const kpi = (ic, lbl, val, foot, href) => `<a class="card kpi" href="${href || "#/"}" style="color:inherit"><div class="lbl"><span class="ic">${icon(ic, "sm")}</span>${lbl}</div><div class="val">${val}</div><div class="foot">${foot}</div></a>`;
  const channels = Object.keys(an.by_channel);
  const cats = Object.keys(CAT);
  const maxCell = Math.max(1, ...channels.flatMap((ch) => cats.map((c) => an.by_channel[ch][c] || 0)));
  const shade = (n) => n ? `background:rgba(79,70,229,${0.12 + 0.75 * n / maxCell});color:${n / maxCell > 0.55 ? "#fff" : "var(--ink)"}` : "background:var(--surface-2);color:var(--muted)";
  const recent = [...list].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 6);

  view.innerHTML = `
    <div class="page-head"><div><h1>Good to see you, ${esc(ctx.me.name.split(" ")[0])}</h1>
      <div class="sub">Brand health for <b>Voltaro Mobility</b> <span class="tag-demo">fictional demo org</span>. Seeded submissions were scored by the real rule engine.</div></div>
      <div class="actions"><a class="btn" href="#/intelligence">${icon("sparkles", "sm")} Brand Intelligence</a><a class="btn primary" href="#/studio/new">${icon("plus", "sm")} Review new content</a></div></div>
    ${startCard()}
    <div class="grid g6" style="margin-bottom:16px">
      ${kpi("gauge", "Avg. compliance", an.overall_score == null ? "—" : `${Math.round(an.overall_score)}<small>/100</small>`, `${an.reviewed} reviewed items`, "#/reports")}
      ${kpi("files", "Submissions", an.submissions, `${an.ai_share}% reviewed with AI`, "#/studio")}
      ${kpi("alert-octagon", "Open violations", an.violations, "Not marked false positive", "#/reports")}
      ${kpi("flame", "High-risk content", an.high_risk.length, "Score < 60 or critical issue", "#/reports")}
      ${kpi("stamp", "Pending approvals", an.pending_approvals, "Waiting for an approver", "#/approvals")}
      ${kpi("shield-alert", "Integrity alerts", an.alerts, "Changed after approval", "#/approvals?tab=integrity")}
    </div>
    <div class="grid" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);margin-bottom:16px">
      <div class="card"><div class="card-h"><h2>Most violated guidelines</h2><span class="muted small right">open findings, latest version of each item</span></div>
        <div class="card-b">${bars(an.top_guidelines.map((g) => ({ label: `${g.id} · ${g.title}`, value: g.count })))}</div></div>
      <div class="card"><div class="card-h"><h2>Issues by dimension</h2></div>
        <div class="card-b">${bars(cats.map((c) => ({ label: CAT[c], value: an.by_category[c] || 0 })).sort((a, b) => b.value - a.value))}</div></div>
    </div>
    <div class="grid" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);margin-bottom:16px">
      <div class="card"><div class="card-h"><h2>Repeated mistakes by channel</h2><span class="muted small right">darker = more open findings</span></div>
        <div class="card-b" style="overflow-x:auto">${channels.length ? `<div class="heat" style="grid-template-columns:110px repeat(${cats.length},minmax(64px,1fr));min-width:520px">
          <div></div>${cats.map((c) => `<div class="h">${CAT[c]}</div>`).join("")}
          ${channels.map((ch) => `<div class="rh">${esc(ch)}</div>${cats.map((c) => { const n = an.by_channel[ch][c] || 0; return `<div class="c" style="${shade(n)}" title="${esc(ch)} · ${CAT[c]}: ${n}">${n || "·"}</div>`; }).join("")}`).join("")}
        </div>` : `<div class="empty">No data</div>`}</div></div>
      <div class="card"><div class="card-h"><h2>${icon("lightbulb", "sm")} Guideline recommendations</h2><a class="right small" href="#/intelligence">All insights →</a></div>
        <div class="card-b stack" style="gap:10px">${an.recommendations.length ? an.recommendations.map((r) => `<a href="#/intelligence" class="src" style="color:inherit;display:block"><span class="id">${esc(r.guideline_id)}</span> <b>${esc(r.title)}</b><div class="ink2 small" style="margin-top:3px">${esc(r.description)}</div></a>`).join("")
          : `<div class="empty small">${icon("check-circle-2")}<div>No recurring gaps detected yet.</div></div>`}</div></div>
    </div>
    <div class="grid g2">
      <div class="card"><div class="card-h"><h2>${icon("flame", "sm")} High-risk content</h2></div><div class="card-b">
        ${an.high_risk.length ? `<table class="t"><tbody>${an.high_risk.map((h) => `<tr class="click" data-href="#/reports/${h.id}"><td>${scoreBadge(h.score)}</td><td><b>${esc(h.title)}</b></td><td class="right">${h.critical ? `<span class="pill critical">${h.critical} critical</span>` : ""}</td></tr>`).join("")}</tbody></table>`
          : `<div class="empty small">Nothing high-risk right now.</div>`}</div></div>
      <div class="card"><div class="card-h"><h2>${icon("activity", "sm")} Recent activity</h2></div><div class="card-b">
        <table class="t"><tbody>${recent.map((c) => `<tr class="click" data-href="#/reports/${c.id}"><td>${scoreBadge(c.score)}</td><td><b>${esc(c.title)}</b><div class="small muted">${esc(c.channel || "")} · ${esc(c.owner || "")}</div></td><td class="small"><span class="pill st-${c.status}">${esc(c.status_label)}</span></td><td class="muted small">${ago(c.updated_at)}</td></tr>`).join("")}</tbody></table>
      </div></div>
    </div>`;
  view.onclick = async (e) => {
    const x = e.target.closest("[data-start-hide]");
    if (x) { try { localStorage.setItem(HIDE, "1"); } catch { /* private mode */ } x.closest(".start-card").remove(); return; }
    const t = e.target.closest("[data-try],[data-go-as]");
    if (t) {
      const { switchUser } = await import("../app.js");
      if (t.dataset.try) {
        // One click: become the Creator, load a sample with deliberate mistakes and run the review.
        if (!ctx.status.permissions.create.includes(ctx.me.role)) await switchUser("u-creator");
        location.hash = `#/studio/new?type=${t.dataset.try}&sample=1&run=1`;
      } else {
        await switchUser(t.dataset.goAs);
        location.hash = t.dataset.href;
      }
      return;
    }
    const tr = e.target.closest("tr[data-href]"); if (tr) location.hash = tr.dataset.href;
  };
}

const HIDE = "inkloom.start.hidden";
function startCard() {
  try { if (localStorage.getItem(HIDE)) return ""; } catch { /* show it */ }
  return `<div class="card start-card"><div class="card-h"><h2>${icon("rocket", "sm")} Start here: the whole workflow in 3 minutes</h2>
      <button class="btn ghost sm right" data-start-hide aria-label="Hide this guide">${icon("x", "sm")}</button></div>
    <div class="card-b"><div class="start-steps">
      <div class="start-step"><span class="n">1</span><b>Submit content for review</b><span class="small muted">Pick a sample with deliberate brand mistakes. It is reviewed against the Brand Brain straight away.</span>
        <div class="acts"><button class="btn sm primary" data-try="ad">${icon("megaphone", "sm")} Ad</button><button class="btn sm" data-try="email">${icon("mail", "sm")} Email</button>
        <button class="btn sm" data-try="post">${icon("image", "sm")} Poster</button><button class="btn sm" data-try="doc">${icon("file-text", "sm")} PDF</button></div></div>
      <div class="start-step"><span class="n">2</span><b>Read why, fix it, submit</b><span class="small muted">Every issue shows the rule it breaks and a suggested correction. Accept or reject each, apply the fixes, then submit for approval.</span></div>
      <div class="start-step"><span class="n">3</span><b>A human approves</b><span class="small muted">Switch to the Approver to approve or reject. The approved version is sealed with SHA-256.</span>
        <div class="acts"><button class="btn sm" data-go-as="u-approver" data-href="#/approvals">${icon("stamp", "sm")} Approve as Vikram</button></div></div>
    </div></div></div>`;
}
