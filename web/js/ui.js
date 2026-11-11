// Small UI helpers shared by all pages.
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const icon = (name, cls = "") => `<i data-lucide="${name}" class="${cls}"></i>`;

export function icons() { if (window.lucide) window.lucide.createIcons(); }

export function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === "err" ? "alert-circle" : kind === "ok" ? "check-circle-2" : "info", "sm")}<div>${esc(msg)}</div>`;
  $("#toasts").appendChild(el);
  icons();
  setTimeout(() => el.remove(), kind === "err" ? 6500 : 3800);
}

export async function guard(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg, "ok");
    return r;
  } catch (e) {
    toast(e.message, "err");
    return undefined;
  }
}

export function modal({ title, body, actions = [], wide = false, onMount }) {
  return new Promise((resolve) => {
    const ov = document.createElement("div");
    ov.className = "overlay";
    ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
      <div class="modal-h"><h2>${title}</h2><button class="btn ghost sm right" data-x aria-label="Close">${icon("x", "sm")}</button></div>
      <div class="modal-b">${body}</div>
      ${actions.length ? `<div class="modal-f">${actions.map((a, i) => `<button class="btn ${a.cls || ""}" data-a="${i}">${a.label}</button>`).join("")}</div>` : ""}
    </div>`;
    const close = (v) => { ov.remove(); resolve(v); };
    ov.addEventListener("click", async (e) => {
      if (e.target === ov || e.target.closest("[data-x]")) return close(null);
      const b = e.target.closest("[data-a]");
      if (!b) return;
      const a = actions[+b.dataset.a];
      if (a.onClick) {
        b.disabled = true;
        const r = await a.onClick(ov);
        b.disabled = false;
        if (r === false) return;
        return close(r ?? a.value ?? true);
      }
      close(a.value ?? true);
    });
    document.body.appendChild(ov);
    icons();
    onMount && onMount(ov);
    const first = ov.querySelector("textarea, input");
    first && first.focus();
  });
}

export function scoreClass(s) { return s == null ? "" : s >= 85 ? "sb-good" : s >= 60 ? "sb-mid" : "sb-bad"; }
export function scoreColor(s) { return s >= 85 ? "var(--good)" : s >= 60 ? "var(--medium)" : "var(--critical)"; }
export function band(s) { return s >= 85 ? "Ready to publish" : s >= 60 ? "Needs attention" : "High brand risk"; }
export const scoreBadge = (s) => s == null ? `<span class="muted small">Not reviewed</span>` : `<span class="score-badge ${scoreClass(s)}">${Math.round(s)}</span>`;

export function ring(score, size = 132) {
  const r = (size - 14) / 2, c = 2 * Math.PI * r, off = c * (1 - (score || 0) / 100);
  return `<div class="ring" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--line-2)" stroke-width="11"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${scoreColor(score)}" stroke-width="11" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}" data-off="${off}" style="transition:stroke-dashoffset .8s"/></svg>
    <div class="num"><div><b>${Math.round(score)}</b><span>/ 100</span></div></div></div>`;
}

export const SEV = ["critical", "high", "medium", "low"];
export const sevPill = (s) => `<span class="pill ${s}">${s[0].toUpperCase() + s.slice(1)}</span>`;
export const CAT = { claims: "Claims", facts: "Facts", terminology: "Terminology", tone: "Tone & messaging", visual: "Visual identity", accessibility: "Accessibility" };
export const CAT_ICON = { claims: "badge-alert", facts: "file-check-2", terminology: "spell-check", tone: "message-square-text", visual: "palette", accessibility: "accessibility" };
export const statusPill = (st, label) => `<span class="pill st-${st}">${esc(label || st)}</span>`;

export function initials(name) { return (name || "?").split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase(); }
export function avatar(u) { return `<div class="avatar ${u?.role || ""}" title="${esc(u?.name || "")}">${initials(u?.name || "System")}</div>`; }

export function ago(iso) {
  if (!iso) return "";
  const d = new Date(iso), s = (Date.now() - d) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function bars(rows, { max, color = "var(--primary)", fmt = (v) => v } = {}) {
  if (!rows.length) return `<div class="empty small">No data yet</div>`;
  const m = max || Math.max(...rows.map((r) => r.value), 1);
  return `<div class="bars">${rows.map((r) => `<div class="bar-row" title="${esc(r.label)}: ${fmt(r.value)}">
    <div class="name">${esc(r.label)}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${(r.value / m) * 100}%;background:${r.color || color}"></div></div>
    <div class="v">${fmt(r.value)}</div></div>`).join("")}</div>`;
}

export function dims(d, prev) {
  return Object.entries(CAT).map(([k, label]) => {
    const v = d?.[k] ?? 100, p = prev?.[k];
    const delta = p == null ? "" : v - p === 0 ? "" : `<span class="delta ${v > p ? "up" : "down"}">${v > p ? "+" : ""}${Math.round(v - p)}</span>`;
    return `<div class="dim" title="${label}: ${v}/100"><div class="ink2">${label} ${delta}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${v}%;background:${scoreColor(v)}"></div></div><div class="v">${Math.round(v)}</div></div>`;
  }).join("");
}

export function diffHtml(ops) {
  return ops.map((o) => o.op === "equal" ? esc(o.old)
    : (o.old ? `<span class="del">${esc(o.old)}</span>` : "") + (o.new ? `<span class="ins">${esc(o.new)}</span>` : "")).join("");
}
