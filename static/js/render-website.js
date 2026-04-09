function renderWebsite(ws) {
    const container = document.getElementById('section-website');
    const timeline = ws.deep_timeline || [];
    const current = ws.current || {};
    const allPoints = [...timeline.filter(t => !t.error && t.date), ...(current && !current.error && current.date ? [current] : [])];

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">🌐 Website Evolution</h3>
            <span class="text-[10px] bg-amber-900/40 text-amber-300 border border-amber-700/40 px-2.5 py-1 rounded-full font-medium">🔍 Wayback Machine Exclusive Data</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">Domain</div><div class="text-sm font-mono mt-1">${esc(ws.domain)}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">First Seen</div><div class="text-sm font-mono mt-1">${esc(ws.first_seen)}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">Historical Snapshots</div><div class="text-sm font-mono mt-1">${ws.total_snapshots}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">Analyzed Snapshots</div><div class="text-sm font-mono mt-1">${allPoints.length}</div></div>
        </div>`;

    const hasSnapshots = allPoints.filter(p => !p.is_current && p.date).length > 0;
    if (allPoints.length > 0 && hasSnapshots) {
        html += `<div class="mb-6">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">📸 Website Evolution Timeline</h4>
            <div class="ws-timeline-scroll" style="display:flex; gap:16px; overflow-x:auto; padding-bottom:12px; scroll-snap-type:x mandatory; -webkit-overflow-scrolling:touch;">`;

        for (let i = 0; i < allPoints.length; i++) {
            const p = allPoints[i];
            const isCurrent = !!p.is_current;
            const label = isCurrent ? 'Current' : (p.date || '—');
            const previewUrl = p.preview_url || '';
            const archiveUrl = p.archive_url || '';
            const f = p.features || {};
            const featureLabels = {pricing:'💰Pricing',blog:'📝Blog',docs:'📖Docs',changelog:'📋Changelog',faq:'❓FAQ',trial:'🎯Trial',demo:'🖥Demo',logos:'🏢Logos',case_study:'📊Case Study'};
            const activeFeatures = Object.entries(featureLabels).filter(([k]) => f[k]);

            // Build the iframe source URL
            let iframeSrc = '';
            if (isCurrent) {
                iframeSrc = archiveUrl || '';
            } else if (previewUrl) {
                iframeSrc = previewUrl;
            } else if (archiveUrl) {
                // Convert regular archive URL to if_ iframe-safe URL
                iframeSrc = archiveUrl.replace(/\/web\/(\d+)\//, '/web/$1if_/');
            }

            html += `<div style="flex:none; width:300px; scroll-snap-align:start;">
                <div class="bg-gray-800 rounded-xl border ${isCurrent ? 'border-blue-500/60' : 'border-gray-700/60'} overflow-hidden h-full flex flex-col">`;

            // Screenshot area — scaled-down iframe for real visual preview
            html += `<div class="ws-thumb-container" style="position:relative; width:300px; height:188px; overflow:hidden; background:#0a0a0a; cursor:pointer;" onclick="wsOpenFullPreview('${esc(iframeSrc)}', '${esc(label)}')">`;

            if (iframeSrc) {
                // Scaled iframe: render at 1280×800, scale to fit 300×188 (scale ≈ 0.234)
                html += `<iframe src="${esc(iframeSrc)}"
                    style="width:1280px; height:800px; transform:scale(0.234); transform-origin:top left; pointer-events:none; border:none; position:absolute; top:0; left:0;"
                    loading="lazy"
                    sandbox="allow-same-origin"
                    tabindex="-1"
                    onload="this.parentElement.classList.add('ws-thumb-loaded')"
                    onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'"></iframe>
                <div style="display:none; align-items:center; justify-content:center; height:100%; color:#4b5563; font-size:11px;">📷 Screenshot unavailable</div>`;
            } else {
                html += `<div style="display:flex; align-items:center; justify-content:center; height:100%; color:#4b5563; font-size:11px;">📷 No archive link</div>`;
            }

            // Current badge
            if (isCurrent) {
                html += `<div style="position:absolute; top:6px; right:6px; background:#2563eb; color:white; font-size:9px; font-weight:700; padding:2px 8px; border-radius:4px; z-index:2;">📍 Current</div>`;
            }

            // Loading spinner (hidden after iframe loads)
            if (iframeSrc) {
                html += `<div class="ws-thumb-spinner" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; background:#0a0a0a; z-index:1;">
                    <div style="width:20px; height:20px; border:2px solid #333; border-top-color:#666; border-radius:50%; animation:ws-spin 0.8s linear infinite;"></div>
                </div>`;
            }

            html += `</div>`; // end screenshot area

            // Card body
            html += `<div style="padding:12px; display:flex; flex-direction:column; gap:6px; flex:1;">`;

            // Date + archive link
            html += `<div style="display:flex; align-items:center; justify-content:space-between;">
                <span style="font-size:14px; font-weight:600; color:${isCurrent ? '#60a5fa' : '#e5e7eb'};">${esc(label)}</span>`;
            if (archiveUrl && !isCurrent) {
                html += `<a href="${esc(archiveUrl)}" target="_blank" rel="noopener" style="font-size:10px; color:#6b7280; text-decoration:none;" onmouseenter="this.style.color='#60a5fa'" onmouseleave="this.style.color='#6b7280'">↗ Archive</a>`;
            }
            html += `</div>`;

            // Slogan
            const slogan = (p.slogan || '').substring(0, 70);
            if (slogan) {
                html += `<p style="font-size:11px; color:#93c5fd; font-style:italic; line-height:1.4; margin:0;">"${esc(slogan)}"</p>`;
            }

            // Section count + features in one row
            html += `<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:auto;">`;
            html += `<span style="font-size:10px; color:#6b7280;">📄 ${p.section_count || 0} Sections</span>`;
            for (const [, v] of activeFeatures.slice(0, 4)) {
                html += `<span style="background:rgba(22,101,52,0.3); color:#86efac; padding:1px 5px; border-radius:3px; font-size:9px;">${v}</span>`;
            }
            if (activeFeatures.length > 4) {
                html += `<span style="font-size:9px; color:#6b7280;">+${activeFeatures.length - 4}</span>`;
            }
            html += `</div>`;

            html += `</div>`; // end card body
            html += `</div>`; // end card
            html += `</div>`; // end snap container
        }

        html += `</div>`; // end scroll container
        html += `<div style="text-align:center; font-size:10px; color:#4b5563; margin-top:4px;">Scroll to see more →</div>`;
        html += `</div>`;
    }

    // Current site summary (only show if no snapshots — fallback view)
    if (!hasSnapshots && current && !current.error) {
        html += `<div class="mb-4"><h4 class="text-sm font-semibold text-gray-300 mb-2">📍 Current Website</h4>
            <div class="bg-gray-800 rounded-lg p-4 space-y-2">
                <div class="text-sm"><span class="text-gray-400">Slogan:</span> <span class="text-blue-300">${esc(current.slogan||'N/A')}</span></div>
                <div class="text-sm"><span class="text-gray-400">Title:</span> ${esc(current.title||'N/A')}</div>
                ${current.meta_description ? `<div class="text-xs text-gray-400">${esc(current.meta_description)}</div>` : ''}
            </div></div>`;
        html += `<div class="text-xs text-yellow-400/60 mb-4">⚠️ No Wayback Machine snapshots found (may be a JS-rendered site or redirected domain)</div>`;
    }

    // Key changes
    const changes = ws.key_changes || [];
    if (changes.length) {
        html += `<div class="mt-4"><h4 class="text-sm font-semibold text-gray-300 mb-3">📊 Key Changes</h4><div class="space-y-3">`;
        for (const c of changes) {
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-xs text-blue-400 mb-1">${esc(c.from_date)} → ${esc(c.to_date)}</div>
                <ul class="space-y-0.5">`;
            for (const item of c.changes) { html += `<li class="text-xs text-gray-300">• ${esc(item)}</li>`; }
            html += `</ul></div>`;
        }
        html += `</div></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}

/** Click a thumbnail → open full-screen iframe modal */
function wsOpenFullPreview(url, label) {
    if (!url) return;
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed; inset:0; z-index:50; display:flex; flex-direction:column; align-items:center; justify-content:center; background:rgba(0,0,0,0.92);';
    modal.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:space-between; width:90vw; max-width:1200px; margin-bottom:8px;">
            <span style="color:#9ca3af; font-size:13px;">📸 ${label} · Click outside or press ESC to close</span>
            <div style="display:flex; gap:8px;">
                <a href="${url.replace('if_/', '')}" target="_blank" rel="noopener" style="color:#60a5fa; font-size:12px; text-decoration:none; padding:4px 12px; border:1px solid rgba(96,165,250,0.3); border-radius:6px;">↗ Open in new tab</a>
                <button onclick="this.closest('[style*=fixed]').remove()" style="color:#9ca3af; font-size:12px; padding:4px 12px; border:1px solid rgba(255,255,255,0.1); border-radius:6px; cursor:pointer; background:transparent;">✕ Close</button>
            </div>
        </div>
        <div style="width:90vw; max-width:1200px; height:75vh; background:#111; border-radius:12px; overflow:hidden; border:1px solid rgba(255,255,255,0.1);">
            <iframe src="${url}" style="width:100%; height:100%; border:none;"></iframe>
        </div>`;
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
    const onEsc = (e) => { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', onEsc); } };
    document.addEventListener('keydown', onEsc);
    document.body.appendChild(modal);
}
