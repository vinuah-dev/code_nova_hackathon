import { api, fileToB64, guessMime } from "../api.js";
import { $, ago, esc, guard, icon, icons, modal, sevPill, toast } from "../ui.js";

let tab = "guidelines";
const TABS = [
  ["guidelines", "Guidelines", "book-open"], ["terms", "Terminology", "spell-check"], ["prohibited", "Prohibited phrases", "ban"],
  ["facts", "Approved facts", "file-check-2"], ["claims", "Approved claims", "badge-check"], ["visual", "Visual identity", "palette"],
  ["documents", "Documents", "file-up"], ["retrieval", "Test retrieval", "search"],
];

export async function render(view, ctx) {
  const b = await api("/api/brand");
  const admin = ctx.status.permissions.brand.includes(ctx.me.role);
  const counts = { guidelines: b.guidelines.length, terms: b.terms.length, prohibited: b.prohibited.length, facts: b.facts.length, claims: b.claims.length, visual: b.colors.length + b.assets.length, documents: b.documents.length };
  view.innerHTML = `
    <div class="page-head"><div><h1>Brand Brain</h1><div class="sub">The approved source of truth. Every finding must point back to something here. <b>${b.chunk_count}</b> retrievable knowledge chunks.</div></div>
      <div class="actions">${admin ? "" : `<span class="pill">${icon("eye", "sm")} Read-only for ${esc(ctx.me.role)}s</span>`}</div></div>
    <div class="tabs">${TABS.map(([k, l, ic]) => `<button class="${tab === k ? "active" : ""}" data-tab="${k}">${icon(ic, "sm")} ${l}${counts[k] != null ? ` <span class="n">${counts[k]}</span>` : ""}</button>`).join("")}</div>
    <div id="pane">${pane(b, admin)}</div>`;
  view.onclick = async (e) => {
    const t = e.target.closest("[data-tab],[data-add],[data-del],[data-edit-g],[data-upload],[data-search],[data-extract]");
    if (!t) return;
    if (t.dataset.tab) { tab = t.dataset.tab; return render(view, ctx); }
    if (t.dataset.del) {
      const [kind, id] = t.dataset.del.split(":");
      const ok = await modal({ title: "Remove from Brand Brain?", body: `<p class="ink2">Future reviews will no longer use this item. Past reports keep their recorded evidence.</p>`, actions: [{ label: "Cancel", value: false }, { label: "Remove", cls: "danger solid", value: true }] });
      if (ok && await guard(() => api(`/api/brand/${kind}/${encodeURIComponent(id)}`, { method: "DELETE" }), "Removed")) render(view, ctx);
      return;
    }
    if (t.dataset.editG !== undefined) return editGuideline(view, ctx, b.guidelines.find((g) => g.id === t.dataset.editG));
    if (t.dataset.add) return addItem(view, ctx, t.dataset.add);
    if (t.dataset.upload) return upload(view, ctx, t.dataset.upload);
    if (t.dataset.extract) return extractRules(view, ctx, +t.dataset.extract);
    if (t.hasAttribute("data-search")) return search();
  };
  const q = $("#q");
  if (q) q.onkeydown = (e) => { if (e.key === "Enter") search(); };
  icons();
}

const del = (admin, kind, id) => admin ? `<button class="btn ghost sm" data-del="${kind}:${esc(id)}" aria-label="Remove">${icon("trash-2", "sm")}</button>` : "";

function pane(b, admin) {
  if (tab === "guidelines") {
    const cats = [...new Set(b.guidelines.map((g) => g.category))];
    return `<div class="row" style="margin-bottom:12px">${admin ? `<button class="btn primary" data-edit-g="">${icon("plus", "sm")} Add guideline</button>` : ""}</div>
      <div class="grid g2">${b.guidelines.map((g) => `<div class="card"><div class="card-b">
        <div class="row"><span class="src id">${esc(g.id)}</span><span class="pill">${esc(g.category)}</span><span class="muted small">v${g.version}</span>
          <span class="right">${admin ? `<button class="btn ghost sm" data-edit-g="${esc(g.id)}">${icon("pencil", "sm")}</button>${del(admin, "guidelines", g.id)}` : ""}</span></div>
        <h3 style="margin:8px 0 4px">${esc(g.title)}</h3><div class="ink2" style="white-space:pre-wrap">${esc(g.body)}</div>
        <div class="small muted" style="margin-top:8px">${esc(g.source || "")} · updated ${ago(g.updated_at)}</div></div></div>`).join("")}</div>
      ${b.history.length ? `<div class="card" style="margin-top:16px"><div class="card-h"><h2>${icon("history", "sm")} Guideline change history</h2></div><div class="card-b"><table class="t"><tbody>
        ${b.history.map((h) => `<tr><td><span class="src id">${esc(h.guideline_id)}</span></td><td>${esc(h.reason || "")}</td><td class="muted small">${esc(h.changed_by)} · ${ago(h.at)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
      <p class="small muted">${cats.length} categories. Guidelines are retrievable by id in every review.</p>`;
  }
  if (tab === "terms") return table(admin, "terms", "Add term rule", ["Approved term", "Never write", "Note"], b.terms.map((t) => [
    `<b>${esc(t.preferred)}</b>`, t.disallowed.map((d) => `<span class="pill critical" style="margin:2px">${esc(d)}</span>`).join(""), esc(t.note || ""), t.id]));
  if (tab === "prohibited") return table(admin, "prohibited", "Add phrase", ["Phrase", "Why", "Use instead", "Severity"], b.prohibited.map((p) => [
    `<b>${esc(p.phrase)}</b>`, esc(p.reason || ""), p.replacement ? `<span class="pill good">${esc(p.replacement)}</span>` : "—", sevPill(p.severity || "medium"), p.id]));
  if (tab === "facts") return table(admin, "facts", "Add approved fact", ["Fact", "Approved statement", "Value", "Outdated values", "Source"], b.facts.map((f) => [
    `<span class="src id">${esc(f.id)}</span> <b>${esc(f.label)}</b>`, esc(f.statement), f.value != null ? `<b>${f.value} ${esc(f.unit || "")}</b>` : "—",
    f.outdated_values.length ? f.outdated_values.map((v) => `<span class="pill critical">${v}</span>`).join(" ") : "—", `<span class="small">${esc(f.source || "")}<br><span class="muted">verified ${esc(f.verified_on || "")}</span></span>`, f.id]));
  if (tab === "claims") return table(admin, "claims", "Add approved claim", ["Claim", "Evidence", "Approved by"], b.claims.map((c) => [
    `<span class="src id">${esc(c.id)}</span> <b>${esc(c.text)}</b>`, esc(c.evidence || ""), esc(c.approved_by || ""), c.id]));
  if (tab === "visual") return `<div class="grid g2">
    <div class="card"><div class="card-h"><h2>Approved colours</h2>${admin ? `<button class="btn sm right" data-add="colors">${icon("plus", "sm")} Add</button>` : ""}</div><div class="card-b stack" style="gap:8px">
      ${b.colors.map((c) => `<div class="row"><span class="sw" style="width:38px;height:38px;border-radius:10px;background:${c.hex}"></span><div><b>${esc(c.name)}</b><div class="small muted mono">${esc(c.hex)} · ${esc(c.usage || "")}</div></div><span class="right">${del(admin, "colors", c.id)}</span></div>`).join("")}</div></div>
    <div class="card"><div class="card-h"><h2>Official logos & assets</h2>${admin ? `<button class="btn sm right" data-upload="assets">${icon("upload", "sm")} Upload logo</button>` : ""}</div><div class="card-b">
      <div class="imgs">${b.assets.map((a) => `<div class="img-card"><img src="${a.url}" alt="${esc(a.name)}"><div class="cap">${icon("badge-check", "sm")}${esc(a.name)}<span class="right">${del(admin, "assets", a.id)}</span></div></div>`).join("") || `<div class="empty small">No logos yet</div>`}</div>
      <p class="small muted">Logos used in content are compared against these: aspect ratio (distortion), main colour (ΔE) and shape hash.</p></div></div></div>`;
  if (tab === "documents") return `<div class="card"><div class="card-h"><h2>Brand documents</h2>${admin ? `<button class="btn primary sm right" data-upload="documents">${icon("upload", "sm")} Upload guidelines (PDF / TXT / MD)</button>` : ""}</div><div class="card-b">
    <p class="ink2">Uploaded documents are split into paragraphs and indexed. Reviews retrieve the most relevant paragraphs and the AI must cite them by id (e.g. <code>DOC-1#3</code>).</p>
    ${b.documents.length ? `<table class="t"><thead><tr><th>Document</th><th>Characters indexed</th><th>Uploaded</th><th></th></tr></thead><tbody>${b.documents.map((d) => `<tr><td>${icon("file-text", "sm")} <b>${esc(d.name)}</b> <span class="src id">DOC-${d.id}</span></td><td>${d.chars}</td><td class="muted small">${ago(d.uploaded_at)}</td><td class="row" style="gap:6px;justify-content:flex-end">${admin ? `<button class="btn sm primary" data-extract="${d.id}">${icon("wand-2", "sm")} Extract rules</button>` : ""}${del(admin, "documents", d.id)}</td></tr>`).join("")}</tbody></table>
      <p class="small muted" style="margin-bottom:0">${icon("info", "sm")} <b>Extract rules</b> reads a document and proposes facts, terms, banned phrases, approved claims and colours. Each proposal quotes the sentence it came from; you choose what to add. Try it with <a href="/demo/Voltaro_Guidelines_Update_2026.pdf" target="_blank">Voltaro_Guidelines_Update_2026.pdf</a> (demo file: upload it, then Extract rules).</p>`
      : `<div class="empty">${icon("file-up")}<div>No documents yet. Try <a href="/demo/Voltaro_Brand_Book_2026.pdf" target="_blank">Voltaro_Brand_Book_2026.pdf</a> (demo file).</div></div>`}</div></div>`;
  return `<div class="card"><div class="card-b"><p class="ink2">See exactly what the reviewer would retrieve from the Brand Brain for any text. This is the retrieval step (BM25) that grounds AI findings.</p>
    <div class="row"><input class="input" id="q" placeholder="e.g. Diwali offer with 150 km range and a red background"><button class="btn primary" data-search>${icon("search", "sm")} Retrieve</button></div>
    <div id="res" class="stack" style="gap:8px;margin-top:14px"></div></div></div>`;
}

function table(admin, kind, addLabel, heads, rows) {
  return `<div class="card"><div class="card-h">${admin ? `<button class="btn primary sm" data-add="${kind}">${icon("plus", "sm")} ${addLabel}</button>` : ""}</div><div class="card-b">
    <table class="t"><thead><tr>${heads.map((h) => `<th>${h}</th>`).join("")}<th></th></tr></thead><tbody>
    ${rows.map((r) => `<tr>${r.slice(0, -1).map((c) => `<td>${c}</td>`).join("")}<td>${del(admin, kind, r[r.length - 1])}</td></tr>`).join("")}</tbody></table></div></div>`;
}

const FORMS = {
  terms: [["preferred", "Approved term", "Voltaro Glide S1"], ["disallowed", "Never write (comma separated)", "Glide-S1, GlideS1"], ["note", "Note", ""]],
  prohibited: [["phrase", "Phrase", "crazy deal"], ["reason", "Why it's prohibited", ""], ["replacement", "Use instead", ""], ["severity", "Severity (critical/high/medium/low)", "medium"], ["category", "Category (tone/claims/…)", "tone"]],
  facts: [["label", "Fact name", "Boot space"], ["statement", "Approved statement", "Under-seat storage is 26 litres."], ["value", "Numeric value (optional)", "26"], ["unit", "Unit (km, min, years, km/h, %, kg, hours…)", ""], ["keywords", "Context keywords (comma separated)", "storage, boot"], ["outdated_values", "Outdated values (comma separated)", ""], ["source", "Source / evidence", ""]],
  claims: [["text", "Approved claim", "India's most awarded electric scooter design"], ["evidence", "Evidence", ""]],
  colors: [["name", "Name", "Voltaro Indigo"], ["hex", "Hex", "#3B2FC9"], ["usage", "Usage", "Primary"]],
};

async function addItem(view, ctx, kind) {
  const f = FORMS[kind];
  const data = await modal({ title: "Add to Brand Brain", body: f.map(([k, l, ph]) => `<div class="field"><label class="f">${l}</label>${k === "statement" || k === "evidence" || k === "reason" ? `<textarea class="textarea" style="min-height:70px" data-k="${k}" placeholder="${esc(ph)}"></textarea>` : `<input class="input" data-k="${k}" placeholder="${esc(ph)}">`}</div>`).join(""),
    actions: [{ label: "Cancel", value: null }, { label: "Save", cls: "primary", onClick: async (ov) => {
      const body = {};
      ov.querySelectorAll("[data-k]").forEach((el) => { if (el.value.trim()) body[el.dataset.k] = el.value.trim(); });
      return (await guard(() => api(`/api/brand/${kind}`, { method: "POST", body }), "Saved to Brand Brain")) ? true : false;
    } }] });
  if (data) render(view, ctx);
}

async function editGuideline(view, ctx, g) {
  const ok = await modal({ title: g ? `Edit ${g.id}` : "Add guideline", body: `
    <div class="grid g2"><div class="field"><label class="f">Title</label><input class="input" id="gt" value="${esc(g?.title || "")}"></div>
    <div class="field"><label class="f">Category</label><select class="select" id="gc">${["tone", "claims", "facts", "terminology", "visual", "accessibility", "legal"].map((c) => `<option ${g?.category === c ? "selected" : ""}>${c}</option>`).join("")}</select></div></div>
    <div class="field"><label class="f">Guideline text</label><textarea class="textarea" id="gb" style="min-height:160px">${esc(g?.body || "")}</textarea></div>
    ${g ? `<div class="field"><label class="f">Reason for change</label><input class="input" id="gr" placeholder="Recorded in history"></div>` : ""}`,
    actions: [{ label: "Cancel", value: null }, { label: "Save", cls: "primary", onClick: async (ov) => !!(await guard(() => api("/api/brand/guidelines", { method: "POST", body: { id: g?.id, title: $("#gt", ov).value, category: $("#gc", ov).value, body: $("#gb", ov).value, reason: $("#gr", ov)?.value } }), "Guideline saved")) }] });
  if (ok) render(view, ctx);
}

function upload(view, ctx, kind) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = kind === "assets" ? ".png,.jpg,.jpeg,.webp" : ".pdf,.txt,.md";
  inp.onchange = async () => {
    const f = inp.files[0];
    if (!f) return;
    toast(`Uploading ${f.name}…`);
    const r = await guard(async () => api(`/api/brand/${kind}`, { method: "POST", body: { name: f.name, label: f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "), mime: guessMime(f), data: await fileToB64(f), kind: "logo" } }),
      kind === "documents" ? `Indexed ${f.name}` : "Logo added");
    if (r) render(view, ctx);
  };
  inp.click();
}

async function search() {
  const q = $("#q").value.trim();
  if (!q) return;
  const hits = await guard(() => api(`/api/brand/search?q=${encodeURIComponent(q)}`));
  if (!hits) return;
  $("#res").innerHTML = hits.map((h) => `<div class="src"><div class="row"><span class="id">${esc(h.id)}</span><b>${esc(h.title)}</b><span class="pill">${esc(h.type)}</span><span class="muted small right">${h.always ? "always applied" : `BM25 ${h.score}`}</span></div><div class="ink2" style="margin-top:4px">${esc(h.text)}</div></div>`).join("");
}

// ---------------------------------------------------------------- import rules from a document
const KIND_LABEL = { facts: "Approved facts", terms: "Terminology", prohibited: "Prohibited phrases", claims: "Approved claims", colors: "Colours" };
const describe = {
  facts: (i) => `<b>${esc(i.label)}</b>: ${esc(i.value ?? "")} ${esc(i.unit || "")}<div class="small ink2">${esc(i.statement)}</div>`,
  terms: (i) => `Write <b>${esc(i.preferred)}</b>, not ${(i.disallowed || []).map((d) => `<span class="quote">${esc(d)}</span>`).join(" ") || "—"}`,
  prohibited: (i) => `Avoid <span class="quote">${esc(i.phrase)}</span>${i.replacement ? ` → <b>${esc(i.replacement)}</b>` : ""}<div class="small ink2">${esc(i.reason || "")}</div>`,
  claims: (i) => `<b>${esc(i.text)}</b><div class="small ink2">Evidence: ${esc(i.evidence || "")}</div>`,
  colors: (i) => `<span class="swatch" style="display:inline-block;width:14px;height:14px;border-radius:4px;vertical-align:-2px;background:${esc(i.hex)}"></span> <b>${esc(i.name)}</b> <code>${esc(i.hex)}</code> ${esc(i.usage || "")}`,
};
const payload = {
  facts: (i) => ({ label: i.label, value: i.value, unit: i.unit, statement: i.statement, keywords: i.keywords || [], source: `${i.source} (extracted)` }),
  terms: (i) => ({ preferred: i.preferred, disallowed: i.disallowed || [], note: i.quote }),
  prohibited: (i) => ({ phrase: i.phrase, reason: i.reason, replacement: i.replacement || "", severity: i.severity || "medium", category: "tone" }),
  claims: (i) => ({ text: i.text, evidence: `${i.evidence} (${i.source})` }),
  colors: (i) => ({ name: i.name, hex: i.hex, usage: i.usage || "" }),
};

async function extractRules(view, ctx, did) {
  const wait = document.createElement("div");
  wait.className = "overlay";
  wait.innerHTML = `<div class="modal" style="width:min(420px,100%)"><div class="modal-b row"><span class="spin"></span> Reading the document and extracting rules…</div></div>`;
  document.body.appendChild(wait);
  const r = await guard(() => api(`/api/brand/documents/${did}/extract`, { method: "POST" }));
  wait.remove();
  if (!r) return;
  const flat = Object.entries(r.proposals).flatMap(([kind, items]) => items.map((i) => ({ kind, i })));
  const fresh = flat.filter((x) => !x.i.already).length;
  const added = await modal({
    title: `${icon("wand-2", "sm")} Rules found in ${esc(r.document.name)}`, wide: true,
    body: `<div class="banner ${r.engine === "ai" ? "info" : "warn"}" style="margin-bottom:12px">${icon(r.engine === "ai" ? "sparkles" : "cpu", "sm")}<div>${esc(r.note)}${r.dropped_ungrounded ? ` ${r.dropped_ungrounded} proposal(s) were dropped because their quote was not in the document.` : ""}</div></div>
      ${flat.length ? Object.entries(r.proposals).filter(([, v]) => v.length).map(([kind, items]) => `<div class="section-lbl" style="margin-top:10px">${KIND_LABEL[kind]}</div>
        ${items.map((i, n) => `<label class="src row" style="gap:10px;align-items:flex-start;cursor:pointer;margin-bottom:6px">
          <input type="checkbox" data-pick="${kind}:${n}" ${i.already ? "" : "checked"} style="margin-top:4px">
          <div style="min-width:0">${describe[kind](i)}${i.already ? ` <span class="pill">already in Brand Brain</span>` : ""}
            <div class="small muted" style="margin-top:3px">${icon("quote", "sm")} “${esc(i.quote)}” · ${esc(i.source)}</div></div></label>`).join("")}`).join("")
        : `<div class="empty small">No rules could be extracted from this document.</div>`}`,
    actions: [{ label: "Cancel", value: null }, ...(flat.length ? [{
      label: `Add selected to Brand Brain`, cls: "primary",
      onClick: async (ov) => {
        const picks = [...ov.querySelectorAll("[data-pick]:checked")].map((c) => c.dataset.pick.split(":"));
        if (!picks.length) { toast("Nothing selected", "err"); return false; }
        let ok = 0;
        for (const [kind, n] of picks) {
          try { await api(`/api/brand/${kind}`, { method: "POST", body: payload[kind](r.proposals[kind][+n]) }); ok++; }
          catch (e) { toast(`${KIND_LABEL[kind]}: ${e.message}`, "err"); }
        }
        return ok;
      },
    }] : [])],
  });
  if (added) { toast(`${added} rule(s) added to the Brand Brain. New reviews use them right away.`, "ok"); render(view, ctx); }
  else if (fresh === 0 && flat.length) toast("Everything in this document is already in the Brand Brain");
}
