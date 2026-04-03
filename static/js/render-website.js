function renderWebsite(ws) {
    const container = document.getElementById('section-website');
    const timeline = ws.deep_timeline || [];
    const current = ws.current || {};
    const allPoints = [...timeline.filter(t => !t.error && t.date), ...(current && !current.error && current.date ? [current] : [])];

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">🌐 官网演变分析</h3>
            <span class="text-[10px] bg-amber-900/40 text-amber-300 border border-amber-700/40 px-2.5 py-1 rounded-full font-medium">🔍 Wayback Machine 独家数据</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">域名</div><div class="text-sm font-mono mt-1">${esc(ws.domain)}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">首次出现</div><div class="text-sm font-mono mt-1">${esc(ws.first_seen)}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">历史快照</div><div class="text-sm font-mono mt-1">${ws.total_snapshots} 个</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-xs text-gray-400">分析快照</div><div class="text-sm font-mono mt-1">${allPoints.length} 个</div></div>
        </div>`;

    // Horizontal timeline cards — only show if we have actual snapshots (not just current)
    const hasSnapshots = allPoints.filter(p => !p.is_current && p.date).length > 0;
    if (allPoints.length > 0 && hasSnapshots) {
        html += `<div class="mb-6">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">📸 官网演变时间线</h4>
            <div class="ws-timeline-scroll" style="display:flex; gap:16px; overflow-x:auto; padding-bottom:12px; scroll-snap-type:x mandatory; -webkit-overflow-scrolling:touch;">`;

        for (let i = 0; i < allPoints.length; i++) {
            const p = allPoints[i];
            const isCurrent = !!p.is_current;
            const label = isCurrent ? '当前' : (p.date || '—');
            const previewUrl = p.preview_url || '';
            const archiveUrl = p.archive_url || '';
            const f = p.features || {};
            const featureLabels = {pricing:'💰定价',blog:'📝博客',docs:'📖文档',changelog:'📋更新',faq:'❓FAQ',trial:'🎯试用',demo:'🖥Demo',logos:'🏢Logo墙',case_study:'📊案例'};

            // Active features as array
            const activeFeatures = Object.entries(featureLabels).filter(([k]) => f[k]);

            html += `<div style="flex:none; width:260px; scroll-snap-align:start;">
                <div class="bg-gray-800 rounded-xl border ${isCurrent ? 'border-blue-500/60' : 'border-gray-700/60'} overflow-hidden h-full flex flex-col" style="min-height:320px;">`;

            // Visual header — mini site wireframe representation
            html += `<div class="relative" style="height:120px; overflow:hidden;">`;

            // Gradient background based on era
            const year = parseInt((p.date || '2024').substring(0, 4));
            const hue = Math.min(220, Math.max(180, (year - 2015) * 6 + 180));
            html += `<div style="width:100%; height:100%; background: linear-gradient(135deg, hsl(${hue},40%,12%) 0%, hsl(${hue},30%,18%) 100%); padding:10px;">`;

            // Mini wireframe: nav bar + hero text
            const navItems = (p.nav_links || []).slice(0, 4);
            if (navItems.length) {
                html += `<div style="display:flex; gap:6px; margin-bottom:8px;">`;
                for (const n of navItems) {
                    html += `<div style="background:rgba(255,255,255,0.08); border-radius:3px; padding:2px 5px; font-size:8px; color:rgba(255,255,255,0.35); max-width:50px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(n)}</div>`;
                }
                html += `</div>`;
            }

            // Slogan as hero text
            const slogan = (p.slogan || '').substring(0, 60);
            if (slogan) {
                html += `<div style="font-size:11px; font-weight:600; color:rgba(255,255,255,0.7); line-height:1.3; margin-top:6px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">${esc(slogan)}</div>`;
            }

            // Feature dots row
            if (activeFeatures.length) {
                html += `<div style="display:flex; gap:3px; margin-top:auto; position:absolute; bottom:10px; left:10px;">`;
                for (let j = 0; j < Math.min(activeFeatures.length, 6); j++) {
                    html += `<div style="width:6px; height:6px; border-radius:50%; background:rgba(74,222,128,0.5);"></div>`;
                }
                if (activeFeatures.length > 6) {
                    html += `<div style="font-size:8px; color:rgba(255,255,255,0.3);">+${activeFeatures.length - 6}</div>`;
                }
                html += `</div>`;
            }

            html += `</div>`; // end gradient bg

            // Current badge
            if (isCurrent) {
                html += `<div style="position:absolute; top:6px; right:6px; background:#2563eb; color:white; font-size:9px; font-weight:700; padding:2px 8px; border-radius:4px;">📍 当前</div>`;
            }

            // Preview button overlay
            if (previewUrl || (isCurrent && archiveUrl)) {
                const targetUrl = isCurrent ? archiveUrl : (previewUrl || archiveUrl);
                html += `<button onclick="wsPreviewSite('${esc(targetUrl)}', '${esc(label)}')" style="position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); border:1px solid rgba(255,255,255,0.15); color:rgba(255,255,255,0.7); font-size:9px; padding:3px 8px; border-radius:4px; cursor:pointer;" onmouseenter="this.style.background='rgba(37,99,235,0.7)'" onmouseleave="this.style.background='rgba(0,0,0,0.6)'">👁 预览</button>`;
            }

            html += `</div>`; // end visual header

            // Card body
            html += `<div style="padding:12px; display:flex; flex-direction:column; gap:8px; flex:1;">`;

            // Date + archive link
            html += `<div style="display:flex; align-items:center; justify-content:space-between;">
                <span style="font-size:13px; font-weight:600; color:${isCurrent ? '#60a5fa' : '#e5e7eb'};">${esc(label)}</span>`;
            if (archiveUrl && !isCurrent) {
                html += `<a href="${esc(archiveUrl)}" target="_blank" rel="noopener" style="font-size:10px; color:#6b7280; text-decoration:none;" onmouseenter="this.style.color='#60a5fa'" onmouseleave="this.style.color='#6b7280'">↗ 存档</a>`;
            }
            html += `</div>`;

            // Structure summary (top 3)
            const parts = (p.structure_summary || []).slice(0, 3);
            if (parts.length) {
                html += `<div style="flex:1;">`;
                for (const part of parts) {
                    html += `<div style="font-size:10px; color:#9ca3af; line-height:1.5; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">· ${esc(part.substring(0, 45))}</div>`;
                }
                html += `</div>`;
            } else {
                html += `<div style="flex:1;"></div>`;
            }

            // Section count
            html += `<div style="font-size:10px; color:#6b7280;">📄 ${p.section_count || 0} 个板块</div>`;

            // Feature badges
            if (activeFeatures.length) {
                html += `<div style="display:flex; flex-wrap:wrap; gap:4px;">`;
                for (const [, v] of activeFeatures) {
                    html += `<span style="background:rgba(22,101,52,0.3); color:#86efac; padding:1px 6px; border-radius:4px; font-size:9px;">${v}</span>`;
                }
                html += `</div>`;
            }

            // Social links found in this snapshot
            const sl = p.social_links || {};
            const slKeys = Object.keys(sl);
            if (slKeys.length) {
                html += `<div style="display:flex; flex-wrap:wrap; gap:3px;">`;
                for (const k of slKeys) {
                    html += `<span style="background:rgba(55,65,81,0.5); color:#9ca3af; padding:1px 5px; border-radius:3px; font-size:9px;">🔗 ${esc(k)}</span>`;
                }
                html += `</div>`;
            }

            html += `</div>`; // end card body
            html += `</div>`; // end card
            html += `</div>`; // end snap container
        }

        html += `</div>`; // end scroll container
        html += `<div style="text-align:center; font-size:10px; color:#4b5563; margin-top:4px;">← 横向滑动查看更多快照 →</div>`;
        html += `</div>`; // end timeline section
    }

    // Current site summary (only show if no snapshots — fallback view)
    if (!hasSnapshots && current && !current.error) {
        html += `<div class="mb-4"><h4 class="text-sm font-semibold text-gray-300 mb-2">📍 当前官网</h4>
            <div class="bg-gray-800 rounded-lg p-4 space-y-2">
                <div class="text-sm"><span class="text-gray-400">Slogan:</span> <span class="text-blue-300">${esc(current.slogan||'N/A')}</span></div>
                <div class="text-sm"><span class="text-gray-400">标题:</span> ${esc(current.title||'N/A')}</div>
                ${current.meta_description ? `<div class="text-xs text-gray-400">${esc(current.meta_description)}</div>` : ''}
                <div class="flex flex-wrap gap-1.5 mt-2">`;
        const features = current.features || {};
        const labels = {pricing:'💰定价',blog:'📝博客',docs:'📖文档',changelog:'📋更新',faq:'❓FAQ',trial:'🎯试用',demo:'🖥Demo',logos:'🏢Logo墙',case_study:'📊案例',privacy:'🔒隐私',terms:'📄条款'};
        for (const [k,v] of Object.entries(labels)) {
            if (features[k]) html += `<span class="bg-green-900/40 text-green-300 px-1.5 py-0.5 rounded text-[10px]">${v}</span>`;
            else html += `<span class="bg-gray-700/40 text-gray-500 px-1.5 py-0.5 rounded text-[10px]">${v}</span>`;
        }
        html += `</div>`;
        if (current.headings_h2 && current.headings_h2.length) {
            html += `<div class="mt-2"><span class="text-xs text-gray-400">页面板块:</span><div class="flex flex-wrap gap-1 mt-1">`;
            for (const h of current.headings_h2.slice(0,8)) { html += `<span class="bg-gray-700 text-xs px-2 py-0.5 rounded">${esc(h)}</span>`; }
            html += `</div></div>`;
        }
        const sl = Object.keys(current.social_links || {});
        if (sl.length) {
            html += `<div class="mt-2"><span class="text-xs text-gray-400">社媒外链:</span> <span class="text-xs text-blue-400">${sl.join(', ')}</span></div>`;
        }
        html += `</div></div>`;
        html += `<div class="text-xs text-yellow-400/60 mb-4">⚠️ Wayback Machine 无历史快照（可能是 JS 渲染站点或重定向域名）</div>`;
    }

    // Key changes
    const changes = ws.key_changes || [];
    if (changes.length) {
        html += `<div class="mt-4"><h4 class="text-sm font-semibold text-gray-300 mb-3">📊 关键变化记录</h4><div class="space-y-3">`;
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

/** Open a Wayback snapshot in an iframe preview modal */
function wsPreviewSite(url, label) {
    if (!url) return;
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed; inset:0; z-index:50; display:flex; flex-direction:column; align-items:center; justify-content:center; background:rgba(0,0,0,0.92);';
    modal.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:space-between; width:90vw; max-width:1200px; margin-bottom:8px;">
            <span style="color:#9ca3af; font-size:13px;">📸 ${label} · 点击外部或按 ESC 关闭</span>
            <div style="display:flex; gap:8px;">
                <a href="${url.replace('if_/', '')}" target="_blank" rel="noopener" style="color:#60a5fa; font-size:12px; text-decoration:none; padding:4px 12px; border:1px solid rgba(96,165,250,0.3); border-radius:6px;">↗ 在新标签打开</a>
                <button onclick="this.closest('div').closest('div').remove()" style="color:#9ca3af; font-size:12px; padding:4px 12px; border:1px solid rgba(255,255,255,0.1); border-radius:6px; cursor:pointer; background:transparent;">✕ 关闭</button>
            </div>
        </div>
        <div style="width:90vw; max-width:1200px; height:75vh; background:#111; border-radius:12px; overflow:hidden; border:1px solid rgba(255,255,255,0.1);">
            <div style="display:flex; align-items:center; justify-content:center; height:100%; color:#6b7280; font-size:13px;" id="ws-preview-loading">⏳ 加载存档页面中...</div>
            <iframe src="${url}" style="width:100%; height:100%; border:none; display:none;" onload="this.style.display='block'; this.previousElementSibling.style.display='none';" onerror="this.previousElementSibling.textContent='❌ 存档页面无法加载，请点击右上角在新标签打开'"></iframe>
        </div>`;
    // Close on background click
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
    // Close on ESC
    const onEsc = (e) => { if (e.key === 'Escape') { modal.remove(); document.removeEventListener('keydown', onEsc); } };
    document.addEventListener('keydown', onEsc);
    document.body.appendChild(modal);
}
