import { api, session } from "./api.js";
import { $, esc, icon, icons, initials, toast } from "./ui.js";

const NAV = [
  ["dashboard", "Dashboard", "layout-dashboard", "#/"],
  ["brand", "Brand Brain", "brain", "#/brand"],
  ["studio", "Content Studio", "pen-square", "#/studio"],
  ["reports", "Compliance Reports", "shield-check", "#/reports"],
  ["approvals", "Approval Center", "stamp", "#/approvals"],
  ["intelligence", "Brand Intelligence", "sparkles", "#/intelligence"],
  ["settings", "Settings", "settings", "#/settings"],
];

const ROUTES = [
  [/^\/?$/, "dashboard", "dashboard"],
  [/^\/brand$/, "brand", "brand"],
  [/^\/studio$/, "studio", "studio"],
  [/^\/studio\/new$/, "studio", "studio", { mode: "new" }],
  [/^\/reports$/, "reports", "reports"],
  [/^\/reports\/(\d+)$/, "report", "reports"],
  [/^\/approvals$/, "approvals", "approvals"],
  [/^\/intelligence$/, "intelligence", "intelligence"],
  [/^\/settings$/, "settings", "settings"],
];

export const ctx = { users: [], me: null, status: null, pending: 0 };

async function loadShell() {
  [ctx.users, ctx.status] = await Promise.all([api("/api/users"), api("/api/status")]);
  if (!ctx.users.find((u) => u.id === session.userId)) session.userId = "u-creator";
  ctx.me = ctx.users.find((u) => u.id === session.userId);
  const sel = $("#user-select");
  sel.innerHTML = ctx.users.map((u) => `<option value="${u.id}" ${u.id === ctx.me.id ? "selected" : ""}>${esc(u.name)} — ${esc(u.title)}</option>`).join("");
  sel.onchange = () => { session.userId = sel.value; ctx.me = ctx.users.find((u) => u.id === sel.value); paintMe(); toast(`Now acting as ${ctx.me.name} (${ctx.me.role})`); route(); };
  paintMe();
  const ai = ctx.status.ai_configured;
  $("#ai-pill").innerHTML = ai
    ? `<span class="pill violet" title="Model: ${esc(ctx.status.model)}">${icon("sparkles", "sm")} Claude + Rules</span>`
    : `<span class="pill medium" title="Set ANTHROPIC_API_KEY to enable AI review">${icon("cpu", "sm")} Rule engine mode</span>`;
  $("#side-foot").innerHTML = `<div class="row"><span class="dot ${ai ? "on" : "off"}"></span><b>${ai ? "AI review on" : "AI review off"}</b></div>
    <div style="margin-top:4px">${ai ? `Model <code>${esc(ctx.status.model)}</code>. Content marked confidential is never sent.` : "Deterministic checks only. Add an API key in <code>.env</code> to enable Claude."}</div>`;
}

function paintMe() {
  $("#me-avatar").textContent = initials(ctx.me.name);
  $("#me-avatar").className = `avatar ${ctx.me.role}`;
  $("#me-name").textContent = ctx.me.name;
  $("#me-role").textContent = ctx.me.title;
}

async function paintNav(active) {
  try {
    const list = await api("/api/content");
    ctx.pending = list.filter((c) => c.status === "pending_approval").length;
  } catch { /* nav badge is optional */ }
  $("#nav").innerHTML = NAV.map(([key, label, ic, href]) => `<a href="${href}" class="${key === active ? "active" : ""}">${icon(ic)}<span class="lbl">${label}</span>
    ${key === "approvals" && ctx.pending ? `<span class="count">${ctx.pending}</span>` : ""}</a>`).join("");
}

const pages = {};
async function page(name) {
  if (!pages[name]) pages[name] = await import(`./pages/${name}.js`);
  return pages[name];
}

let routeSeq = 0;
export async function route() {
  const seq = ++routeSeq;
  const path = location.hash.replace(/^#/, "").split("?")[0] || "/";
  let match = null;
  for (const [re, name, nav, extra] of ROUTES) {
    const m = path.match(re);
    if (m) { match = { name, nav, params: { ...(extra || {}), id: m[1] } }; break; }
  }
  if (!match) { location.hash = "#/"; return; }
  paintNav(match.nav);
  const label = NAV.find((n) => n[0] === match.nav)?.[1] || "";
  $("#crumbs").innerHTML = `Voltaro Mobility <span>/</span> <b>${label}</b>`;
  const view = $("#view");
  view.onclick = null;
  view.onchange = null;
  view.oninput = null;
  view.innerHTML = `<div class="stack"><div class="skeleton" style="width:240px;height:26px"></div><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:240px"></div></div>`;
  try {
    const mod = await page(match.name);
    if (seq !== routeSeq) return;
    await mod.render(view, ctx, match.params);
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="banner bad">${icon("alert-triangle", "sm")}<div><b>Something went wrong.</b> ${esc(e.message)}</div></div>`;
  }
  icons();
}

export function crumbs(html) { $("#crumbs").innerHTML = html; }

window.addEventListener("hashchange", route);
loadShell().then(route).catch((e) => {
  $("#view").innerHTML = `<div class="banner bad">${icon("plug-zap", "sm")}<div><b>Cannot load Inkloom.</b> ${esc(e.message)}</div></div>`;
  icons();
});
