function renderWebsite(ws) {
    const container = document.getElementById('section-website');
    const timeline = ws.deep_timeline || [];
    const current = ws.current || {};
    const allPoints = [...timeline.filter(t => !t.error && t.date), ...(current && !current.error ? [current] : [])];

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

    // Timeline table - only show if we have actual snapshots (not just current)
    const hasSnapshots = allPoints.filter(p => !p.is_current && p.date).length > 0;
    if (allPoints.length > 0 && hasSnapshots) {
        html += `<div class="overflow-x-auto mb-6"><table class="w-full text-xs border-collapse min-w-[800px]">
            <thead><tr class="bg-gray-800">
                <th class="sticky left-0 bg-gray-800 z-10 text-left px-3 py-2 text-gray-400 min-w-[100px]">维度</th>`;
        for (const p of allPoints) {
            const label = p.is_current ? '📍 当前' : (p.date || '—');
            const link = p.archive_url && !p.is_current ? `<a href="${esc(p.archive_url)}" target="_blank" class="text-blue-400 hover:underline">${label} ↗</a>` : label;
            html += `<th class="px-3 py-2 text-gray-300 min-w-[180px] border-l border-gray-700">${link}</th>`;
        }
        html += `</tr></thead><tbody>`;

        // Slogan row
        html += `<tr class="border-t border-gray-800"><td class="sticky left-0 bg-gray-900 z-10 px-3 py-2 font-medium text-gray-300">Slogan</td>`;
        for (const p of allPoints) {
            html += `<td class="px-3 py-2 border-l border-gray-800 text-blue-300">${esc((p.slogan||'').substring(0,60))}</td>`;
        }
        html += `</tr>`;

        // Structure row
        html += `<tr class="border-t border-gray-800 bg-gray-950/50"><td class="sticky left-0 bg-gray-900 z-10 px-3 py-2 font-medium text-gray-300">官网结构</td>`;
        for (const p of allPoints) {
            const parts = (p.structure_summary||[]).slice(0,6);
            html += `<td class="px-3 py-2 border-l border-gray-800"><ul class="space-y-0.5">`;
            for (const part of parts) { html += `<li class="text-gray-400">• ${esc(part.substring(0,50))}</li>`; }
            html += `</ul></td>`;
        }
        html += `</tr>`;

        // Features row
        html += `<tr class="border-t border-gray-800"><td class="sticky left-0 bg-gray-900 z-10 px-3 py-2 font-medium text-gray-300">功能检测</td>`;
        for (const p of allPoints) {
            const f = p.features || {};
            const labels = {pricing:'💰定价',blog:'📝博客',docs:'📖文档',changelog:'📋更新',faq:'❓FAQ',trial:'🎯试用',demo:'🖥Demo',logos:'🏢Logo墙',case_study:'📊案例',privacy:'🔒隐私',terms:'📄条款'};
            html += `<td class="px-3 py-2 border-l border-gray-800"><div class="flex flex-wrap gap-1">`;
            for (const [k,v] of Object.entries(labels)) {
                if (f[k]) html += `<span class="bg-green-900/40 text-green-300 px-1.5 py-0.5 rounded text-[10px]">${v}</span>`;
            }
            html += `</div></td>`;
        }
        html += `</tr>`;

        // Social links row
        html += `<tr class="border-t border-gray-800 bg-gray-950/50"><td class="sticky left-0 bg-gray-900 z-10 px-3 py-2 font-medium text-gray-300">社媒外链</td>`;
        for (const p of allPoints) {
            const sl = p.social_links || {};
            const keys = Object.keys(sl);
            html += `<td class="px-3 py-2 border-l border-gray-800">`;
            if (keys.length) {
                for (const k of keys) {
                    const info = sl[k];
                    html += `<div class="text-gray-400">🔗 ${k}: ${esc(info.handle||'')}</div>`;
                }
            } else { html += `<span class="text-gray-600">无</span>`; }
            html += `</td>`;
        }
        html += `</tr>`;

        // Section count row
        html += `<tr class="border-t border-gray-800"><td class="sticky left-0 bg-gray-900 z-10 px-3 py-2 font-medium text-gray-300">板块数</td>`;
        for (const p of allPoints) {
            html += `<td class="px-3 py-2 border-l border-gray-800 text-gray-400">${p.section_count||'?'} 个</td>`;
        }
        html += `</tr></tbody></table></div>`;
    }

    // Current site summary (always show if available)
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
