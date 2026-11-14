// In-app user-testing feedback: what the tester tried, whether it worked, a 1-5 rating and a comment.
import { api } from "./api.js";
import { $, esc, icon, modal, toast } from "./ui.js";
import { isMobile } from "./motion.js";

let tasks = null;

export async function openFeedback() {
  try { tasks = tasks || await api("/api/feedback/tasks"); } catch { tasks = ["Other"]; }
  let tester = "";
  try { tester = localStorage.getItem("inkloom.tester") || ""; } catch { /* private mode */ }
  const page = location.hash.replace(/\?.*$/, "") || "#/";
  const result = await modal({
    title: `${icon("message-square-heart", "sm")} Share feedback`,
    body: `<p class="ink2" style="margin-top:0">Helping us test Inkloom? Tell us what you tried and how it went. It takes 30 seconds.</p>
      <div class="field"><label class="f" for="fb-name">Your name (optional)</label><input class="input" id="fb-name" value="${esc(tester)}" placeholder="So we can follow up"></div>
      <div class="field"><label class="f" for="fb-task">What were you trying to do?</label>
        <select class="select" id="fb-task">${tasks.map((t) => `<option>${esc(t)}</option>`).join("")}</select></div>
      <div class="field"><span class="f">Did you manage to do it?</span>
        <div class="seg" id="fb-done" role="radiogroup">${[["yes", "Yes"], ["partly", "Partly"], ["no", "No"]].map(([v, l]) =>
          `<button type="button" class="chip" role="radio" aria-checked="false" data-v="${v}">${l}</button>`).join("")}</div></div>
      <div class="field"><span class="f">How easy was it? (1 = very hard, 5 = very easy)</span>
        <div class="stars" id="fb-rate" role="radiogroup">${[1, 2, 3, 4, 5].map((n) =>
          `<button type="button" role="radio" aria-checked="false" aria-label="${n} of 5" data-n="${n}">${icon("star")}</button>`).join("")}</div></div>
      <div class="field"><label class="f" for="fb-c">What confused you or what should change?</label>
        <textarea class="textarea" id="fb-c" style="min-height:80px" placeholder="Anything: a step you got stuck on, a finding that was wrong, an idea…"></textarea></div>`,
    onMount: (ov) => {
      const pick = (root, attr, val) => root.querySelectorAll("[role=radio]").forEach((b) => {
        const on = attr === "n" ? +b.dataset.n <= val : b.dataset.v === val;
        b.classList.toggle("on", on);
        b.setAttribute("aria-checked", attr === "n" ? String(+b.dataset.n === val) : String(on));
      });
      $("#fb-done", ov).onclick = (e) => { const b = e.target.closest("[data-v]"); if (b) { ov.dataset.done = b.dataset.v; pick($("#fb-done", ov), "v", b.dataset.v); } };
      $("#fb-rate", ov).onclick = (e) => { const b = e.target.closest("[data-n]"); if (b) { ov.dataset.rate = b.dataset.n; pick($("#fb-rate", ov), "n", +b.dataset.n); } };
      const map = { "#/studio/new": 0, "#/reports": 1, "#/approvals": 3, "#/brand": 4 };
      const guess = Object.entries(map).find(([k]) => page.startsWith(k));
      if (guess && tasks[guess[1]]) $("#fb-task", ov).value = tasks[guess[1]];
    },
    actions: [{ label: "Cancel", value: null }, {
      label: "Send feedback", cls: "primary",
      onClick: async (ov) => {
        if (!ov.dataset.rate) { toast("Pick a rating from 1 to 5", "err"); return false; }
        const name = $("#fb-name", ov).value.trim();
        try { localStorage.setItem("inkloom.tester", name); } catch { /* ignore */ }
        try {
          await api("/api/feedback", { method: "POST", body: { tester: name, task: $("#fb-task", ov).value, completed: ov.dataset.done || null,
            rating: +ov.dataset.rate, comment: $("#fb-c", ov).value, page, device: isMobile() ? "mobile" : "desktop" } });
          return true;
        } catch (e) { toast(e.message, "err"); return false; }
      },
    }],
  });
  if (result) toast("Thank you! Your feedback was saved.", "ok");
}
