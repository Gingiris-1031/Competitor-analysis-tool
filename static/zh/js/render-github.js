/* render-github.js — GitHub OSS 分析渲染模块 */

function renderGithub(data) {
    const el = document.getElementById('section-github');
    if (!el) return;
    if (!data || !data.found) { el.innerHTML = ''; return; }

    const stars = data.stars || 0;
    const forks = data.forks || 0;
    const issues = data.open_issues || 0;
    const contributors = data.contributors || 0;
    const language = data.language || '';
    const license = data.license || '';
    const created = data.created_at || '';
    const pushed = data.pushed_at || '';
    const desc = data.description || '';
    const repoUrl = data.repo_url || '';
    const topics = data.topics || [];
    const insights = data.insights || [];
    const milestones = data.milestones || [];
    const history = data.star_history || [];
    const rel = data.latest_release || null;

    el.innerHTML = `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-base font-semibold text-white flex items-center gap-2">
                <span>⭐</span> GitHub 开源分析
            </h3>
            ${repoUrl ? `<a href="${_escAttr(repoUrl)}" target="_blank" rel="noopener"
                class="text-xs text-blue-400 hover:text-blue-300 border border-blue-800 hover:border-blue-600 px-3 py-1 rounded-lg transition-colors">
                查看仓库 ↗
            </a>` : ''}
        </div>

        ${desc ? `<p class="text-sm text-gray-400 mb-4">${_esc(desc)}</p>` : ''}

        <!-- Core stats -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
            ${_statBadge('⭐', _fmtNum(stars), 'Stars', 'yellow')}
            ${_statBadge('🍴', _fmtNum(forks), 'Forks', 'blue')}
            ${_statBadge('🐛', _fmtNum(issues), 'Open Issues', 'red')}
            ${_statBadge('👥', _fmtNum(contributors), 'Contributors', 'green')}
        </div>

        <!-- Meta row -->
        <div class="flex flex-wrap gap-2 mb-5 text-xs">
            ${language ? `<span class="bg-gray-800 text-gray-300 border border-gray-700 px-2.5 py-1 rounded-full">💻 ${_esc(language)}</span>` : ''}
            ${license ? `<span class="bg-gray-800 text-gray-300 border border-gray-700 px-2.5 py-1 rounded-full">📄 ${_esc(license)}</span>` : ''}
            ${created ? `<span class="bg-gray-800 text-gray-400 border border-gray-700 px-2.5 py-1 rounded-full">🗓 创建 ${_esc(created)}</span>` : ''}
            ${pushed ? `<span class="bg-gray-800 text-gray-400 border border-gray-700 px-2.5 py-1 rounded-full">🔄 最近推送 ${_esc(pushed)}</span>` : ''}
            ${topics.slice(0, 5).map(t => `<span class="bg-indigo-950/60 text-indigo-300 border border-indigo-800/50 px-2.5 py-1 rounded-full">${_esc(t)}</span>`).join('')}
        </div>

        ${rel ? _renderRelease(rel) : ''}
        ${history.length ? _renderStarChart(history, stars) : ''}
        ${milestones.length ? _renderMilestones(milestones) : ''}
        ${insights.length ? _renderInsights(insights) : ''}

        ${data.data_note ? `<p class="text-xs text-gray-600 mt-3 italic">${_esc(data.data_note)}</p>` : ''}
    </div>`;
}

function _statBadge(icon, value, label, color) {
    const colors = {
        yellow: 'bg-yellow-950/40 border-yellow-800/40 text-yellow-300',
        blue:   'bg-blue-950/40 border-blue-800/40 text-blue-300',
        red:    'bg-red-950/40 border-red-800/40 text-red-300',
        green:  'bg-green-950/40 border-green-800/40 text-green-300',
    };
    const cls = colors[color] || colors.blue;
    return `
    <div class="border rounded-lg p-3 text-center ${cls}">
        <div class="text-xl font-bold">${icon} ${value}</div>
        <div class="text-xs opacity-70 mt-0.5">${label}</div>
    </div>`;
}

function _renderRelease(rel) {
    return `
    <div class="bg-gray-800/50 border border-gray-700 rounded-lg px-4 py-3 mb-4 flex items-center justify-between">
        <div class="flex items-center gap-2">
            <span class="text-green-400 text-sm">🚀</span>
            <span class="text-sm text-gray-200">最新发布：<strong class="text-white">${_esc(rel.tag || rel.name || '—')}</strong></span>
            ${rel.date ? `<span class="text-xs text-gray-500">${_esc(rel.date)}</span>` : ''}
        </div>
        ${rel.url ? `<a href="${_escAttr(rel.url)}" target="_blank" rel="noopener" class="text-xs text-blue-400 hover:text-blue-300">查看 ↗</a>` : ''}
    </div>`;
}

function _renderStarChart(history, totalStars) {
    // Show last 30 months max, or all if fewer
    const show = history.slice(-30);
    if (!show.length) return '';

    const maxGain = Math.max(...show.map(h => h.gain || 0), 1);

    const bars = show.map(h => {
        const gain = h.gain || 0;
        const pct = Math.round((gain / maxGain) * 100);
        const isBig = pct >= 60;
        const barColor = isBig ? 'bg-yellow-500' : 'bg-blue-600';
        const cum = h.cumulative || 0;
        const label = h.month ? h.month.slice(2) : '';  // "2022-08" → "22-08"
        return `
        <div class="flex flex-col items-center gap-0.5 flex-1" title="${_esc(h.month)}: +${_fmtNum(gain)} stars（累计 ${_fmtNum(cum)}）">
            <div class="w-full flex items-end justify-center" style="height:60px">
                <div class="${barColor} w-full rounded-t transition-all" style="height:${Math.max(pct, 2)}%"></div>
            </div>
            <span class="text-gray-600 leading-none" style="font-size:9px;writing-mode:vertical-rl;transform:rotate(180deg)">${label}</span>
        </div>`;
    }).join('');

    return `
    <div class="mb-5">
        <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-medium text-gray-400">Star 增长趋势</span>
            <span class="text-xs text-gray-600">⭐ 峰值 = 重大发布节点</span>
        </div>
        <div class="flex items-end gap-px overflow-hidden" style="height:76px">
            ${bars}
        </div>
    </div>`;
}

function _renderMilestones(milestones) {
    const items = milestones.map((m, i) => {
        const isLast = i === milestones.length - 1;
        return `
        <div class="flex items-center gap-3">
            <div class="flex flex-col items-center">
                <div class="w-3 h-3 rounded-full ${isLast ? 'bg-yellow-400' : 'bg-blue-500'} ring-2 ring-gray-900 flex-shrink-0"></div>
                ${!isLast ? '<div class="w-0.5 bg-gray-700 flex-1 my-0.5" style="min-height:16px"></div>' : ''}
            </div>
            <div class="pb-3 flex items-center gap-3">
                <span class="text-yellow-300 font-bold text-sm">${_esc(m.label)}</span>
                <span class="text-gray-400 text-xs">Stars</span>
                <span class="text-gray-300 text-xs bg-gray-800 border border-gray-700 px-2 py-0.5 rounded">${_esc(m.month)}</span>
            </div>
        </div>`;
    }).join('');

    return `
    <div class="mb-5">
        <div class="text-xs font-medium text-gray-400 mb-3">里程碑时间轴</div>
        <div class="pl-2">
            ${items}
        </div>
    </div>`;
}

function _renderInsights(insights) {
    const items = insights.map(ins =>
        `<li class="text-sm text-gray-300 leading-relaxed">${_esc(ins)}</li>`
    ).join('');
    return `
    <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg px-4 py-3 mt-2">
        <div class="text-xs font-medium text-gray-400 mb-2">自动洞察</div>
        <ul class="space-y-1.5 list-none">
            ${items}
        </ul>
    </div>`;
}

function _fmtNum(n) {
    n = Number(n);
    if (isNaN(n)) return '—';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
}

function _esc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

function _escAttr(s) {
    return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
