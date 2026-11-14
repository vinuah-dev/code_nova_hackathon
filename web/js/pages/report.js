import { api } from "../api.js";
import { crumbs } from "../app.js";
import {
  $, $$, CAT, CAT_ICON, SEV, ago, avatar, band, diffHtml, dims, esc, guard, icon, icons, modal, ring,
  scoreBadge, sevPill, statusPill, toast,
} from "../ui.js";

const can = (ctx, perm) => (ctx.status.permissions[perm] || []).includes(ctx.me.role);
let state = { filter: "all", focus: null, preview: false };

export async function render(view, ctx, { id }) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const vq = params.get("v");
  const [rep, detail] = await Promise.all([
    api(`/api/content/${id}/report${vq ? `?version=${vq}` : ""}`),
    api(`/api/content/${id}`),
  ]);
  state = { ...state, focus: null };
  const c = rep.content, v = rep.version, a = rep.analysis;
  const isCurrent = v.number === c.current_version;
  crumbs(`Voltaro Mobility <span>/</span> <a href="#/reports">Compliance Reports</a> <span>/</span> <b>${esc(c.title)}</b>`);

  view.innerHTML = `
    <div class="page-head">
      <div style="min-width:0">
        <div class="row wrap" style="gap:10px">
          <h1>${esc(c.title)}</h1>${statusPill(c.status, c.status_label)}
          ${c.is_demo ? `<span class="tag-demo" title="Seeded fictional demo submission">Demo data</span>` : ""}
          ${c.confidential ? `<span class="pill" title="Never sent to external AI">${icon("lock", "sm")} Confidential</span>` : ""}
        </div>
        <div class="sub row wrap">${esc(c.channel || "")} · by ${esc(c.owner || "")} ·
          <select class="select" id="ver" style="width:auto;padding:3px 8px;font-size:12.5px">
            ${detail.versions.map((x) => `<option value="${x.number}" ${x.number === v.number ? "selected" : ""}>Version ${x.number}${x.number === c.current_version ? " (current)" : ""} — ${esc(x.note || "")}</option>`).join("")}
          </select>
          ${c.approved_version ? `<span class="pill good">${icon("shield-check", "sm")} v${c.approved_version} approved</span>` : ""}
        </div>
      </div>
      <div class="actions" id="actions"></div>
    </div>
    ${flow(c.status)}
    ${isCurrent ? nextStep(ctx, rep) : ""}
    ${!isCurrent ? `<div class="banner warn" style="margin:14px 0">${icon("history", "sm")}<div>You are viewing an older version. Actions apply to the current version (v${c.current_version}).</div></div>` : ""}
    ${detail.alerts.some((x) => !x.resolved) ? `<div class="banner bad" style="margin:14px 0">${icon("shield-alert", "sm")}<div><b>Integrity Shield:</b> this content changed after approval. It no longer matches the SHA-256 recorded when it was approved and must be reviewed again. <a href="#/approvals?tab=integrity">See what changed</a></div></div>` : ""}
    <div style="height:14px"></div>
    ${a ? `<div class="split">
      <div class="stack">${contentCard(rep, a)}${activityCard(detail)}</div>
      <div class="stack">${scoreCard(rep, a)}${findingsCard(a, ctx)}</div>
    </div>` : emptyCard(ctx, c)}
  `;
  paintActions(ctx, rep, detail, isCurrent);
  wire(view, ctx, rep, detail);
  $("[data-print]")?.addEventListener("click", () => window.print());
  $("#next", view)?.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-as]");
    if (!b) return;
    const { switchUser } = await import("../app.js");
    await switchUser(b.dataset.as);
  });
  icons();
  if (params.get("run") && !a && can(ctx, "review")) {
    history.replaceState(null, "", `#/reports/${id}`);
    runReview(id);
  }
}

// One plain sentence telling whoever is looking what to do next, so the workflow needs no walkthrough.
const ROLE_USER = { creator: ["u-creator", "Rohan (Creator)"], manager: ["u-manager", "Meera (Manager)"], approver: ["u-approver", "Vikram (Approver)"] };
function nextStep(ctx, rep) {
  const c = rep.content, a = rep.analysis, st = c.status, role = ctx.me.role;
  const sw = (r) => role === r ? "" : `<button class="btn sm" data-as="${ROLE_USER[r][0]}">${icon("repeat", "sm")} Switch to ${ROLE_USER[r][1]}</button>`;
  let title = "", text = "", acts = "";
  if (!a) {
    title = "Next: run the brand review";
    text = "Checks the content against the Brand Brain and explains every issue with the rule it breaks.";
  } else if (["draft", "ai_review", "needs_revision", "modified_after_approval"].includes(st)) {
    const open = a.findings.filter((f) => !f.decision).length;
    const accepted = a.findings.filter((f) => f.decision === "accepted" && f.suggestion?.replacement != null && (f.start != null || f.target === "alt_text")).length;
    if (!can(ctx, "edit")) {
      title = "Waiting for the creator";
      text = "The creator accepts or rejects each finding, applies the fixes and submits for approval.";
      acts = sw("creator");
    } else if (open) {
      title = `Step 1 of 3: decide on each finding (${open} left)`;
      text = "Accept fix to use the suggested correction, or Reject if it is a false positive. Accept all text fixes does it in one click.";
    } else if (accepted) {
      title = "Step 2 of 3: apply the accepted fixes";
      text = `Apply ${accepted} accepted fix${accepted > 1 ? "es" : ""} (button above) to create a corrected new version. The original is kept.`;
    } else {
      title = "Step 3 of 3: submit for approval";
      text = "Send it to the manager and approver. A person always makes the final decision.";
    }
  } else if (st === "pending_approval") {
    if (can(ctx, "approve")) { title = "Your decision: approve or reject"; text = "Approving seals this version with SHA-256. Approving with serious open issues needs a written reason."; }
    else if (can(ctx, "endorse")) { title = "Endorse or request changes"; text = "Final approval belongs to the Approver."; acts = sw("approver"); }
    else { title = "Waiting for approval"; text = "A manager can endorse it and an approver gives the final sign-off."; acts = sw("manager") + sw("approver"); }
  } else if (st === "approved") {
    title = "Approved and sealed";
    text = "The approved version has a SHA-256 seal. Edit it and the Integrity Shield flags the change as Modified after approval.";
  } else if (st === "rejected") {
    title = "Rejected";
    text = "Edit the content and run the review again to resubmit.";
    acts = can(ctx, "edit") ? "" : sw("creator");
  }
  return title ? `<div class="next-step" id="next"><div class="ic">${icon("compass", "sm")}</div><div><b>${title}</b><div class="small">${text}</div>${acts ? `<div class="acts">${acts}</div>` : ""}</div></div>` : "";
}

function flow(status) {
  const steps = [["draft", "Draft"], ["ai_review", "AI Review"], ["needs_revision", "Needs Revision"], ["pending_approval", "Pending Approval"], ["approved", "Approved / Rejected"]];
  const order = { draft: 0, ai_review: 1, needs_revision: 2, pending_approval: 3, approved: 4, rejected: 4, modified_after_approval: 1 };
  const cur = order[status] ?? 0;
  return `<div class="flow">${steps.map(([k, l], i) => {
    let cls = i < cur ? "done" : i === cur ? "now" : "";
    if (i === 4 && status === "rejected") { cls = "bad"; l = "Rejected"; }
    if (i === 4 && status === "approved") l = "Approved";
    if (k === "needs_revision" && status !== "needs_revision" && i < cur) cls = "";
    return `<span class="step ${cls}">${l}</span>${i < steps.length - 1 ? `<span class="sep">›</span>` : ""}`;
  }).join("")}${status === "modified_after_approval" ? `<span class="step bad" style="margin-left:8px">${icon("shield-alert", "sm")} Modified after approval</span>` : ""}</div>`;
}

function emptyCard(ctx, c) {
  return `<div class="card"><div class="card-b empty" style="padding:56px 20px">
    ${icon("scan-search")}<h2 style="color:var(--ink);margin:6px 0">Not reviewed yet</h2>
    <p>Run a brand review to check this content against the Brand Brain: guidelines, approved facts, claims, terminology, palette and logo.</p>
    ${can(ctx, "review") ? `<button class="btn primary" data-run>${icon("sparkles", "sm")} Run brand review</button>` : `<p class="small">Your role cannot run reviews.</p>`}
  </div></div>`;
}

// ---------------------------------------------------------------- content + highlights
function highlight(text, findings, target) {
  const spans = findings.filter((f) => f.target === target && f.start != null && f.end > f.start)
    .sort((x, y) => x.start - y.start || SEV.indexOf(x.severity) - SEV.indexOf(y.severity));
  let out = "", pos = 0;
  for (const f of spans) {
    if (f.start < pos) continue;
    out += esc(text.slice(pos, f.start));
    const cls = f.decision === "accepted" ? "accepted" : f.decision === "rejected" ? "rejected" : f.severity;
    out += `<mark class="${cls}" data-f="${f.id}" title="${esc(f.title)}">${esc(text.slice(f.start, f.end))}</mark>`;
    pos = f.end;
  }
  return out + esc(text.slice(pos));
}

function revised(text, findings, target) {
  const edits = findings.filter((f) => f.decision === "accepted" && f.target === target && f.start != null && f.suggestion && f.suggestion.replacement != null)
    .sort((x, y) => y.start - x.start);
  let s = text, last = Infinity, html = null;
  const parts = [];
  for (const f of edits) {
    if (f.end > last) continue;
    parts.unshift({ start: f.start, end: f.end, rep: f.suggestion.replacement });
    last = f.start;
  }
  html = ""; let pos = 0;
  for (const p of parts) {
    html += esc(text.slice(pos, p.start)) + `<span class="del">${esc(text.slice(p.start, p.end))}</span>` + (p.rep ? `<span class="ins">${esc(p.rep)}</span>` : "");
    pos = p.end;
  }
  return { html: html + esc(text.slice(pos)), count: parts.length, s };
}

function contentCard(rep, a) {
  const v = rep.version, f = a.findings;
  const imgs = v.attachments.filter((x) => (x.mime || "").startsWith("image/"));
  const rv = revised(v.body || "", f, "body");
  const badHex = new Set(f.filter((x) => x.category === "visual" && x.title === "Unapproved brand colour" && x.decision !== "rejected").map((x) => x.quote.toUpperCase()));
  return `<div class="card">
    <div class="card-h"><h2>${icon("file-text", "sm")} Content</h2>
      <div class="right">${rv.count ? `<label class="toggle small"><input type="checkbox" id="pv" ${state.preview ? "checked" : ""}><span class="sl"></span>Preview ${rv.count} accepted fix${rv.count > 1 ? "es" : ""}</label>` : ""}</div></div>
    <div class="card-b">
      <div class="section-lbl">${icon("align-left", "sm")} Caption / body</div>
      <div class="doc" id="doc">${state.preview && rv.count ? rv.html : highlight(v.body || "", f, "body") || `<span class="muted">No text</span>`}</div>
      <div class="hr"></div>
      <div class="section-lbl">${icon("image", "sm")} Alt text</div>
      <div class="doc" style="font-size:14px">${v.alt_text ? highlight(v.alt_text, f, "alt_text") : `<mark class="${f.some((x) => x.target === "alt_text" && x.decision !== "rejected") ? "high" : "low"}" data-f="${(f.find((x) => x.target === "alt_text") || {}).id || ""}"><i>No alt text provided</i></mark>`}</div>
      ${rep.pdf_text ? `<div class="hr"></div><details><summary class="section-lbl" style="cursor:pointer">${icon("file-type-2", "sm")} Text extracted from PDF (${rep.pdf_text.length} chars)</summary>
        <div class="doc" style="font-size:13px;max-height:340px;overflow:auto">${highlight(rep.pdf_text, f, "pdf")}</div></details>` : ""}
      ${imgs.length ? `<div class="hr"></div><div class="section-lbl">${icon("images", "sm")} Visual assets</div><div class="imgs">${imgs.map((im) => {
        const iss = f.filter((x) => x.target === `image:${im.id}` && x.decision !== "rejected");
        const worst = SEV.find((s) => iss.some((x) => x.severity === s));
        return `<div class="img-card"><a href="${im.url}" target="_blank" rel="noopener"><img src="${im.url}" alt="${esc(im.name)}"></a>
          ${worst ? `<span class="flag">${sevPill(worst)}</span>` : `<span class="flag pill good">${icon("check", "sm")}</span>`}
          <div class="cap">${icon(im.kind === "logo" ? "badge" : "image", "sm")}<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(im.name)}</span><span class="muted right">${im.kind}</span></div>
          ${im.meta?.palette ? `<div class="swatches">${im.meta.palette.map((p) => `<span class="sw ${badHex.has(p.hex.toUpperCase()) ? "bad" : ""}" style="background:${p.hex}" title="${p.hex} · ${Math.round(p.share * 100)}%"></span>`).join("")}</div>` : ""}
          ${iss.length ? `<div class="small" style="padding:0 10px 10px">${iss.map((x) => `<a href="#" data-goto="${x.id}">${esc(x.title)}</a>`).join("<br>")}</div>` : ""}
        </div>`;
      }).join("")}</div>` : ""}
    </div></div>`;
}

// ---------------------------------------------------------------- score
function scoreCard(rep, a) {
  const prev = rep.previous;
  const d = prev ? Math.round(a.score - prev.score) : null;
  const aiMode = a.mode === "ai+rules";
  return `<div class="card"><div class="card-b">
    <div class="score-card">${ring(a.score)}
      <div>
        <div class="row wrap"><h2>${band(a.score)}</h2>
          ${d != null && d !== 0 ? `<span class="delta ${d > 0 ? "up" : "down"}">${d > 0 ? "▲ +" : "▼ "}${d} vs v${prev.version}</span>` : ""}</div>
        <div class="row wrap small" style="margin:6px 0 10px">
          <span class="pill ${aiMode ? "violet" : "medium"}">${icon(aiMode ? "sparkles" : "cpu", "sm")} ${aiMode ? "AI + rule engine" : "Rule engine"}</span>
          <span class="muted">${a.findings.length} findings · ${ago(a.created_at)}</span>
        </div>
        ${a.score_after_review !== a.score ? `<div class="small ink2">Excluding findings marked false positive: <b>${Math.round(a.score_after_review)}</b></div>` : ""}
        <a href="#" class="small" data-how>How is this scored?</a>
      </div>
    </div>
    <div class="hr"></div>
    ${dims(a.dimensions, prev?.dimensions)}
    ${a.engine_note ? `<div class="banner ${a.ai_error ? "warn" : aiMode ? "info" : "warn"}" style="margin-top:12px">${icon(a.ai_error ? "alert-triangle" : "info", "sm")}<div>${esc(a.engine_note)}</div></div>` : ""}
    <details class="ev"><summary>${icon("library", "sm")} ${a.retrieved.length} Brand Brain sources retrieved for this review</summary>
      <div class="small" style="margin-top:6px">${a.retrieved.map((r) => `<div class="row" style="margin:3px 0"><span class="src id" style="padding:1px 6px">${esc(r.id)}</span><span class="ink2">${esc(r.title)}</span><span class="muted right">${r.score ? `BM25 ${r.score}` : "always applied"}</span></div>`).join("")}</div></details>
  </div></div>`;
}

// ---------------------------------------------------------------- findings
function findingsCard(a, ctx) {
  const counts = {};
  a.findings.forEach((f) => { counts[f.category] = (counts[f.category] || 0) + 1; });
  const list = a.findings.filter((f) => state.filter === "all" || f.category === state.filter || (state.filter === "open" && !f.decision));
  const open = a.findings.filter((f) => !f.decision).length;
  return `<div class="card"><div class="card-h"><h2>${icon("list-checks", "sm")} Findings</h2><span class="muted small">${open} awaiting decision</span>
      ${can(ctx, "decide_fix") && a.findings.some((f) => !f.decision && f.suggestion?.replacement != null && f.start != null) ? `<button class="btn sm right" data-accept-all>${icon("check-check", "sm")} Accept all text fixes</button>` : ""}</div>
    <div class="card-b">
      <div class="chips" style="margin-bottom:12px">
        <button class="chip ${state.filter === "all" ? "active" : ""}" data-filter="all">All ${a.findings.length}</button>
        <button class="chip ${state.filter === "open" ? "active" : ""}" data-filter="open">Undecided ${open}</button>
        ${Object.keys(CAT).filter((k) => counts[k]).map((k) => `<button class="chip ${state.filter === k ? "active" : ""}" data-filter="${k}">${CAT[k]} ${counts[k]}</button>`).join("")}
      </div>
      <div class="stack" style="gap:10px">${list.length ? list.map((f) => finding(f, ctx)).join("") : `<div class="empty">${icon("party-popper")}<div>No findings here. This content follows the brand guidelines.</div></div>`}</div>
    </div></div>`;
}

function finding(f, ctx) {
  const sug = f.suggestion;
  const canDecide = can(ctx, "decide_fix");
  const hasRep = sug && sug.replacement != null && (f.start != null || f.target === "alt_text");
  return `<div class="finding ${f.severity} ${f.decision ? "dec-" + f.decision : ""}" id="f-${f.id}" data-card="${f.id}">
    <div class="row wrap" style="gap:6px">${sevPill(f.severity)}<span class="pill">${icon(CAT_ICON[f.category] || "dot", "sm")} ${CAT[f.category] || f.category}</span>
      <span class="pill ${f.engine === "ai" ? "violet" : "indigo"}" title="${f.engine === "ai" ? "Found by the AI model, grounded in retrieved sources" : "Deterministic rule"}">${f.engine === "ai" ? "AI" : "Rule"}</span>
      ${f.engine === "ai" && !f.grounded ? `<span class="pill medium" title="The AI did not cite an approved source; treat as advisory">Ungrounded</span>` : ""}
      ${f.learned ? `<span class="pill ${f.learned.applied ? "good" : ""} learned" title="${f.learned.applied
        ? `Feedback-learning model (active): ${Math.round(f.learned.p * 100)}% likely a real issue, based on your team's past accept/reject decisions. Confidence recalibrated from ${Math.round((f.confidence_raw ?? f.confidence) * 100)}%.`
        : `Feedback-learning model (shadow mode): ${Math.round(f.learned.p * 100)}% likely a real issue. Shown for reference only; it does not change the score yet.`}">${icon("graduation-cap", "sm")} ${Math.round(f.learned.p * 100)}%${f.learned.applied ? "" : " · shadow"}</span>` : ""}
      <span class="conf right" title="Confidence">${Math.round((f.confidence || 0) * 100)}%<span class="bar-track"><span class="bar-fill" style="display:block;width:${(f.confidence || 0) * 100}%"></span></span></span>
    </div>
    <div class="ttl" style="margin-top:8px">${esc(f.title)}</div>
    ${f.quote ? `<div style="margin-top:6px"><span class="quote" title="${esc(f.quote)}">${esc(f.quote)}</span> <span class="muted small">in ${f.target.startsWith("image") ? "image" : f.target.replace("_", " ")}</span></div>` : ""}
    <p class="expl">${esc(f.explanation)}</p>
    ${sug ? `<div class="fix"><div class="section-lbl" style="margin-bottom:4px">${icon("wand-2", "sm")} Suggested correction</div>
      ${hasRep ? `<div class="arrow"><span class="old">${esc(f.quote)}</span>${icon("arrow-right", "sm")}${sug.replacement === "" ? `<span class="new removal">remove</span>` : `<span class="new">${esc(sug.replacement)}</span>`}</div>`
        : sug.replacement ? `<div class="arrow">${icon("arrow-right", "sm")}<span class="new">${esc(sug.replacement)}</span><span class="muted small">(manual change)</span></div>` : ""}
      ${sug.rationale ? `<div class="why">${esc(sug.rationale)}</div>` : ""}</div>`
      : `<div class="fix"><span class="muted small">${icon("user-round-pen", "sm")} No automatic fix. A person needs to decide how to change this.</span></div>`}
    ${f.sources?.length ? `<details class="ev"><summary>${icon("book-open-check", "sm")} Evidence: ${f.sources.length} approved source${f.sources.length > 1 ? "s" : ""}</summary>
      ${f.sources.map((s) => `<div class="src"><span class="id">${esc(s.id)}</span> <b>${esc(s.title)}</b><div class="ink2" style="margin-top:3px">${esc(s.text)}</div></div>`).join("")}
      ${f.evidence_data ? `<div class="src mono">${esc(Object.entries(f.evidence_data).map(([k, v]) => `${k}: ${v}`).join(" · "))}</div>` : ""}
    </details>` : ""}
    <div class="f-actions">
      ${canDecide ? `<button class="btn sm ${f.decision === "accepted" ? "on-accept" : ""}" data-dec="accepted" data-id="${f.id}">${icon("check", "sm")} ${f.decision === "accepted" ? "Accepted" : hasRep ? "Accept fix" : "Acknowledge"}</button>
      <button class="btn sm ${f.decision === "rejected" ? "on-reject" : ""}" data-dec="rejected" data-id="${f.id}" title="Mark as false positive / keep original">${icon("x", "sm")} ${f.decision === "rejected" ? "Rejected" : "Reject"}</button>` : ""}
      ${f.decision && canDecide ? `<button class="btn sm ghost" data-dec="" data-id="${f.id}">Undo</button>` : ""}
      ${can(ctx, "comment") ? `<button class="btn sm ghost right" data-comment="${f.id}">${icon("message-circle", "sm")} Comment</button>` : ""}
    </div>
    ${f.decision_note ? `<div class="small muted" style="margin-top:6px">Note: ${esc(f.decision_note)}</div>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- activity
function activityCard(detail) {
  const items = [
    ...detail.events.map((e) => ({ at: e.at, user: e.user, html: eventText(e) })),
    ...detail.comments.map((c) => ({ at: c.at, user: c.user, html: `<span class="pill" style="margin-right:4px">${icon("message-circle", "sm")}</span>${esc(c.body)}${c.finding_id ? ` <a href="#" data-goto="${c.finding_id}" class="small">(on finding ${c.finding_id})</a>` : ""}` })),
  ].sort((x, y) => (x.at < y.at ? 1 : -1));
  return `<div class="card"><div class="card-h"><h2>${icon("history", "sm")} Activity, comments & approvals</h2></div><div class="card-b">
    <div class="row" style="margin-bottom:12px"><input class="input" id="cmt" placeholder="Add a comment for the team…"><button class="btn" data-post>${icon("send", "sm")}</button></div>
    <div class="timeline">${items.map((i) => `<div class="tl-item">${avatar(i.user)}<div><div class="txt"><b>${esc(i.user?.name || "System")}</b> ${i.html}</div><div class="when">${ago(i.at)}</div></div></div>`).join("")}</div>
  </div></div>`;
}

function eventText(e) {
  const map = { created: "created this content", edited: "edited the content", ai_review: "ran a brand review", submitted: "submitted for approval",
    revision_requested: "requested changes", rejected: "rejected", approved: "approved", endorsed: "endorsed for approval", fixes_applied: "applied accepted fixes",
    reopened: "reopened for review", integrity_violation: "detected an integrity violation" };
  let note = e.note || "";
  if (e.action === "approved") {
    try { const s = JSON.parse(note); note = `v${s.version} · SHA-256 <span class="hash">${s.hash.slice(0, 16)}…</span>${s.override_reason ? ` · override: “${esc(s.override_reason)}”` : ""}`; } catch { note = esc(note); }
  } else note = esc(note);
  return `${map[e.action] || esc(e.action)}${note ? ` <span class="muted">— ${note}</span>` : ""}`;
}

// ---------------------------------------------------------------- actions
function paintActions(ctx, rep, detail, isCurrent) {
  const c = rep.content, a = rep.analysis, st = c.status;
  const acceptedText = a ? a.findings.filter((f) => f.decision === "accepted" && f.suggestion?.replacement != null && (f.start != null || f.target === "alt_text")).length : 0;
  const b = [];
  if (can(ctx, "edit")) b.push(`<button class="btn" data-edit>${icon("pencil", "sm")} Edit</button>`);
  if (can(ctx, "review")) b.push(`<button class="btn" data-run>${icon("refresh-cw", "sm")} ${a ? "Re-run review" : "Run review"}</button>`);
  if (a && isCurrent && can(ctx, "edit") && acceptedText) b.push(`<button class="btn primary" data-apply>${icon("wand-2", "sm")} Apply ${acceptedText} accepted fix${acceptedText > 1 ? "es" : ""}</button>`);
  if (a && rep.previous) b.push(`<a class="btn" href="#/intelligence?dna=${c.id}&a=${rep.previous.version}&b=${rep.version.number}">${icon("dna", "sm")} Brand DNA</a>`);
  if (can(ctx, "edit") && ["ai_review", "needs_revision", "draft", "modified_after_approval"].includes(st)) b.push(`<button class="btn ${acceptedText ? "" : "primary"}" data-submit ${a ? "" : "disabled"}>${icon("send", "sm")} Submit for approval</button>`);
  if (st === "pending_approval") {
    if (can(ctx, "endorse")) b.push(`<button class="btn" data-endorse>${icon("thumbs-up", "sm")} Endorse</button>`);
    if (can(ctx, "request_revision")) b.push(`<button class="btn" data-revise>${icon("undo-2", "sm")} Request changes</button>`);
    if (can(ctx, "approve")) b.push(`<button class="btn danger" data-reject>${icon("x-circle", "sm")} Reject</button><button class="btn good" data-approve>${icon("stamp", "sm")} Approve</button>`);
  }
  if (a) b.push(`<button class="btn" data-print title="Print or save this compliance report as PDF">${icon("printer", "sm")} Print / PDF</button>`);
  if (c.approved_hash) b.push(`<button class="btn" data-verify title="Recompute SHA-256 and compare">${icon("shield-check", "sm")} Verify integrity</button>`);
  $("#actions").innerHTML = b.join("");
}

function progress(title = "Reviewing against the Brand Brain") {
  const ai = window.__inkloomAI;
  const steps = ["Extracting text, PDF and image data", "Retrieving approved brand sources (BM25 over the Brand Brain)", "Running deterministic rule checks",
    ai ? `${ai} review grounded in retrieved sources (up to ~40 s)` : "AI review skipped: rule engine mode", "Scoring and saving the report"];
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="modal" style="width:min(480px,100%)"><div class="modal-b"><h2>${title}</h2><div class="steps">${steps.map((s, i) => `<div class="s" data-s="${i}"><span class="spin" style="visibility:hidden"></span>${s}</div>`).join("")}</div><div class="small muted" data-el style="margin-top:10px">0 s</div></div></div>`;
  document.body.appendChild(ov);
  const t0 = Date.now();
  const el = setInterval(() => { const n = Math.round((Date.now() - t0) / 1000); ov.querySelector("[data-el]").textContent = `${n} s${n > 20 ? " · the free AI tier can be slow; the rule report is used if it does not answer in time" : ""}`; }, 1000);
  let i = 0;
  const tick = () => {
    $$(".s", ov).forEach((el, k) => {
      el.className = `s ${k < i ? "done" : k === i ? "on" : ""}`;
      el.firstChild.style.visibility = k === i ? "visible" : "hidden";
      if (k < i) el.firstChild.outerHTML = `<span style="width:16px;color:var(--good)">✓</span>`;
    });
  };
  tick();
  const t = setInterval(() => { if (i < 3) { i++; tick(); } }, 650);
  return { done: () => { clearInterval(t); clearInterval(el); i = 5; tick(); setTimeout(() => ov.remove(), 250); } };
}

async function runReview(id) {
  const p = progress();
  try {
    const r = await api(`/api/content/${id}/analyze`, { method: "POST" });
    p.done();
    toast(`Review complete — score ${Math.round(r.score)} (${r.findings.length} findings)`, "ok");
    if (r.ai_error) toast(`AI unavailable: ${r.ai_error}. Rule-engine report shown.`, "err");
  } catch (e) { p.done(); toast(e.message, "err"); }
  location.hash = `#/reports/${id}`;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

function wire(view, ctx, rep, detail) {
  const id = rep.content.id, a = rep.analysis;
  const reload = () => window.dispatchEvent(new HashChangeEvent("hashchange"));
  const focus = (fid) => {
    $$(".finding.focus, mark.focus", view).forEach((x) => x.classList.remove("focus"));
    const card = $(`#f-${CSS.escape(fid)}`, view);
    if (!card && state.filter !== "all") { state.filter = "all"; reload(); return; }
    card?.classList.add("focus");
    card?.scrollIntoView({ behavior: "smooth", block: "center" });
    $(`mark[data-f="${CSS.escape(fid)}"]`, view)?.classList.add("focus");
  };
  $("#ver", view).onchange = (e) => { location.hash = `#/reports/${id}?v=${e.target.value}`; };

  view.onclick = async (e) => {
    const t = e.target.closest("button, a, mark, [data-card]");
    if (!t) return;
    if (t.matches("mark[data-f]") && t.dataset.f) return focus(t.dataset.f);
    if (t.dataset.goto) { e.preventDefault(); return focus(t.dataset.goto); }
    if (t.dataset.filter) { state.filter = t.dataset.filter; return reload(); }
    if (t.hasAttribute("data-run")) return runReview(id);
    if (t.hasAttribute("data-how")) { e.preventDefault(); return howScored(ctx); }
    if (t.dataset.dec !== undefined && t.dataset.id) {
      let note = null;
      if (t.dataset.dec === "rejected") {
        note = await modal({ title: "Reject this finding?", body: `<p class="ink2">The original wording is kept and this finding stops counting toward the score. Your decision is recorded.</p><label class="f">Reason (optional)</label><input class="input" id="why" placeholder="e.g. Approved by legal for this campaign">`,
          actions: [{ label: "Cancel", value: null }, { label: "Reject finding", cls: "primary", onClick: (ov) => $("#why", ov).value || "" }] });
        if (note === null) return;
      }
      await guard(() => api(`/api/analyses/${a.id}/decisions`, { method: "POST", body: { finding_id: t.dataset.id, decision: t.dataset.dec || null, note } }));
      return reload();
    }
    if (t.hasAttribute("data-accept-all")) {
      const todo = a.findings.filter((f) => !f.decision && f.suggestion?.replacement != null && f.start != null);
      for (const f of todo) await api(`/api/analyses/${a.id}/decisions`, { method: "POST", body: { finding_id: f.id, decision: "accepted" } });
      toast(`${todo.length} fixes accepted. Review them, then apply.`, "ok");
      return reload();
    }
    if (t.dataset.comment) {
      const body = await modal({ title: `Comment on: ${esc(a.findings.find((f) => f.id === t.dataset.comment)?.title || "")}`, body: `<textarea class="textarea" id="cb" placeholder="Your comment"></textarea>`,
        actions: [{ label: "Cancel", value: null }, { label: "Post", cls: "primary", onClick: (ov) => $("#cb", ov).value.trim() || false }] });
      if (body) { await guard(() => api(`/api/content/${id}/comments`, { method: "POST", body: { body, finding_id: t.dataset.comment } }), "Comment posted"); reload(); }
      return;
    }
    if (t.hasAttribute("data-post")) {
      const body = $("#cmt", view).value.trim();
      if (!body) return;
      await guard(() => api(`/api/content/${id}/comments`, { method: "POST", body: { body } }), "Comment posted");
      return reload();
    }
    if (t.hasAttribute("data-apply")) return applyFixes(id, a);
    if (t.hasAttribute("data-edit")) return editContent(rep);
    if (t.hasAttribute("data-submit")) {
      const open = a.findings.filter((f) => !f.decision && ["critical", "high"].includes(f.severity)).length;
      const ok = await modal({ title: "Submit for approval", body: `${open ? `<div class="banner warn" style="margin-bottom:12px">${icon("alert-triangle", "sm")}<div>${open} critical/high finding(s) have no decision yet. Approvers will see them.</div></div>` : ""}<label class="f">Note to reviewers (optional)</label><textarea class="textarea" id="sn" style="min-height:70px"></textarea>`,
        actions: [{ label: "Cancel", value: null }, { label: "Submit", cls: "primary", onClick: (ov) => ({ note: $("#sn", ov).value }) }] });
      if (ok) { await guard(() => api(`/api/content/${id}/submit`, { method: "POST", body: ok }), "Submitted for approval"); reload(); }
      return;
    }
    if (t.hasAttribute("data-endorse")) {
      const note = await modal({ title: "Endorse for approval", body: `<label class="f">Manager note</label><textarea class="textarea" id="en" style="min-height:70px">Reviewed — fixes look good.</textarea>`, actions: [{ label: "Cancel", value: null }, { label: "Endorse", cls: "primary", onClick: (ov) => $("#en", ov).value }] });
      if (note !== null) { await guard(() => api(`/api/content/${id}/endorse`, { method: "POST", body: { note } }), "Endorsed"); reload(); }
      return;
    }
    if (t.hasAttribute("data-revise")) {
      const note = await modal({ title: "Request changes", body: `<label class="f">What needs to change?</label><textarea class="textarea" id="rn"></textarea>`, actions: [{ label: "Cancel", value: null }, { label: "Send back", cls: "primary", onClick: (ov) => $("#rn", ov).value.trim() || false }] });
      if (note) { await guard(() => api(`/api/content/${id}/request-revision`, { method: "POST", body: { note } }), "Sent back for revision"); reload(); }
      return;
    }
    if (t.hasAttribute("data-reject")) {
      const note = await modal({ title: "Reject content", body: `<label class="f">Reason</label><textarea class="textarea" id="xn"></textarea>`, actions: [{ label: "Cancel", value: null }, { label: "Reject", cls: "danger solid", onClick: (ov) => $("#xn", ov).value.trim() || false }] });
      if (note) { await guard(() => api(`/api/content/${id}/reject`, { method: "POST", body: { note } }), "Rejected"); reload(); }
      return;
    }
    if (t.hasAttribute("data-approve")) return approve(id, a);
    if (t.hasAttribute("data-verify")) {
      const r = await guard(() => api(`/api/content/${id}/verify`, { method: "POST" }));
      if (!r) return;
      if (r.status === "intact") toast("Integrity verified: content matches the approved SHA-256.", "ok");
      else { toast("Integrity violation: content changed after approval.", "err"); reload(); }
    }
  };
  const pv = $("#pv", view);
  if (pv) pv.onchange = () => { state.preview = pv.checked; reload(); };
}

async function applyFixes(id, a) {
  const p = progress("Applying your fixes and re-reviewing the new version");
  const r = await guard(() => api(`/api/content/${id}/apply-fixes`, { method: "POST", body: { analysis_id: a.id } }));
  p.done();
  if (!r) return;
  const d = Math.round(r.after.score - r.before.score);
  await modal({
    title: `${icon("dna", "sm")} Fixes applied — version ${r.version}`,
    body: `<div class="compare" style="text-align:center">
        <div><div class="muted small">Before</div><div class="big-delta">${Math.round(r.before.score)}</div></div>
        <div><div class="muted small">After (re-reviewed)</div><div class="big-delta" style="color:${d >= 0 ? "var(--good)" : "var(--critical)"}">${Math.round(r.after.score)} <span class="delta ${d >= 0 ? "up" : "down"}">${d >= 0 ? "+" : ""}${d}</span></div></div>
      </div><div class="hr"></div>${dims(r.after.dimensions, r.before.dimensions)}
      <p class="small muted">The original is kept as version ${r.version - 1}. Only the ${r.applied.length} fix(es) you accepted were applied, then the new version was reviewed again.</p>
      ${r.skipped.length ? `<div class="banner warn">${icon("hand", "sm")}<div>${r.skipped.length} accepted item(s) need a manual change (for example, image fixes): ${r.skipped.map((s) => esc(s.title || s.id)).join(", ")}.</div></div>` : ""}`,
    actions: [{ label: "View new version", cls: "primary" }],
  });
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

async function approve(id, a) {
  const open = a.findings.filter((f) => ["critical", "high"].includes(f.severity) && f.decision !== "rejected");
  const r = await modal({
    title: "Approve content",
    body: `${open.length ? `<div class="banner warn" style="margin-bottom:12px">${icon("alert-triangle", "sm")}<div><b>${open.length} critical/high finding(s) are still open.</b> The AI recommends; you decide. Approving anyway requires a reason, which is recorded in the approval log.<ul style="margin:6px 0 0 16px;padding:0">${open.slice(0, 5).map((f) => `<li>${esc(f.title)}</li>`).join("")}</ul></div></div>
      <label class="f">Override reason (required)</label><textarea class="textarea" id="or" style="min-height:70px"></textarea>` : `<div class="banner ok" style="margin-bottom:12px">${icon("check-circle-2", "sm")}<div>No open critical or high findings.</div></div>`}
      <label class="f">Approval note (optional)</label><input class="input" id="an">
      <p class="small muted">On approval, Inkloom stores a SHA-256 fingerprint of this exact version. Any later change is detected and sent back for re-review.</p>`,
    actions: [{ label: "Cancel", value: null }, { label: "Approve & seal", cls: "good", onClick: (ov) => {
      const o = $("#or", ov)?.value.trim();
      if (open.length && !o) { toast("Give an override reason or resolve the findings first.", "err"); return false; }
      return { override_reason: o || null, note: $("#an", ov).value };
    } }],
  });
  if (!r) return;
  const res = await guard(() => api(`/api/content/${id}/approve`, { method: "POST", body: r }));
  if (res) toast(`Approved and sealed · SHA-256 ${res.hash.slice(0, 12)}…`, "ok");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

async function editContent(rep) {
  const v = rep.version, c = rep.content;
  const r = await modal({
    title: "Edit content (creates a new version)",
    body: `${c.status === "approved" ? `<div class="banner warn" style="margin-bottom:12px">${icon("shield-alert", "sm")}<div>This content is approved. Editing it will break the approval seal and send it back for review.</div></div>` : ""}
      <div class="field"><label class="f">Title</label><input class="input" id="et" value="${esc(c.title)}"></div>
      <div class="field"><label class="f">Caption / body</label><textarea class="textarea" id="eb" style="min-height:160px">${esc(v.body || "")}</textarea></div>
      <div class="field"><label class="f">Alt text</label><textarea class="textarea" id="ea" style="min-height:70px">${esc(v.alt_text || "")}</textarea></div>`,
    actions: [{ label: "Cancel", value: null }, { label: "Save new version", cls: "primary", onClick: (ov) => ({ title: $("#et", ov).value, body: $("#eb", ov).value, alt_text: $("#ea", ov).value, note: "Edited manually" }) }],
  });
  if (!r) return;
  const res = await guard(() => api(`/api/content/${c.id}`, { method: "PUT", body: r }), "Saved as a new version");
  if (res) { location.hash = `#/reports/${c.id}`; window.dispatchEvent(new HashChangeEvent("hashchange")); }
}

function howScored(ctx) {
  const s = ctx.status.scoring;
  modal({ title: "How the compliance score works", body: `<p class="ink2">Scores are computed, not guessed. Same content → same score.</p>
    <p><code>${esc(s.formula)}</code></p>
    <table class="t"><tr><th>Severity</th><th>Penalty weight</th><th>Example impact alone</th></tr>
    ${Object.entries(s.penalties).map(([k, v]) => `<tr><td>${sevPill(k)}</td><td>${v}</td><td>≈ ${Math.round(100 * Math.exp(-v * 0.9 / 100))}/100 at 90% confidence</td></tr>`).join("")}</table>
    <p class="small muted">Each dimension uses the same curve on its own findings (divisor 50). Findings you reject as false positives stop counting. ≥85 is ready to publish, 60–84 needs attention, below 60 is high brand risk.</p>`,
    actions: [{ label: "Got it", cls: "primary" }] });
}
