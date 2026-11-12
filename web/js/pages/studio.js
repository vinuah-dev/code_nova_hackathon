import { api, fileToB64, guessMime } from "../api.js";
import { $, ago, esc, guard, icon, icons, scoreBadge, statusPill, toast } from "../ui.js";

const CHANNELS = ["Instagram", "LinkedIn", "Website", "Email", "Blog", "WhatsApp", "Display ads", "Search ads", "Print", "Press release"];
let files = [];

export async function render(view, ctx, params) {
  const can = ctx.status.permissions.create.includes(ctx.me.role);
  if (params.mode === "new") return renderNew(view, ctx, can);
  const list = await api("/api/content");
  view.innerHTML = `
    <div class="page-head"><div><h1>Content Studio</h1><div class="sub">Draft, upload and review content before it goes anywhere public.</div></div>
      <div class="actions">${can ? `<a class="btn primary" href="#/studio/new">${icon("plus", "sm")} New content</a>` : `<span class="muted small">Switch to a Creator to add content</span>`}</div></div>
    <div class="card"><table class="t"><thead><tr><th>Content</th><th>Channel</th><th>Owner</th><th>Status</th><th>Score</th><th>Issues</th><th>Updated</th></tr></thead><tbody>
      ${list.map((c) => `<tr class="click" data-href="#/reports/${c.id}">
        <td><b>${esc(c.title)}</b> ${c.is_demo ? `<span class="tag-demo">demo</span>` : ""} ${c.confidential ? icon("lock", "sm") : ""}<div class="small muted">v${c.current_version}</div></td>
        <td>${esc(c.channel || "")}</td><td>${esc(c.owner || "")}</td><td>${statusPill(c.status, c.status_label)}</td>
        <td>${scoreBadge(c.score)}</td><td>${c.analysis_id ? `${c.issues}${c.critical ? ` <span class="pill high">${c.critical} serious</span>` : ""}` : "—"}</td><td class="muted small">${ago(c.updated_at)}</td></tr>`).join("")}
    </tbody></table>${list.length ? "" : `<div class="empty">${icon("inbox")}<div>No content yet.</div></div>`}</div>`;
  view.onclick = (e) => { const tr = e.target.closest("tr[data-href]"); if (tr) location.hash = tr.dataset.href; };
}

// Content types the brief names: a post, an advertisement, an email or a document.
const TYPES = {
  post: { label: "Social post", ic: "message-square", channel: "Instagram", body: "Caption", ph: "Paste the post caption…", alt: true, files: true },
  ad: { label: "Advertisement", ic: "megaphone", channel: "Display ads", body: "Ad copy", ph: "Headline and ad text…", alt: true, files: true },
  email: { label: "Email", ic: "mail", channel: "Email", body: "Email body", ph: "Hi rider,…", alt: false, files: false, subject: true },
  doc: { label: "Document", ic: "file-text", channel: "Press release", body: "Notes or summary (optional)", ph: "Optional: paste text, or upload the PDF on the right…", alt: false, files: true },
};
const SAMPLES = {
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
      <div class="actions"><button class="btn" id="sample">${icon("flask-conical", "sm")} <span id="sample-l">Try a sample</span></button></div></div>
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
  if (qs.get("sample")) loadSample().then(() => { if (qs.get("run")) save(true); });
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

async function loadSample() {
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
