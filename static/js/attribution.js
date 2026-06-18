/**
 * attribution.js — Analook first-touch acquisition capture
 *
 * MUST load synchronously in <head>, as early as possible, on EVERY page —
 * it has to read utm_* / document.referrer before the SPA (app.js) can strip
 * the query string via history.replaceState.
 *
 * It only writes to localStorage. The send-to-server happens in auth.js once
 * the user is authenticated (POST /api/profile/attribution, write-once).
 *
 * First-touch semantics: the FIRST pageview ever (across the whole site) wins
 * and is locked. Later visits — even with different utm — do NOT overwrite,
 * so we always credit the channel that originally acquired the user.
 */
(function () {
  var KEY = '_analook_ft';

  // Expose the reader FIRST — must exist even on a returning user's visit
  // (where first-touch is already locked and capture below early-returns).
  // auth.js calls this when that returning user finally signs up.
  window._analookAttribution = {
    getFirstTouch: function () {
      try { return JSON.parse(localStorage.getItem(KEY) || 'null'); }
      catch (e) { return null; }
    },
  };

  try {
    // Already captured on an earlier pageview → first-touch is locked. Stop.
    if (localStorage.getItem(KEY)) return;

    var p = new URLSearchParams(location.search || '');
    var ft = {
      utm_source:   (p.get('utm_source')   || '').slice(0, 200),
      utm_medium:   (p.get('utm_medium')   || '').slice(0, 200),
      utm_campaign: (p.get('utm_campaign') || '').slice(0, 200),
      utm_content:  (p.get('utm_content')  || '').slice(0, 200),
      utm_term:     (p.get('utm_term')     || '').slice(0, 200),
      referrer:     (document.referrer     || '').slice(0, 500),
      landing_path: (location.pathname     || '').slice(0, 300),
      ts:           new Date().toISOString(),
    };
    // Always store — a visitor with no utm and no referrer is a legitimate
    // "direct" first-touch and we want to lock that too.
    localStorage.setItem(KEY, JSON.stringify(ft));
  } catch (e) {
    // localStorage can throw in private mode / blocked cookies — attribution
    // is best-effort, never break the page.
  }
})();
