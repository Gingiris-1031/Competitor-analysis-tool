/* render-funding.js — 融资信息渲染模块 */

function renderFunding(data) {
    const el = document.getElementById('section-funding');
    if (!el) return;
    if (!data || !data.found) { el.innerHTML = ''; return; }

    const rounds    = data.rounds    || [];
    const investors = data.investors || [];
    const insights  = data.insights  || [];
    const total     = data.total_raised;
    const latest    = data.latest_round || '';
    const cbUrl     = data.crunchbase_url || '';

    el.innerHTML = `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-white flex items-center gap-2">
                <span>💵</span> 融资信息
            </h3>
            ${cbUrl ? `<a href="${_fuEscAttr(cbUrl)}" target="_blank" rel="noopener"
                class="text-xs text-blue-400 hover:text-blue-300 border border-blue-800 hover:border-blue-600 px-3 py-1 rounded-lg transition-colors">
                Crunchbase ↗
            </a>` : ''}
        </div>

        <!-- Summary badges -->
        <div class="flex flex-wrap gap-3 mb-5">
            ${total ? `<div class="bg-green-950/50 border border-green-800/50 rounded-lg px-4 py-2.5 text-center">
                <div class="text-xs text-green-400 mb-0.5">累计融资</div>
                <div class="text-lg font-bold text-green-300">${_fmtMoney(total)}</div>
            </div>` : ''}
            ${latest ? `<div class="bg-blue-950/50 border border-blue-800/50 rounded-lg px-4 py-2.5 text-center">
                <div class="text-xs text-blue-400 mb-0.5">最近轮次</div>
                <div class="text-lg font-bold text-blue-300">${_fuEsc(latest)}</div>
            </div>` : ''}
            ${rounds.length ? `<div class="bg-gray-800/60 border border-gray-700 rounded-lg px-4 py-2.5 text-center">
                <div class="text-xs text-gray-400 mb-0.5">融资轮次</div>
                <div class="text-lg font-bold text-white">${rounds.length}</div>
            </div>` : ''}
        </div>

        ${rounds.length ? _renderRounds(rounds) : ''}
        ${investors.length ? _renderInvestors(investors) : ''}

        ${insights.length ? `
        <div class="mt-4 space-y-1.5">
            ${insights.map(i => `<div class="text-sm text-gray-300">${_fuEsc(i)}</div>`).join('')}
        </div>` : ''}
    </div>`;
}

function _renderRounds(rounds) {
    const items = rounds.map(r => {
        const amt = r.amount ? `<span class="text-green-400 font-medium">${_fmtMoney(r.amount)}</span>` : '';
        const src = r.source ? `<a href="${_fuEscAttr(r.source)}" target="_blank" rel="noopener" class="text-blue-500 hover:text-blue-400 text-xs">来源 ↗</a>` : '';
        return `
        <div class="flex items-center justify-between py-2 border-b border-gray-800 last:border-0">
            <span class="text-sm font-medium text-white">${_fuEsc(r.round)}</span>
            <div class="flex items-center gap-3">${amt}${src}</div>
        </div>`;
    }).join('');

    return `
    <div class="mb-4">
        <div class="text-xs font-medium text-gray-400 mb-2">融资轮次明细</div>
        <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg px-4 py-1">${items}</div>
    </div>`;
}

function _renderInvestors(investors) {
    const chips = investors.map(inv =>
        `<span class="text-xs bg-gray-800 border border-gray-700 text-gray-300 px-2.5 py-1 rounded-full">${_fuEsc(inv)}</span>`
    ).join('');
    return `
    <div class="mb-4">
        <div class="text-xs font-medium text-gray-400 mb-2">已知投资方</div>
        <div class="flex flex-wrap gap-2">${chips}</div>
    </div>`;
}

function _fmtMoney(n) {
    n = Number(n);
    if (isNaN(n) || n === 0) return '—';
    if (n >= 1e9) return '$' + (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
    return '$' + n;
}

function _fuEsc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}
function _fuEscAttr(s) {
    return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
