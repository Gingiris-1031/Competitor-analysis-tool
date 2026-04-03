function renderProductHunt(ph) {
    const container = document.getElementById('section-producthunt');
    if (!ph || !ph.found) {
        container.innerHTML = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
            <h3 class="text-lg font-semibold mb-2">🏆 Product Hunt</h3>
            <p class="text-sm text-gray-500">${ph && ph.note ? esc(ph.note) : '未在 Product Hunt 上找到该产品'}</p>
        </div>`;
        return;
    }

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-4">🏆 Product Hunt 表现</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">Launch 日期</div><div class="text-sm font-mono text-blue-300 mt-1">${esc(ph.launch_date)}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">Upvotes</div><div class="text-sm font-mono text-orange-300 mt-1">⬆ ${(ph.votes||0).toLocaleString()}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">评论数</div><div class="text-sm font-mono text-green-300 mt-1">💬 ${(ph.comments||0).toLocaleString()}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">评分</div><div class="text-sm font-mono text-yellow-300 mt-1">${ph.reviews_rating ? '⭐ ' + ph.reviews_rating.toFixed(1) + ' (' + ph.reviews_count + ')' : 'N/A'}</div></div>
        </div>

        <div class="bg-gray-800 rounded-lg p-4 mb-4">
            <div class="text-sm font-medium text-white mb-1">${esc(ph.name)}</div>
            <div class="text-xs text-blue-300 mb-2">${esc(ph.tagline)}</div>
            ${ph.description ? `<div class="text-xs text-gray-400">${esc(ph.description)}</div>` : ''}
        </div>

        <div class="flex flex-wrap gap-4 text-xs text-gray-400">`;

    if (ph.topics && ph.topics.length) {
        html += `<div><span class="text-gray-500">Topics:</span> ${ph.topics.map(t => `<span class="bg-gray-800 px-1.5 py-0.5 rounded ml-1">${esc(t)}</span>`).join('')}</div>`;
    }
    if (ph.makers && ph.makers.length) {
        html += `<div><span class="text-gray-500">Makers:</span> ${ph.makers.map(m => `<span class="ml-1">${esc(m.name)}</span>`).join(', ')}</div>`;
    }
    if (ph.url) {
        html += `<a href="${esc(ph.url)}" target="_blank" class="text-blue-400 hover:underline font-medium">🔗 查看 Product Hunt 页面 ↗</a>`;
    }
    if (ph.website) {
        html += `<a href="${esc(ph.website)}" target="_blank" class="text-blue-400 hover:underline ml-4">🌐 官网 ↗</a>`;
    }

    html += `</div>`;

    // Other launches (multi-launch support)
    if (ph.other_launches && ph.other_launches.length > 0) {
        html += `<div class="mt-4 pt-4 border-t border-gray-700">
            <div class="text-xs font-semibold text-gray-400 mb-2">🚀 其他 Launch（共 ${ph.other_launches.length + 1} 次）</div>
            <div class="space-y-1.5">`;
        for (const ol of ph.other_launches) {
            html += `<div class="flex items-center justify-between bg-gray-700/50 rounded px-3 py-2">
                <div>
                    <span class="text-xs text-gray-200">${esc(ol.name || '')}</span>
                    ${ol.tagline ? `<span class="text-[10px] text-gray-500 ml-2">${esc(ol.tagline.slice(0,60))}</span>` : ''}
                </div>
                <div class="flex items-center gap-3 text-[10px] shrink-0 ml-2">
                    <span class="text-orange-300 font-mono">⬆ ${(ol.votes || 0).toLocaleString()}</span>
                    <span class="text-gray-500 font-mono">${esc(ol.launch_date || '')}</span>
                    ${ol.url ? `<a href="${esc(ol.url)}" target="_blank" class="text-blue-400 hover:underline">↗</a>` : ''}
                </div>
            </div>`;
        }
        html += `</div></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
