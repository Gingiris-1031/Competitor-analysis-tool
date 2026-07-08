/* One-click report language toggle for the CLASSIC competitor-analysis report.
 *
 * Self-contained + additive: injects a 🌐 button into the report header and
 * re-renders the "AI Business Insights" section — which holds the entire report
 * narrative (a single large markdown block) — in the other language via
 * POST /api/report/{id}/translate, reusing the existing global renderInsights().
 *
 * Deliberately a standalone file (loaded via one <script> tag) so it never
 * touches app.js / the SPA render code and merges cleanly alongside concurrent
 * index.html work. Does nothing if the report has no translatable AI content.
 */
(function () {
  "use strict";
  var origAi = null;   // original ai_insights object (verdict/source/success/content)
  var origLang = null; // 'en' | 'zh' — the language the report was generated in
  var shown = null;    // currently displayed language
  var cache = {};      // lang -> ai_insights markdown
  var btn = null;

  function jobId() {
    return (typeof currentJobId !== "undefined" && currentJobId) || window.currentJobId || null;
  }
  function hasCJK(s) { return /[一-鿿]/.test(s || ""); }
  function label() { if (btn) btn.textContent = shown === "zh" ? "🌐 EN" : "🌐 中文"; }

  async function pollTranslate(id, target) {
    var deadline = Date.now() + 240000; // 4 min
    while (Date.now() < deadline) {
      var r = await fetch("/api/report/" + encodeURIComponent(id) + "/translate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: target })
      });
      if (r.status === 200) { var o = await r.json(); if (o.docs) return o.docs; throw new Error(o.error || "empty"); }
      if (r.status !== 202) { var e = await r.json().catch(function () { return {}; }); throw new Error(e.error || ("HTTP " + r.status)); }
      await new Promise(function (res) { setTimeout(res, 4000); });
    }
    throw new Error("timeout");
  }

  function renderLang(lang) {
    if (typeof renderInsights !== "function" || !origAi || !cache[lang]) return;
    // Preserve verdict/source/success; swap only the translated narrative.
    renderInsights(Object.assign({}, origAi, { content: cache[lang] }));
    shown = lang; label();
  }

  async function onClick() {
    var id = jobId(); if (!id || !btn) return;
    var target = shown === "zh" ? "en" : "zh";
    if (cache[target]) { renderLang(target); return; }
    btn.disabled = true;
    btn.textContent = shown === "zh" ? "🌐 Translating…" : "🌐 翻译中…";
    try {
      var docs = await pollTranslate(id, target);
      cache[target] = docs.ai_insights || docs[Object.keys(docs)[0]];
      renderLang(target);
    } catch (err) {
      alert((shown === "zh" ? "翻译失败：" : "Translation failed: ") + err.message);
    } finally {
      btn.disabled = false; label();
    }
  }

  async function capture() {
    // Grab the original ai_insights object once (has verdict/source/content).
    if (origAi) return true;
    var id = jobId(); if (!id) return false;
    try {
      var r = await fetch("/api/report/" + encodeURIComponent(id));
      var j = await r.json();
      var rep = j.report || j;
      var ai = (rep.sections || {}).ai_insights || (rep.sections || {}).ai_summary;
      if (!ai || !ai.content) return false; // nothing translatable → no toggle
      origAi = ai;
      origLang = hasCJK(ai.content) ? "zh" : "en";
      shown = origLang;
      cache[origLang] = ai.content;
      return true;
    } catch (e) { return false; }
  }

  async function inject() {
    if (document.getElementById("report-lang-toggle")) return;
    var host = document.getElementById("share-btn");
    if (!host || !host.parentElement) return;
    if (!(await capture())) return;
    btn = document.createElement("button");
    btn.id = "report-lang-toggle";
    btn.className = host.className;      // match the Share button's styling
    btn.style.marginRight = "8px";
    btn.title = "Translate this report";
    btn.addEventListener("click", onClick);
    host.parentElement.insertBefore(btn, host);
    label();
  }

  function watch() {
    var sec = document.getElementById("report-section");
    if (!sec) return;
    var obs = new MutationObserver(function () {
      if (!sec.classList.contains("hidden")) inject();
    });
    obs.observe(sec, { attributes: true, attributeFilter: ["class"] });
    if (!sec.classList.contains("hidden")) inject();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watch);
  else watch();
})();
