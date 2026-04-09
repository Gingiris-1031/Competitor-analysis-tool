function renderProductHunt(ph) {
    const container = document.getElementById('section-producthunt');
    if (!ph || !ph.found) {
        container.innerHTML = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
            <h3 class="text-lg font-semibold mb-2">🏆 Product Hunt</h3>
            <p class="text-sm text-gray-500">${ph && ph.note ? esc(ph.note) : 'Product not found on Product Hunt'}</p>
        </div>`;
        return;
    }

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">🏆 Product Hunt Performance</h3>
            <span class="text-[10px] bg-blue-900/40 text-blue-300 border border-blue-700/40 px-2.5 py-1 rounded-full font-medium">🚀 Product Hunt Deep Analysis</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">Launch Date</div><div class="text-sm font-mono text-blue-300 mt-1">${esc(ph.launch_date)}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">Upvotes</div><div class="text-sm font-mono text-orange-300 mt-1">⬆ ${(ph.votes||0).toLocaleString()}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">Comments</div><div class="text-sm font-mono text-green-300 mt-1">💬 ${(ph.comments||0).toLocaleString()}</div></div>
            <div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">Rating</div><div class="text-sm font-mono text-yellow-300 mt-1">${ph.reviews_rating ? '⭐ ' + ph.reviews_rating.toFixed(1) + ' (' + ph.reviews_count + ')' : 'N/A'}</div></div>
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
        html += `<a href="${esc(ph.url)}" target="_blank" class="text-blue-400 hover:underline font-medium">🔗 View on Product Hunt ↗</a>`;
    }
    if (ph.website) {
        html += `<a href="${esc(ph.website)}" target="_blank" class="text-blue-400 hover:underline ml-4">🌐 Website ↗</a>`;
    }

    html += `</div>`;

    // Launch timeline (chronological view of all launches)
    if (ph.other_launches && ph.other_launches.length > 0) {
        // Build unified list: main launch + other launches, sorted by date ascending
        const allLaunches = [
            { name: ph.name, slug: ph.slug, votes: ph.votes, launch_date: ph.launch_date, url: ph.url, tagline: ph.tagline, is_best: true },
            ...ph.other_launches
        ].sort((a, b) => (a.launch_date || '').localeCompare(b.launch_date || ''));

        html += `<div class="mt-5 pt-5 border-t border-gray-700">
            <div class="text-sm font-semibold text-gray-300 mb-3">📅 Launch Timeline (${allLaunches.length} launches total)</div>
            <div class="relative pl-6 border-l-2 border-gray-700 space-y-4">`;
        for (let i = 0; i < allLaunches.length; i++) {
            const ol = allLaunches[i];
            const isBest = ol.is_best;
            const dotColor = isBest ? 'bg-orange-400' : 'bg-blue-400';
            const ringColor = isBest ? 'ring-orange-400/30' : 'ring-blue-400/30';
            const label = i === 0 ? 'First Launch' : i === allLaunches.length - 1 ? 'Latest Launch' : `Launch #${i + 1}`;
            html += `<div class="relative">
                <div class="absolute -left-[25px] top-1 w-3 h-3 rounded-full ${dotColor} ring-4 ${ringColor}"></div>
                <div class="bg-gray-800/70 rounded-lg px-4 py-3 ${isBest ? 'border border-orange-500/30' : ''}">
                    <div class="flex items-center justify-between mb-1">
                        <div class="flex items-center gap-2">
                            <span class="text-xs font-mono text-blue-300">${esc(ol.launch_date || 'N/A')}</span>
                            <span class="text-[10px] px-1.5 py-0.5 rounded ${isBest ? 'bg-orange-900/50 text-orange-300' : 'bg-gray-700 text-gray-400'}">${label}${isBest ? ' · Top voted' : ''}</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-xs text-orange-300 font-mono">⬆ ${(ol.votes || 0).toLocaleString()}</span>
                            ${ol.url ? `<a href="${esc(ol.url)}" target="_blank" class="text-blue-400 hover:underline text-[10px]">↗</a>` : ''}
                        </div>
                    </div>
                    <div class="text-xs text-gray-200">${esc(ol.name || '')}</div>
                    ${ol.tagline ? `<div class="text-[10px] text-gray-500 mt-0.5">${esc(typeof ol.tagline === 'string' ? ol.tagline.slice(0,80) : '')}</div>` : ''}
                </div>
            </div>`;
        }
        html += `</div></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
