// Motion + mobile helpers. Everything here is decorative: if it fails or the user prefers
// reduced motion, the page still renders in its final state.
import { esc, icon, icons } from "./ui.js";

const mq = window.matchMedia("(max-width: 760px)");
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
export const isMobile = () => mq.matches;
const ease = (t) => 1 - Math.pow(1 - t, 3);

function countUp(el) {
  const node = [...el.childNodes].find((n) => n.nodeType === 3 && /\d/.test(n.textContent));
  if (!node) return;
  const m = node.textContent.match(/^(\D*)(-?\d+(?:\.\d+)?)(.*)$/s);
  if (!m) return;
  const target = parseFloat(m[2]), decimals = (m[2].split(".")[1] || "").length, t0 = performance.now(), dur = 750;
  const step = (now) => {
    const p = Math.min(1, (now - t0) / dur);
    node.textContent = m[1] + (target * ease(p)).toFixed(decimals) + m[3];
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function animateIn(root, { quiet = false } = {}) {
  if (reduce.matches || quiet) return;
  root.classList.remove("enter");
  void root.offsetWidth; // restart CSS animations
  root.classList.add("enter");
  const items = root.querySelectorAll(".page-head, .flow, .tabs, .chips, .grid > *, .split > .stack > *, .stack > .card, .finding, .t tbody tr, .more-tile");
  [...items].slice(0, 28).forEach((el, i) => { el.classList.add("rise"); el.style.setProperty("--i", Math.min(i, 14)); });
  root.querySelectorAll(".kpi .val, .ring .num b, .big-delta").forEach(countUp);
  root.querySelectorAll(".ring circle[data-off]").forEach((c) => {
    c.style.transition = "none";
    c.style.strokeDashoffset = c.getAttribute("stroke-dasharray");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      c.style.transition = "stroke-dashoffset 1s cubic-bezier(.2,.8,.2,1)";
      c.style.strokeDashoffset = c.dataset.off;
    }));
  });
  root.querySelectorAll(".bar-fill").forEach((b, i) => {
    const w = b.style.width;
    if (!w) return;
    b.style.transition = "none";
    b.style.width = "0";
    setTimeout(() => { b.style.transition = ""; b.style.width = w; }, 120 + Math.min(i, 12) * 35);
  });
}

// Bottom sheet (mobile) / centred card (desktop) with drag-to-dismiss.
export function sheet({ title, body, onClick }) {
  const ov = document.createElement("div");
  ov.className = "sheet-ov";
  ov.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <div class="sheet-grab"><span></span></div>
    <div class="sheet-h"><h2>${esc(title)}</h2><button class="btn ghost sm right" data-close aria-label="Close">${icon("x", "sm")}</button></div>
    <div class="sheet-b">${body}</div></div>`;
  const panel = ov.querySelector(".sheet");
  const close = () => {
    ov.classList.add("out");
    setTimeout(() => ov.remove(), reduce.matches ? 0 : 220);
  };
  ov.addEventListener("click", (e) => {
    if (e.target === ov || e.target.closest("[data-close]")) return close();
    onClick && onClick(e, close);
  });
  let y0 = null, dy = 0;
  const grab = ov.querySelector(".sheet-grab");
  grab.addEventListener("pointerdown", (e) => { y0 = e.clientY; grab.setPointerCapture(e.pointerId); panel.style.transition = "none"; });
  grab.addEventListener("pointermove", (e) => { if (y0 == null) return; dy = Math.max(0, e.clientY - y0); panel.style.transform = `translateY(${dy}px)`; });
  grab.addEventListener("pointerup", () => {
    panel.style.transition = "";
    if (dy > 80) close(); else panel.style.transform = "";
    y0 = null; dy = 0;
  });
  document.body.appendChild(ov);
  icons();
  return close;
}

// Material-style ripple on buttons, tabs and tappable cards.
document.addEventListener("pointerdown", (e) => {
  if (reduce.matches) return;
  const t = e.target.closest(".btn, .m-tab, .m-fab, .chip, .more-tile, .user-row, a.card, .nav a");
  if (!t || t.disabled) return;
  const r = t.getBoundingClientRect(), s = Math.max(r.width, r.height) * 1.6;
  const dot = document.createElement("span");
  dot.className = "ripple";
  dot.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px`;
  if (getComputedStyle(t).position === "static") t.style.position = "relative";
  t.style.overflow = "hidden";
  t.appendChild(dot);
  setTimeout(() => dot.remove(), 600);
}, { passive: true });

// Pointer-follow glow on desktop cards.
document.addEventListener("pointermove", (e) => {
  if (isMobile() || reduce.matches) return;
  const c = e.target.closest(".card");
  if (!c) return;
  const r = c.getBoundingClientRect();
  c.style.setProperty("--mx", `${e.clientX - r.left}px`);
  c.style.setProperty("--my", `${e.clientY - r.top}px`);
}, { passive: true });
