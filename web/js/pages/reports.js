import { api } from "../api.js";
import { ago, esc, icon, scoreBadge, statusPill } from "../ui.js";

let filter = "all";

export async function render(view) {
  const list = (await api("/api/content")).filter((c) => c.analysis_id);
  const show = list.filter((c) => filter === "all" || (filter === "risk" && c.score < 60) || (filter === "attn" && c.score >= 60 && c.score < 85) || (filter === "ready" && c.score >= 85));
  view.innerHTML = `
    <div class="page-head"><div><h1>Compliance Reports</h1><div class="sub">Every review, its score, and what is still open.</div></div></div>
    <div class="chips" style="margin-bottom:14px">
      ${[["all", "All"], ["risk", "High risk (<60)"], ["attn", "Needs attention"], ["ready", "Ready (≥85)"]].map(([k, l]) => `<button class="chip ${filter === k ? "active" : ""}" data-f="${k}">${l}</button>`).join("")}
    </div>
    <div class="card"><table class="t"><thead><tr><th>Score</th><th>Content</th><th>Status</th><th>Engine</th><th>Findings</th><th>Reviewed</th></tr></thead><tbody>
    ${show.sort((a, b) => a.score - b.score).map((c) => `<tr class="click" data-href="#/reports/${c.id}">
      <td>${scoreBadge(c.score)}</td><td><b>${esc(c.title)}</b> ${c.is_demo ? `<span class="tag-demo">demo</span>` : ""}<div class="small muted">${esc(c.channel || "")} · v${c.current_version} · ${esc(c.owner || "")}</div></td>
      <td>${statusPill(c.status, c.status_label)}</td>
      <td>${c.mode === "ai+rules" ? `<span class="pill violet">${icon("sparkles", "sm")} AI + rules</span>` : `<span class="pill">${icon("cpu", "sm")} Rules</span>`}</td>
      <td>${c.issues}${c.critical ? ` <span class="pill high">${c.critical} serious</span>` : ""}</td><td class="small muted">${ago(c.updated_at)}</td></tr>`).join("")}
    </tbody></table>${show.length ? "" : `<div class="empty">${icon("search-x")}<div>No reports match.</div></div>`}</div>`;
  view.onclick = (e) => {
    const f = e.target.closest("[data-f]");
    if (f) { filter = f.dataset.f; render(view); return; }
    const tr = e.target.closest("tr[data-href]");
    if (tr) location.hash = tr.dataset.href;
  };
}
