import { api } from "../api.js";
import { $, CAT, diffHtml, dims, esc, guard, icon, icons, modal, ring, sevPill } from "../ui.js";

const SAMPLE_A = "The Voltaro Glide S1 offers 120 km of certified range (IDC) and charges 0–80% in 50 minutes with the Voltaro FastCharger. Book a test ride at your nearest Voltaro Experience Centre.";
const SAMPLE_B = "The Glide-S1 offers 150 km of range — the best in India!! Charges in 60 minutes. Click here to grab this crazy deal.";

export async function render(view, ctx) {
  const qs = new URLSearchParams(location.hash.split("?")[1] || "");
  const insights = await api("/api/insights");
  const admin = ctx.status.permissions.brand.includes(ctx.me.role);
  const open = insights.filter((i) => i.status === "open");
  view.innerHTML = `
    <div class="page-head"><div><h1>Brand Intelligence</h1><div class="sub">Learn from repeated mistakes, and see how an edit changes brand identity before it ships.</div></div></div>
    <div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:start">
      <div class="stack">
        <div class="card"><div class="card-h"><h2>${icon("lightbulb", "sm")} Guideline Gap Intelligence</h2><span class="pill indigo right">${open.length} open</span></div>
          <div class="card-b"><p class="ink2" style="margin-top:0">When the same mistake appears in 3 or more different submissions, the guideline is probably unclear, not just the writer. Inkloom proposes a clearer rule; an admin must approve it before it becomes official.</p>
          <div class="stack" style="gap:12px">${insights.length ? insights.map((i) => insight(i, admin)).join("") : `<div class="empty">${icon("check-circle-2")}<div>No recurring gaps yet.</div></div>`}</div></div></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-h"><h2>${icon("dna", "sm")} Brand DNA Simulator</h2></div><div class="card-b">
          <p class="ink2" style="margin-top:0">Paste an original and a modified version. Both are scored by the same engine, and every point of difference is traced to a finding.</p>
          <div class="field"><label class="f">Original</label><textarea class="textarea" id="da" style="min-height:90px">${esc(SAMPLE_A)}</textarea></div>
          <div class="field"><label class="f">Modified</label><textarea class="textarea" id="db" style="min-height:90px">${esc(SAMPLE_B)}</textarea></div>
          <div class="row">${ctx.status.ai_configured ? `<label class="toggle small"><input type="checkbox" id="dai"><span class="sl"></span>Include Claude review (slower)</label>` : `<span class="small muted">${icon("cpu", "sm")} Rule engine scoring</span>`}
            <button class="btn primary right" id="run">${icon("play", "sm")} Compare</button></div>
        </div></div>
        <div id="dna"></div>
      </div>
    </div>`;
  $("#run").onclick = async () => {
    $("#run").disabled = true;
    $("#dna").innerHTML = `<div class="card"><div class="card-b row"><span class="spin"></span> Scoring both versions…</div></div>`;
    const r = await guard(() => api("/api/dna", { method: "POST", body: { original: { body: $("#da").value }, modified: { body: $("#db").value }, use_ai: $("#dai")?.checked } }));
    $("#run").disabled = false;
    $("#dna").innerHTML = r ? result(r, "Original", "Modified") : "";
    icons();
  };
  if (qs.get("dna")) {
    const r = await guard(() => api(`/api/content/${qs.get("dna")}/dna?a=${qs.get("a")}&b=${qs.get("b")}`));
    if (r) { $("#dna").innerHTML = result(r, `Version ${qs.get("a")}`, `Version ${qs.get("b")}`); $("#dna").scrollIntoView({ behavior: "smooth" }); }
  }
  view.onclick = async (e) => {
    const t = e.target.closest("[data-propose],[data-approve],[data-dismiss]");
    if (!t) return;
    if (t.dataset.propose) { if (await guard(() => api(`/api/insights/${t.dataset.propose}/propose`, { method: "POST" }), "Proposal ready for review")) render(view, ctx); return; }
    if (t.dataset.dismiss) { if (await guard(() => api(`/api/insights/${t.dataset.dismiss}/decide`, { method: "POST", body: { decision: "dismissed" } }), "Dismissed")) render(view, ctx); return; }
    if (t.dataset.approve) {
      const i = insights.find((x) => String(x.id) === t.dataset.approve);
      const text = await modal({ title: `Update ${esc(i.guideline_id)}: ${esc(i.guideline_title)}`, wide: true,
        body: `<div class="compare"><div><div class="section-lbl">Current</div><div class="src" style="white-space:pre-wrap">${esc(i.guideline_body)}</div></div>
          <div><div class="section-lbl">Proposed (edit before approving)</div><textarea class="textarea" id="pt" style="min-height:220px">${esc(i.suggestion?.text || "")}</textarea></div></div>
          <p class="small muted">${esc(i.suggestion?.why || "")} The change is versioned in the guideline history.</p>`,
        actions: [{ label: "Cancel", value: null }, { label: "Approve & publish guideline", cls: "good", onClick: (ov) => $("#pt", ov).value.trim() || false }] });
      if (text && await guard(() => api(`/api/insights/${i.id}/decide`, { method: "POST", body: { decision: "approved", text } }), "Guideline updated in the Brand Brain")) render(view, ctx);
    }
  };
  icons();
}

function insight(i, admin) {
  const st = { open: "", approved: `<span class="pill good">Guideline updated</span>`, dismissed: `<span class="pill">Dismissed</span>` }[i.status];
  return `<div class="finding ${i.status === "open" ? "high" : ""}"><div class="row wrap"><span class="src id">${esc(i.guideline_id)}</span><b>${esc(i.title)}</b>${st}<span class="pill indigo right">${i.count} submissions</span></div>
    <p class="expl">${esc(i.description)}</p>
    ${i.examples.length ? `<div class="row wrap" style="gap:4px;margin-top:6px">${i.examples.slice(0, 6).map((x) => `<span class="quote">${esc(x)}</span>`).join("")}</div>` : ""}
    ${i.suggestion ? `<details class="ev" ${i.status === "open" ? "open" : ""}><summary>${icon("wand-2", "sm")} Proposed guideline (${i.suggestion.engine === "ai" ? "Claude" : "template"})</summary><div class="src" style="white-space:pre-wrap">${esc(i.suggestion.text)}</div></details>` : ""}
    ${i.status === "open" && admin ? `<div class="f-actions">${i.suggestion ? `<button class="btn sm good" data-approve="${i.id}">${icon("check", "sm")} Review & approve</button>` : `<button class="btn sm primary" data-propose="${i.id}">${icon("sparkles", "sm")} Propose clearer guideline</button>`}
      <button class="btn sm ghost" data-dismiss="${i.id}">Dismiss</button></div>` : i.status === "open" ? `<div class="small muted" style="margin-top:8px">Only a Brand Admin can change guidelines.</div>` : ""}
  </div>`;
}

function result(r, la, lb) {
  const d = Math.round(r.delta);
  const list = (arr, empty) => arr.length ? arr.map((f) => `<div class="row" style="margin:4px 0">${sevPill(f.severity)}<span class="small"><b>${esc(f.title)}</b> <span class="quote">${esc(f.quote || "")}</span> <span class="muted">${CAT[f.category] || ""}</span></span></div>`).join("") : `<div class="muted small">${empty}</div>`;
  return `<div class="card"><div class="card-b">
    <div class="compare" style="align-items:center;text-align:center">
      <div><div class="muted small" style="margin-bottom:6px">${la}</div>${ring(r.original.score, 112)}</div>
      <div><div class="muted small" style="margin-bottom:6px">${lb}</div>${ring(r.modified.score, 112)}</div>
    </div>
    <div style="text-align:center;margin:10px 0"><span class="big-delta" style="color:${d >= 0 ? "var(--good)" : "var(--critical)"}">${d >= 0 ? "+" : ""}${d}</span> <span class="muted">brand compliance points</span></div>
    <div class="hr"></div><div class="section-lbl">Which part of the brand identity moved</div>${dims(r.modified.dimensions, r.original.dimensions)}
    <div class="hr"></div><div class="compare">
      <div><div class="section-lbl" style="color:var(--critical)">${icon("trending-down", "sm")} Introduced (${r.introduced.length})</div>${list(r.introduced, "Nothing new")}</div>
      <div><div class="section-lbl" style="color:var(--good)">${icon("trending-up", "sm")} Resolved (${r.resolved.length})</div>${list(r.resolved, "Nothing resolved")}</div>
    </div>
    <div class="hr"></div><div class="section-lbl">Text changes</div><div class="doc" style="font-size:14px">${diffHtml(r.diff)}</div>
  </div></div>`;
}
