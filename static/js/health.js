/**
 * health.js — On every page load, hit /api/health and surface a red banner
 * if the backend reports degraded status (Supabase init failed, etc.).
 *
 * Mounted on index.html, comparison.html, /report/<id>. Cheap (~1 fetch
 * per pageview) and the only protection against the silent-degrade bug
 * we hit on prod.
 *
 * Note: /api/health always returns HTTP 200; degraded state is in body.status.
 * (We don't 503 because Railway's platform healthcheck may target it and
 * would loop-restart the container.)
 */
(function () {
    function showBanner(text, kind = 'warn') {
        // Don't double-render
        if (document.getElementById('analook-health-banner')) return;
        // Defer until DOM is ready so document.body exists.
        if (!document.body) {
            document.addEventListener('DOMContentLoaded', () => showBanner(text, kind), { once: true });
            return;
        }
        const bg = kind === 'error' ? '#7f1d1d' : '#78350f';
        const fg = kind === 'error' ? '#fecaca' : '#fde68a';
        const div = document.createElement('div');
        div.id = 'analook-health-banner';
        // z-index 50 — above page content but below auth modals (which use
        // higher values). Don't cover login flow.
        div.style.cssText = `position:fixed;top:0;left:0;right:0;z-index:50;
            background:${bg};color:${fg};padding:8px 16px;font-size:13px;
            text-align:center;border-bottom:1px solid rgba(255,255,255,0.1);
            font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;`;
        div.innerHTML = `${text} · <a href="mailto:iris@gingiris.com"
            style="color:${fg};text-decoration:underline">report</a>
            <button onclick="document.getElementById('analook-health-banner').remove()"
                style="float:right;background:transparent;color:${fg};border:0;cursor:pointer;font-size:14px">✕</button>`;
        document.body.appendChild(div);
    }

    // Single health probe at page load. Avoids hot-reloading frenzy if /api/health
    // itself is down.
    fetch('/api/health', { method: 'GET' })
        .then(r => r.json().then(j => ({ status: r.status, body: j })))
        .then(({ status, body }) => {
            if (status === 503 || body.status === 'degraded') {
                showBanner(
                    `⚠️ Analook backend degraded: ${body.warning || 'Supabase misconfigured; reports may not be saved'}`,
                    'error'
                );
            }
        })
        .catch(() => {
            // /api/health unreachable → backend completely down. Show a
            // softer warning since the user can probably see other issues.
            showBanner('⚠️ Cannot reach the Analook backend; some features may be unavailable', 'error');
        });
})();
