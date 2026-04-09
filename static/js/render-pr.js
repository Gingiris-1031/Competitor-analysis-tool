/* render-pr.js — PR & Media coverage render module */

function renderPR(data) {
    const el = document.getElementById('section-pr');
    if (!el) return;
    if (!data || (!data.found && !data._timed_out && !data.error)) { el.innerHTML = ''; return; }
    if (data._timed_out || (data.error && !data.found)) {
        el.innerHTML = `
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 class="text-base font-semibold text-white flex items-center gap-2 mb-3">
                <span>📰</span> Media & Community Coverage
            </h3>
            <div class="text-sm text-yellow-400/80 bg-yellow-400/5 border border-yellow-400/20 rounded-lg px-4 py-3">
                ⏱ Data retrieval timed out. Please regenerate the report or refresh later.
            </div>
        </div>`;
        return;
    }

    const hn      = data.hn_posts       || [];
    const news    = data.news_articles  || [];
    const press   = data.press_mentions || [];
    const insights = data.insights      || [];
    const total    = data.total_mentions || 0;

    el.innerHTML = `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-white flex items-center gap-2">
                <span>📰</span> Media & Community Coverage
            </h3>
            <span class="text-xs text-gray-500 bg-gray-800 border border-gray-700 px-2.5 py-1 rounded-full">${total} records</span>
        </div>

        ${insights.length ? `
        <div class="flex flex-wrap gap-2 mb-5">
            ${insights.map(i => `<div class="text-xs text-gray-300 bg-gray-800/60 border border-gray-700/50 px-3 py-1.5 rounded-lg">${_prEsc(i)}</div>`).join('')}
        </div>` : ''}

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            ${_renderMentionColumn('🟠 HackerNews', hn, 'hn')}
            ${_renderMentionColumn('📰 Google News', news, 'news')}
            ${_renderMentionColumn('🗞 Tech Media', press, 'press')}
        </div>
    </div>`;
}

function _renderMentionColumn(title, items, type) {
    if (!items || !items.length) {
        return `
        <div class="bg-gray-800/30 border border-gray-700/40 rounded-lg p-4">
            <div class="text-xs font-medium text-gray-500 mb-3">${title}</div>
            <p class="text-xs text-gray-600">No data available</p>
        </div>`;
    }

    const cards = items.slice(0, 5).map(item => {
        const url  = type === 'hn' ? (item.hn_url || item.url) : item.url;
        const pts  = type === 'hn' && item.points ? `<span class="text-orange-400 font-medium">${item.points}pts</span> · ${item.comments}💬 · ` : '';
        const date = item.date ? `<span>${_prEsc(item.date)}</span>` : '';
        const src  = item.source && type !== 'hn' ? `<span class="text-blue-400">${_prEsc(item.source)}</span> · ` : '';
        const snippet = item.snippet ? `<p class="text-xs text-gray-500 mt-1 line-clamp-2">${_prEsc(item.snippet)}</p>` : '';

        return `
        <div class="border-b border-gray-700/40 pb-3 mb-3 last:border-0 last:pb-0 last:mb-0">
            <a href="${_prEscAttr(url)}" target="_blank" rel="noopener"
               class="text-sm text-gray-200 hover:text-white leading-snug block mb-1 transition-colors">
               ${_prEsc(item.title || '—')}
            </a>
            <div class="text-xs text-gray-600 flex flex-wrap gap-1">${pts}${src}${date}</div>
            ${snippet}
        </div>`;
    }).join('');

    return `
    <div class="bg-gray-800/30 border border-gray-700/40 rounded-lg p-4">
        <div class="text-xs font-medium text-gray-400 mb-3">${title} <span class="text-gray-600">(${items.length})</span></div>
        ${cards}
    </div>`;
}

function _prEsc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}
function _prEscAttr(s) {
    return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
