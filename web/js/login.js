// Sign-in screen. Renders into #login and resolves once a session cookie is set.
import { api } from "./api.js";
import { $, esc, icon, icons, initials } from "./ui.js";

const FEATS = [
  ["shield-check", "Grounded compliance reviews", "Every finding cites the approved guideline it comes from."],
  ["graduation-cap", "Learns from your team", "Accept/reject decisions train Inkloom's own feedback model."],
  ["lock-keyhole", "Sealed approvals", "SHA-256 integrity seal catches edits after sign-off."],
];

export function showLogin() {
  return new Promise(async (resolve) => {
    document.body.classList.add("signed-out");
    document.body.classList.remove("booting");
    const root = $("#login");
    root.classList.remove("out");
    root.innerHTML = `
      <section class="login-art" aria-hidden="true">
        <div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div><div class="grid-bg"></div>
        <div class="login-brand"><div class="brand-mark">${icon("feather")}</div>Inkloom AI</div>
        <div class="login-hero">
          <h1>Every word,<br><span>on brand.</span></h1>
          <p>AI brand governance for marketing teams: review, fix and approve content against your own guidelines.</p>
          <div class="login-feats">${FEATS.map(([ic, t, d], i) => `<div class="login-feat" style="--i:${i}"><div class="ic">${icon(ic, "sm")}</div><div><b>${t}</b><span>${d}</span></div></div>`).join("")}</div>
        </div>
        <div class="login-foot">Demo workspace: Voltaro Mobility (fictional organisation)</div>
      </section>
      <section class="login-panel">
        <div class="login-card">
          <div class="login-mobile-brand"><div class="brand-mark">${icon("feather")}</div><b>Inkloom AI</b><span>Every word, on brand.</span></div>
          <h2>Sign in</h2>
          <p class="lead">Welcome back. Sign in to your brand workspace.</p>
          <form id="login-form" novalidate>
            <div class="login-err" id="login-err" role="alert">${icon("alert-circle", "sm")}<span></span></div>
            <div class="lf"><label for="li-email">Work email</label>
              <div class="box">${icon("mail", "sm")}<input id="li-email" type="email" autocomplete="username" placeholder="you@company.com" required></div></div>
            <div class="lf"><label for="li-pw">Password</label>
              <div class="box">${icon("lock", "sm")}<input id="li-pw" type="password" autocomplete="current-password" placeholder="••••••••" required>
              <button type="button" class="eye" id="li-eye" aria-label="Show password">${icon("eye", "sm")}</button></div></div>
            <button class="btn primary login-submit" id="li-go" type="submit">Sign in ${icon("arrow-right", "sm")}</button>
          </form>
          <div id="demo-wrap"></div>
        </div>
      </section>`;
    icons();

    const done = (user) => {
      root.classList.add("out");
      setTimeout(() => { document.body.classList.remove("signed-out"); root.innerHTML = ""; resolve(user); }, 230);
    };
    const err = (msg) => {
      const e = $("#login-err");
      e.classList.remove("show");
      void e.offsetWidth;
      $("span", e).textContent = msg;
      e.classList.add("show");
    };

    $("#li-eye").onclick = () => {
      const pw = $("#li-pw"), show = pw.type === "password";
      pw.type = show ? "text" : "password";
      $("#li-eye").innerHTML = icon(show ? "eye-off" : "eye", "sm");
      $("#li-eye").setAttribute("aria-label", show ? "Hide password" : "Show password");
      icons();
    };
    $("#login-form").onsubmit = async (e) => {
      e.preventDefault();
      const email = $("#li-email").value.trim(), password = $("#li-pw").value;
      if (!email || !password) return err("Enter your email and password.");
      const btn = $("#li-go");
      btn.disabled = true;
      btn.innerHTML = `<span class="spin"></span> Signing in…`;
      try {
        const r = await api("/api/auth/login", { method: "POST", body: { email, password } });
        done(r.user);
      } catch (x) {
        err(x.message);
        btn.disabled = false;
        btn.innerHTML = `Sign in ${icon("arrow-right", "sm")}`;
        icons();
      }
    };

    try {
      const d = await api("/api/auth/demo-accounts");
      if (d.enabled && d.accounts.length) {
        $("#demo-wrap").innerHTML = `<div class="login-or">or try a demo account</div>
          <div class="demo-accts">${d.accounts.map((u, i) => `<button class="demo-acct" style="--i:${i}" data-u="${esc(u.id)}">
            <div class="avatar ${esc(u.role)}">${initials(u.name)}</div><div class="who"><b>${esc(u.name)}</b><span>${esc(u.title)}</span></div>${icon("arrow-right", "sm go")}</button>`).join("")}</div>
          <div class="login-note">${icon("info", "sm")}<span>One-click sign-in for the fictional demo team, so judges can try every role.</span></div>`;
        icons();
        $("#demo-wrap").onclick = async (e) => {
          const b = e.target.closest("[data-u]");
          if (!b) return;
          b.classList.add("busy");
          try { done((await api("/api/auth/demo-login", { method: "POST", body: { user_id: b.dataset.u } })).user); }
          catch (x) { err(x.message); b.classList.remove("busy"); }
        };
      }
    } catch { /* demo accounts are optional */ }
    setTimeout(() => { if (window.matchMedia("(min-width: 961px)").matches) $("#li-email")?.focus(); }, 300);
  });
}
