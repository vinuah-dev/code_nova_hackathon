import { api, fileToB64, guessMime } from "../api.js";
import { $, ago, esc, guard, icon, icons, modal, scoreBadge, statusPill, toast } from "../ui.js";

const CHANNELS = ["Instagram", "LinkedIn", "Website", "Email", "Blog", "WhatsApp", "Display ads", "Search ads", "Print", "Press release"];
let files = [];

export async function render(view, ctx, params) {
  const can = ctx.status.permissions.create.includes(ctx.me.role);
  if (params.mode === "new") return renderNew(view, ctx, can);
  const list = await api("/api/content");
  view.innerHTML = `
    <div class="page-head"><div><h1>Content Studio</h1><div class="sub">Draft, upload and review content before it goes anywhere public.</div></div>
      <div class="actions">${can ? `<button class="btn" id="bulk">${icon("table", "sm")} Bulk review (CSV)</button><a class="btn primary" href="#/studio/new">${icon("plus", "sm")} New content</a>` : `<span class="muted small">Switch to a Creator to add content</span>`}</div></div>
    <div class="card"><table class="t"><thead><tr><th>Content</th><th>Channel</th><th>Owner</th><th>Status</th><th>Score</th><th>Issues</th><th>Updated</th></tr></thead><tbody>
      ${list.map((c) => `<tr class="click" data-href="#/reports/${c.id}">
        <td><b>${esc(c.title)}</b> ${c.is_demo ? `<span class="tag-demo">demo</span>` : ""} ${c.confidential ? icon("lock", "sm") : ""}<div class="small muted">v${c.current_version}</div></td>
        <td>${esc(c.channel || "")}</td><td>${esc(c.owner || "")}</td><td>${statusPill(c.status, c.status_label)}</td>
        <td>${scoreBadge(c.score)}</td><td>${c.analysis_id ? `${c.issues}${c.critical ? ` <span class="pill high">${c.critical} serious</span>` : ""}` : "—"}</td><td class="muted small">${ago(c.updated_at)}</td></tr>`).join("")}
    </tbody></table>${list.length ? "" : `<div class="empty">${icon("inbox")}<div>No content yet.</div></div>`}</div>`;
  view.onclick = (e) => { const tr = e.target.closest("tr[data-href]"); if (tr) location.hash = tr.dataset.href; };
  const bulk = $("#bulk");
  if (bulk) bulk.onclick = () => bulkReview(view, ctx);
}

// ---------------------------------------------------------------- bulk review from CSV
function parseCSV(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((c) => c.trim())) rows.push(row);
      row = [];
    } else cell += ch;
  }
  row.push(cell);
  if (row.some((c) => c.trim())) rows.push(row);
  if (!rows.length) return [];
  const head = rows[0].map((h) => h.trim().toLowerCase());
  const col = (names) => head.findIndex((h) => names.includes(h));
  const iBody = col(["body", "text", "copy", "caption", "content"]), iTitle = col(["title", "name"]), iCh = col(["channel"]), iAlt = col(["alt_text", "alt text", "alt"]);
  if (iBody < 0) return null;
  return rows.slice(1).map((r) => ({ title: r[iTitle] ?? "", channel: r[iCh] ?? "", body: r[iBody] ?? "", alt_text: iAlt >= 0 ? r[iAlt] ?? "" : "" })).filter((r) => r.body.trim());
}

async function bulkReview(view, ctx) {
  const ai = ctx.status.ai_configured;
  const go = await modal({
    title: `${icon("table", "sm")} Bulk review from CSV`, wide: true,
    body: `<p class="ink2" style="margin-top:0">Review up to 25 posts at once, for example a content calendar. Columns: <code>title</code>, <code>channel</code>, <code>body</code> (required), <code>alt_text</code>. Each row becomes a draft with its own report.</p>
      <div class="row wrap" style="gap:8px;margin-bottom:10px"><label class="btn sm">${icon("upload", "sm")} Choose CSV file<input type="file" id="bk-file" accept=".csv,text/csv" hidden></label>
        <button class="btn sm" id="bk-sample">${icon("flask-conical", "sm")} Load sample (6 posts)</button><a class="small" href="/demo/bulk_review_sample.csv" download>Download sample CSV</a></div>
      <textarea class="textarea mono" id="bk-text" style="min-height:160px" placeholder="title,channel,body&#10;Weekend offer,Instagram,&quot;Your post text…&quot;"></textarea>
      <div class="row" style="margin-top:8px"><span class="small muted" id="bk-count">0 rows</span>
        ${ai ? `<label class="toggle small right"><input type="checkbox" id="bk-ai"><span class="sl"></span>Include AI review (5 rows max, slower)</label>` : `<span class="small muted right">${icon("cpu", "sm")} Rule engine</span>`}</div>`,
    onMount: (ov) => {
      const ta = $("#bk-text", ov);
      const count = () => { const r = parseCSV(ta.value); $("#bk-count", ov).textContent = r === null ? "No 'body' column found" : `${r.length} row(s) with text`; };
      ta.oninput = count;
      $("#bk-file", ov).onchange = async (e) => { const f = e.target.files[0]; if (f) { ta.value = await f.text(); count(); } };
      $("#bk-sample", ov).onclick = async () => { ta.value = await (await fetch("/demo/bulk_review_sample.csv")).text(); count(); };
    },
    actions: [{ label: "Cancel", value: null }, { label: "Review all", cls: "primary", onClick: (ov) => {
      const rows = parseCSV($("#bk-text", ov).value);
      if (!rows || !rows.length) { toast("Add a CSV with a 'body' column and at least one row", "err"); return false; }
      if (rows.length > 25) { toast(`Up to 25 rows per batch (you have ${rows.length})`, "err"); return false; }
      return { rows, use_ai: !!$("#bk-ai", ov)?.checked };
    } }],
  });
  if (!go) return;
  const wait = document.createElement("div");
  wait.className = "overlay";
  wait.innerHTML = `<div class="modal" style="width:min(420px,100%)"><div class="modal-b row"><span class="spin"></span> Reviewing ${go.rows.length} item(s)…</div></div>`;
  document.body.appendChild(wait);
  const r = await guard(() => api("/api/bulk-review", { method: "POST", body: go }));
  wait.remove();
  if (!r) return;
  const s = r.summary;
  await modal({
    title: `${icon("list-checks", "sm")} Bulk review: ${s.count} item(s)`, wide: true,
    body: `<div class="grid g4" style="gap:10px;margin-bottom:12px">
        <div class="kpi"><div class="lbl">Average score</div><div class="val">${Math.round(s.avg_score)}</div></div>
        <div class="kpi"><div class="lbl">Ready to publish</div><div class="val">${s.ready}</div></div>
        <div class="kpi"><div class="lbl">High brand risk</div><div class="val">${s.high_risk}</div></div>
        <div class="kpi"><div class="lbl">Engine</div><div class="val" style="font-size:16px">${r.ai_used ? "AI + rules" : "Rules"}</div></div></div>
      <table class="t keep"><thead><tr><th>Score</th><th>Item</th><th>Serious</th><th>Top issues</th></tr></thead><tbody>
      ${r.items.sort((x, y) => x.score - y.score).map((i) => `<tr><td>${scoreBadge(i.score)}</td><td><a href="#/reports/${i.id}"><b>${esc(i.title)}</b></a><div class="small muted">${esc(i.channel)}</div></td>
        <td>${i.serious || "—"}</td><td class="small">${i.top.map(esc).join("; ") || "No issues"}</td></tr>`).join("")}</tbody></table>
      <p class="small muted">Each item is a draft with its own report: open one to accept fixes and submit it for approval.</p>`,
    onMount: (ov) => ov.addEventListener("click", (e) => { if (e.target.closest("a[href^='#/reports/']")) ov.remove(); }),
    actions: [{ label: "Done", cls: "primary" }],
  });
  render(view, ctx, {});
}

// Content types the brief names: a post, an advertisement, an email or a document.
const TYPES = {
  post: { label: "Social post", ic: "message-square", channel: "Instagram", body: "Caption", ph: "Paste the post caption…", alt: true, files: true },
  ad: { label: "Advertisement", ic: "megaphone", channel: "Display ads", body: "Ad copy", ph: "Headline and ad text…", alt: true, files: true },
  email: { label: "Email", ic: "mail", channel: "Email", body: "Email body", ph: "Hi rider,…", alt: false, files: false, subject: true },
  doc: { label: "Document", ic: "file-text", channel: "Press release", body: "Notes or summary (optional)", ph: "Optional: paste text, or upload the PDF on the right…", alt: false, files: true },
};
const SAMPLES = {
  hi: { title: "Diwali post (Hindi)", channel: "Instagram",
    body: "दिवाली धमाका! वोल्टारो Glide-S1 अब सबसे सस्ता इलेक्ट्रिक स्कूटर, एक चार्ज में 150 किमी की रेंज, 100% गारंटी के साथ!! यहाँ क्लिक करें और जल्दी करो।" },
  hinglish: { title: "Diwali post (Hinglish)", channel: "Instagram",
    body: "Diwali ka sabse best offer! Glide-S1 ab ek charge mein 150 km chalega, pakka guarantee ke saath!! Jaldi karo, yahan click karein. Dhaasu deal sirf 31 Oct 2025 tak." },
  ad: { title: "Year-end search ad", channel: "Search ads",
    body: "Voltaro S1: India's cheapest premium scooter. Unbeatable price, 150 km range and the lowest EMI, guaranteed. Hurry, offer valid till 31 Dec 2025!" },
  email: { title: "Festive offer email", channel: "Email", subject: "CRAZY DEAL on the Glide-S1!!!",
    body: "Hi rider,\n\nThe Glide-S1 is the best electric scooter in India and charges 0-80% in 60 minutes with the Voltaro Fast Charger. A 5 years battery warranty makes it a no-brainer.\n\nClick here to grab this crazy deal before it ends on 15 Oct 2025.\n\nTeam Voltaro" },
};
let ctype = "post";

function renderNew(view, ctx, can) {
  files = [];
  if (!can) {
    view.innerHTML = `<div class="card"><div class="card-b empty" style="padding:48px 20px">${icon("user-round-pen")}
      <h2 style="color:var(--ink);margin:6px 0">Creators submit content</h2>
      <p>You are signed in as ${esc(ctx.me.name)} (${esc(ctx.me.role)}). Switch to the Content Creator demo account to submit something for review.</p>
      <button class="btn primary" id="as-creator">${icon("repeat", "sm")} Switch to Rohan Mehta (Creator)</button></div></div>`;
    $("#as-creator").onclick = async () => { const { switchUser } = await import("../app.js"); await switchUser("u-creator"); };
    icons();
    return;
  }
  const qs = new URLSearchParams(location.hash.split("?")[1] || "");
  ctype = TYPES[qs.get("type")] ? qs.get("type") : "post";
  view.innerHTML = `
    <div class="page-head"><div><h1>New content</h1><div class="sub">Pick what you are publishing, add it, and run the brand review. Nothing is published.</div></div>
      <div class="actions"><button class="btn" id="sample-hi" title="Hindi (Devanagari) sample">${icon("languages", "sm")} हिंदी sample</button><button class="btn" id="sample-hg" title="Hinglish sample">${icon("languages", "sm")} Hinglish sample</button><button class="btn" id="sample">${icon("flask-conical", "sm")} <span id="sample-l">Try a sample</span></button></div></div>
    <div class="type-chips" id="types" role="tablist" aria-label="Content type">${Object.entries(TYPES).map(([k, t]) =>
      `<button class="chip ${k === ctype ? "on" : ""}" role="tab" aria-selected="${k === ctype}" data-type="${k}">${icon(t.ic, "sm")} ${t.label}</button>`).join("")}</div>
    <div class="split">
      <div class="card"><div class="card-b">
        <div class="grid g2"><div class="field"><label class="f" for="t">Title</label><input class="input" id="t" placeholder="e.g. Diwali launch poster"></div>
          <div class="field"><label class="f" for="ch">Channel</label><select class="select" id="ch">${CHANNELS.map((c) => `<option>${c}</option>`).join("")}</select></div></div>
        <div class="field" id="subj-f"><label class="f" for="subj">Subject line</label><input class="input" id="subj" placeholder="Email subject"></div>
        <div class="field"><label class="f" for="b" id="b-l">Caption / copy</label><textarea class="textarea" id="b" style="min-height:170px" placeholder="Paste the post caption, email copy or ad text…"></textarea></div>
        <div class="field" id="alt-f"><label class="f" for="alt">Image alt text</label><textarea class="textarea" id="alt" style="min-height:64px" placeholder="Describe the image for screen-reader users"></textarea><div class="hint">Required for every image (guideline G-A11Y-01).</div></div>
        <label class="toggle"><input type="checkbox" id="conf"><span class="sl"></span><span><b>Confidential</b> <span class="muted small">— never send this content to the external AI service. Rule checks still run locally.</span></span></label>
      </div></div>
      <div class="stack">
        <div class="card" id="files-card"><div class="card-h"><h2>${icon("upload-cloud", "sm")} Files</h2></div><div class="card-b">
          <label class="drop" id="drop">${icon("image-plus")}<div style="margin-top:6px"><b>Drop files or click to upload</b></div><div class="small muted">PNG, JPG, WEBP, PDF or TXT · up to 15 MB</div>
            <input type="file" id="fi" multiple accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md" hidden></label>
          <div class="files" id="files"></div>
          <div class="hint">Mark the logo file you placed in the creative as <b>Logo used</b>, so it can be compared with the official logo.</div>
        </div></div>
        <div class="card"><div class="card-b">
          <div class="row"><button class="btn" id="save">${icon("save", "sm")} Save draft</button><button class="btn primary right" id="go">${icon("sparkles", "sm")} Save & run brand review</button></div>
          <p class="small muted" style="margin:10px 0 0">Nothing is published. The review only reads your content and the approved Brand Brain.</p>
        </div></div>
      </div>
    </div>`;
  const fi = $("#fi"), drop = $("#drop");
  fi.onchange = () => addFiles([...fi.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles([...e.dataTransfer.files]); };
  $("#sample").onclick = loadSample;
  $("#save").onclick = () => save(false);
  $("#go").onclick = () => save(true);
  $("#types").onclick = (e) => { const b = e.target.closest("[data-type]"); if (b) setType(b.dataset.type); };
  setType(ctype);
  $("#sample-hi").onclick = () => loadSample("hi");
  $("#sample-hg").onclick = () => loadSample("hinglish");
  const sq = qs.get("sample");
  if (sq) loadSample(["hi", "hinglish"].includes(sq) ? sq : undefined).then(() => { if (qs.get("run")) save(true); });
}

function setType(k) {
  ctype = k;
  const t = TYPES[k];
  document.querySelectorAll("#types [data-type]").forEach((b) => { b.classList.toggle("on", b.dataset.type === k); b.setAttribute("aria-selected", b.dataset.type === k); });
  $("#subj-f").hidden = !t.subject;
  $("#alt-f").hidden = !t.alt;
  $("#files-card").hidden = !t.files;
  $("#b-l").textContent = t.body;
  $("#b").placeholder = t.ph;
  $("#ch").value = t.channel;
  if (!t.files && files.length) { files = []; paintFiles(); }
  $("#sample-l").textContent = `Try a sample ${t.label.toLowerCase()}`;
}

function addFiles(list) {
  for (const f of list) {
    const mime = guessMime(f);
    if (mime.startsWith("text/") && !$("#b").value.trim()) {
      f.text().then((t) => { $("#b").value = t; toast(`Loaded caption from ${f.name}`); });
      continue;
    }
    files.push({ file: f, mime, kind: /logo/i.test(f.name) ? "logo" : mime === "application/pdf" ? "pdf" : "poster", url: mime.startsWith("image/") ? URL.createObjectURL(f) : null });
  }
  paintFiles();
}

function paintFiles() {
  $("#files").innerHTML = files.map((f, i) => `<div class="file">${f.url ? `<img src="${f.url}" alt="">` : icon("file-text")}
    <div class="nm" title="${esc(f.file.name)}">${esc(f.file.name)}<div class="small muted">${(f.file.size / 1024).toFixed(0)} KB</div></div>
    ${f.mime.startsWith("image/") ? `<select class="select" data-k="${i}"><option value="poster" ${f.kind === "poster" ? "selected" : ""}>Creative / poster</option><option value="logo" ${f.kind === "logo" ? "selected" : ""}>Logo used</option></select>` : `<span class="pill">PDF</span>`}
    <button class="btn ghost sm" data-rm="${i}" aria-label="Remove">${icon("trash-2", "sm")}</button></div>`).join("");
  $("#files").onchange = (e) => { const s = e.target.closest("[data-k]"); if (s) files[+s.dataset.k].kind = s.value; };
  $("#files").onclick = (e) => { const b = e.target.closest("[data-rm]"); if (b) { files.splice(+b.dataset.rm, 1); paintFiles(); } };
  icons();
}

async function loadSample(lang) {
  if (lang) {  // Hindi / Hinglish text samples (Round 3: multilingual checks)
    setType("post");
    files = []; paintFiles();
    const s = SAMPLES[lang];
    $("#t").value = s.title; $("#ch").value = s.channel; $("#b").value = s.body; $("#alt").value = ""; $("#subj").value = "";
    toast(`${lang === "hi" ? "Hindi" : "Hinglish"} sample loaded: a fictional draft with deliberate brand mistakes`);
    return;
  }
  try {
    const get = async (n, type) => new File([await (await fetch(`/demo/${n}`)).blob()], n, { type });
    files = [];
    $("#alt").value = "";
    $("#subj").value = "";
    if (ctype === "post") {
      $("#t").value = "Diwali launch poster";
      $("#ch").value = "Instagram";
      $("#b").value = await (await fetch("/demo/diwali_caption.txt")).text();
      addFiles([await get("diwali_poster.png", "image/png"), await get("logo_used_in_poster.png", "image/png")]);
    } else if (ctype === "doc") {
      $("#t").value = "Dealer brochure (agency draft)";
      $("#ch").value = "Print";
      $("#b").value = "";
      addFiles([await get("Voltaro_Dealer_Brochure_draft.pdf", "application/pdf")]);
    } else {
      const s = SAMPLES[ctype];
      $("#t").value = s.title;
      $("#ch").value = s.channel;
      $("#b").value = s.body;
      if (s.subject) $("#subj").value = s.subject;
      paintFiles();
    }
    toast(`Sample ${TYPES[ctype].label.toLowerCase()} loaded: a fictional draft with deliberate brand mistakes`);
  } catch (e) { toast("Could not load sample files: " + e.message, "err"); }
}

async function save(review) {
  const btns = [$("#save"), $("#go")];
  btns.forEach((b) => (b.disabled = true));
  const res = await guard(async () => {
    const ids = [];
    for (const f of files) {
      const up = await api("/api/uploads", { method: "POST", body: { name: f.file.name, mime: f.mime, kind: f.kind, data: await fileToB64(f.file) } });
      ids.push(up.id);
    }
    const t = TYPES[ctype];
    // The subject line is part of what readers see, so it is reviewed with the body.
    const subj = t.subject ? $("#subj").value.trim() : "";
    const body = (subj ? `Subject: ${subj}\n\n` : "") + $("#b").value;
    return api("/api/content", { method: "POST", body: { title: $("#t").value || `New ${t.label.toLowerCase()}`, channel: $("#ch").value, body,
      alt_text: t.alt ? $("#alt").value : "", confidential: $("#conf").checked, attachments: t.files ? ids : [] } });
  });
  btns.forEach((b) => (b.disabled = false));
  if (!res) return;
  if (!review) { toast("Draft saved", "ok"); location.hash = `#/reports/${res.id}`; return; }
  location.hash = `#/reports/${res.id}?run=1`;
}
