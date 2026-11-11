import { api } from "./api.js";
import { $, $$, esc, icon, icons, initials, toast } from "./ui.js";
import { animateIn, isMobile, sheet } from "./motion.js";
import { showLogin } from "./login.js";

const NAV = [
  ["dashboard", "Dashboard", "layout-dashboard", "#/"],
  ["brand", "Brand Brain", "brain", "#/brand"],
  ["studio", "Content Studio", "pen-square", "#/studio"],
  ["reports", "Compliance Reports", "shield-check", "#/reports"],
  ["approvals", "Approval Center", "stamp", "#/approvals"],
  ["intelligence", "Brand Intelligence", "sparkles", "#/intelligence"],
  ["settings", "Settings", "settings", "#/settings"],
];
// Mobile bottom bar: 4 primary destinations + a centre "create" button + More.
const MOBILE_TABS = [
  ["dashboard", "Home", "layout-dashboard", "#/"],
  ["reports", "Reports", "shield-check", "#/reports"],
  ["new", "", "plus", "#/studio/new"],
  ["approvals", "Approvals", "stamp", "#/approvals"],
  ["more", "More", "menu", null],
];
const SHORT = { dashboard: "Dashboard", brand: "Brand Brain", studio: "Studio", reports: "Reports", approvals: "Approvals", intelligence: "Intelligence", settings: "Settings" };

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

export const ctx = { users: [], me: null, status: null, pending: 0, nav: "dashboard", demoLogin: false };

async function loadShell() {
  const [me, users, status] = await Promise.all([api("/api/auth/me"), api("/api/users"), api("/api/status")]);
  ctx.me = me.user;
  ctx.demoLogin = me.demo_login;
  ctx.users = users;
  ctx.status = status;
  paintMe();
  const ai = ctx.status.ai_configured;
  $("#ai-pill").innerHTML = ai
    ? `<span class="pill violet glow" title="Model: ${esc(ctx.status.model)}">${icon("sparkles", "sm")} ${esc(ctx.status.provider_label)} + Rules</span>`
    : `<span class="pill medium" title="Add an AI key to enable AI review">${icon("cpu", "sm")} Rule engine mode</span>`;
  $("#side-foot").innerHTML = `<div class="row"><span class="dot ${ai ? "on" : "off"}"></span><b>${ai ? "AI review on" : "AI review off"}</b></div>
    <div style="margin-top:4px">${ai ? `${esc(ctx.status.provider_label)} · <code>${esc(ctx.status.model)}</code>. Confidential content is never sent.` : "Deterministic checks only. Add an AI key in <code>.env</code> (free Gemini key works) to enable AI review."}</div>`;
  $("#m-ai").className = `dot ${ai ? "on" : "off"}`;
  $("#m-avatar").onclick = openMeSheet;
  $("#me-btn").onclick = openMeSheet;
}

async function switchUser(id) {
  try {
    const r = await api("/api/auth/demo-login", { method: "POST", body: { user_id: id } });
    ctx.me = r.user;
    paintMe();
    toast(`Signed in as ${ctx.me.name} (${ctx.me.role})`);
    route();
  } catch (e) { toast(e.message, "err"); }
}

async function logout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* cookie is cleared anyway */ }
  ctx.me = null;
  lastPath = null;
  toast("You have been signed out", "ok");
  await signIn();
}

function paintMe() {
  for (const el of [$("#me-avatar"), $("#m-avatar")]) {
    el.textContent = initials(ctx.me.name);
    el.className = `avatar ${ctx.me.role}`;
  }
  $("#me-name").textContent = ctx.me.name;
  $("#me-role").textContent = ctx.me.title;
}

function openMeSheet() {
  const ai = ctx.status.ai_configured, me = ctx.me;
  sheet({
    title: "Account",
    body: `<div class="acct-head"><div class="avatar ${esc(me.role)}">${initials(me.name)}</div>
        <div class="who"><b>${esc(me.name)}</b><span>${esc(me.email || "")}</span><span>${esc(me.title)}</span></div></div>
      <div class="banner ${ai ? "info" : "warn"}" style="margin-bottom:12px">${icon(ai ? "sparkles" : "cpu", "sm")}<div>${ai ? `AI review on · ${esc(ctx.status.provider_label)} <code>${esc(ctx.status.model)}</code>` : "Rule engine mode (no AI key)"}</div></div>
      ${ctx.demoLogin ? `<div class="section-lbl" style="margin:6px 0 8px">Switch demo account</div>
      <div class="user-list">${ctx.users.filter((u) => u.email).map((u) => `<button class="user-row ${u.id === me.id ? "on" : ""}" data-u="${u.id}">
        <div class="avatar ${u.role}">${initials(u.name)}</div><div class="who"><b>${esc(u.name)}</b><span>${esc(u.title)}</span></div>
        ${u.id === me.id ? icon("check", "sm right") : ""}</button>`).join("")}</div>` : ""}
      <button class="btn danger logout-btn" data-logout>${icon("log-out", "sm")} Sign out</button>`,
    onClick: (e, close) => {
      if (e.target.closest("[data-logout]")) { close(); logout(); return; }
      const b = e.target.closest("[data-u]");
      if (b && b.dataset.u !== me.id) { close(); switchUser(b.dataset.u); }
    },
  });
}

function openMoreSheet() {
  sheet({
    title: "More",
    body: `<div class="more-grid">${NAV.filter(([k]) => ["brand", "studio", "intelligence", "settings"].includes(k)).map(([k, l, ic, href]) =>
      `<a class="more-tile ${ctx.nav === k ? "on" : ""}" href="${href}"><span class="ic">${icon(ic)}</span>${l}</a>`).join("")}</div>`,
    onClick: (e, close) => { if (e.target.closest("a")) close(); },
  });
}

async function paintNav(active) {
  ctx.nav = active;
  try {
    const list = await api("/api/content");
    ctx.pending = list.filter((c) => c.status === "pending_approval").length;
  } catch { /* nav badge is optional */ }
  $("#nav").innerHTML = `<span class="nav-ind" id="nav-ind"></span>` + NAV.map(([key, label, ic, href]) => `<a href="${href}" class="${key === active ? "active" : ""}" data-key="${key}">${icon(ic)}<span class="lbl">${label}</span>
    ${key === "approvals" && ctx.pending ? `<span class="count">${ctx.pending}</span>` : ""}</a>`).join("");
  const mActive = ["dashboard", "reports", "approvals"].includes(active) ? active : "more";
  $("#m-nav").innerHTML = `<span class="m-ind" id="m-ind"></span>` + MOBILE_TABS.map(([key, label, ic, href]) => key === "new"
    ? `<a class="m-fab" href="${href}" aria-label="New content">${icon(ic)}</a>`
    : `<a class="m-tab ${key === mActive ? "active" : ""}" ${href ? `href="${href}"` : `href="#" data-more`} data-key="${key}">
        <span class="m-ic">${icon(ic)}${key === "approvals" && ctx.pending ? `<i class="m-badge">${ctx.pending}</i>` : ""}</span><span>${label}</span></a>`).join("");
  $("#m-nav [data-more]").onclick = (e) => { e.preventDefault(); openMoreSheet(); };
  icons();
  moveIndicator();
}

function moveIndicator() {
  const a = $("#nav a.active"), ind = $("#nav-ind");
  if (a && ind) { ind.style.transform = `translateY(${a.offsetTop}px)`; ind.style.height = `${a.offsetHeight}px`; ind.style.opacity = 1; }
  const t = $("#m-nav .m-tab.active"), mi = $("#m-ind");
  if (t && mi) { mi.style.transform = `translateX(${t.offsetLeft + t.offsetWidth / 2 - 18}px)`; mi.style.opacity = 1; }
}

const pages = {};
async function page(name) {
  if (!pages[name]) pages[name] = await import(`./pages/${name}.js`);
  return pages[name];
}

let routeSeq = 0;
let lastPath = null;
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
  $("#m-title").textContent = match.params.mode === "new" ? "New content" : SHORT[match.nav] || "";
  const view = $("#view");
  view.onclick = null;
  view.onchange = null;
  view.oninput = null;
  const samePage = path === lastPath;
  lastPath = path;
  if (!samePage) view.classList.remove("enter");
  if (!samePage) view.innerHTML = `<div class="stack"><div class="skeleton" style="width:240px;height:26px"></div><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:240px"></div></div>`;
  try {
    const mod = await page(match.name);
    if (seq !== routeSeq) return;
    await mod.render(view, ctx, match.params);
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="banner bad">${icon("alert-triangle", "sm")}<div><b>Something went wrong.</b> ${esc(e.message)}</div></div>`;
  }
  if (seq !== routeSeq) return;
  icons();
  if (!samePage) {
    window.scrollTo({ top: 0 });
    animateIn(view);
  } else {
    animateIn(view, { quiet: true });
  }
}

export function crumbs(html) {
  $("#crumbs").innerHTML = html;
  const last = $$("#crumbs b").pop();
  if (last && isMobile()) $("#m-title").textContent = last.textContent;
}

async function signIn() {
  await showLogin();
  await start();
}

async function start() {
  try {
    await loadShell();
  } catch (e) {
    if (e.status === 401) return signIn();
    document.body.classList.remove("booting");
    $("#view").innerHTML = `<div class="banner bad">${icon("plug-zap", "sm")}<div><b>Cannot load Inkloom.</b> ${esc(e.message)}</div></div>`;
    icons();
    return;
  }
  document.body.classList.remove("booting");
  lastPath = null;
  route();
}

let signingIn = false;
window.addEventListener("inkloom:signed-out", async () => {
  if (signingIn || document.body.classList.contains("signed-out")) return;
  signingIn = true;
  toast("Your session ended. Please sign in again.", "err");
  try { await signIn(); } finally { signingIn = false; }
});
window.addEventListener("hashchange", () => { if (ctx.me) route(); });
window.addEventListener("resize", () => moveIndicator(), { passive: true });
start();
