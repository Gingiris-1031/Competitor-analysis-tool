/* render-bizmodel.js — 商业模型 & 商业化进展渲染模块 */

function renderBizmodel(data) {
    const el = document.getElementById('section-bizmodel');
    if (!el) return;
    if (!data || !data.found) { el.innerHTML = ''; return; }

    const model   = data.model_type          || {};
    const revenue = data.revenue_estimate    || {};
    const stage   = data.stage               || '—';
    const levers  = data.monetization_levers || [];
    const insights = data.insights           || [];

    el.innerHTML = `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 class="text-base font-semibold text-white flex items-center gap-2 mb-4">
            <span>🏗</span> 商业模型分析
        </h3>

        <!-- Stage + Model badges -->
        <div class="flex flex-wrap gap-3 mb-5">
            ${_stageBadge(stage)}
            ${(model.primary || []).map(m => `
            <div class="bg-indigo-950/50 border border-indigo-800/50 rounded-lg px-3 py-2">
                <div class="text-xs text-indigo-400 mb-0.5">主要模式</div>
                <div class="text-sm font-medium text-indigo-200">${_bmEsc(m)}</div>
            </div>`).join('')}
            ${(model.secondary || []).map(m => `
            <div class="bg-gray-800/60 border border-gray-700 rounded-lg px-3 py-2">
                <div class="text-xs text-gray-500 mb-0.5">辅助模式</div>
                <div class="text-sm font-medium text-gray-300">${_bmEsc(m)}</div>
            </div>`).join('')}
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            ${_renderRevenue(revenue)}
            ${_renderLevers(levers)}
        </div>

        ${_renderModelTags(model)}

        ${insights.length ? `
        <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg px-4 py-3 mt-4">
            <div class="text-xs font-medium text-gray-400 mb-2">商业化洞察</div>
            <ul class="space-y-1.5">
                ${insights.map(i => `<li class="text-sm text-gray-300 leading-relaxed">${_bmEsc(i)}</li>`).join('')}
            </ul>
        </div>` : ''}
    </div>`;
}

function _stageBadge(stage) {
    let color = 'bg-gray-800/60 border-gray-700 text-gray-300';
    if (stage.includes('规模')) color = 'bg-green-950/50 border-green-800/50 text-green-200';
    else if (stage.includes('PMF')) color = 'bg-blue-950/50 border-blue-800/50 text-blue-200';
    else if (stage.includes('早期商业')) color = 'bg-yellow-950/50 border-yellow-800/50 text-yellow-200';
    else if (stage.includes('0→1')) color = 'bg-orange-950/50 border-orange-800/50 text-orange-200';
    return `
    <div class="border rounded-lg px-3 py-2 ${color}">
        <div class="text-xs opacity-70 mb-0.5">商业化阶段</div>
        <div class="text-sm font-medium">${_bmEsc(stage)}</div>
    </div>`;
}

function _renderRevenue(rev) {
    const low  = rev.arr_low;
    const high = rev.arr_high;
    if (!low || !high) {
        return `
        <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
            <div class="text-xs font-medium text-gray-400 mb-1">ARR 估算</div>
            <p class="text-sm text-gray-500">${_bmEsc(rev.method || '数据不足，无法估算')}</p>
        </div>`;
    }
    return `
    <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
        <div class="text-xs font-medium text-gray-400 mb-2">保守 ARR 估算</div>
        <div class="text-xl font-bold text-white mb-1">${_fmtM(low)} – ${_fmtM(high)}</div>
        <p class="text-xs text-gray-500">${_bmEsc(rev.method || '')}</p>
        ${rev.assumptions ? `<p class="text-xs text-gray-600 mt-1 italic">${_bmEsc(rev.assumptions)}</p>` : ''}
    </div>`;
}

function _renderLevers(levers) {
    if (!levers || !levers.length) return `
    <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
        <div class="text-xs font-medium text-gray-400 mb-2">变现杠杆</div>
        <p class="text-sm text-gray-500">暂无明确数据</p>
    </div>`;

    return `
    <div class="bg-gray-800/40 border border-gray-700/50 rounded-lg p-4">
        <div class="text-xs font-medium text-gray-400 mb-2">变现杠杆</div>
        <ul class="space-y-1.5">
            ${levers.map(l => `<li class="text-sm text-gray-300 flex items-start gap-1.5"><span class="text-green-400 flex-shrink-0">›</span>${_bmEsc(l)}</li>`).join('')}
        </ul>
    </div>`;
}

function _renderModelTags(model) {
    const tags = [];
    if (model.has_free_tier)   tags.push({label: '✓ 免费套餐', color: 'bg-green-900/40 border-green-700/50 text-green-300'});
    if (model.has_open_source) tags.push({label: `⭐ 开源 (${model.oss_stars ? _fmtNum(model.oss_stars) + ' stars' : model.license || 'OSS'})`, color: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-300'});
    if (model.has_enterprise)  tags.push({label: '🏢 企业版', color: 'bg-blue-900/40 border-blue-700/50 text-blue-300'});
    if (model.license)         tags.push({label: `📄 ${model.license}`, color: 'bg-gray-800 border-gray-700 text-gray-400'});
    if (!tags.length) return '';
    return `<div class="flex flex-wrap gap-2">${tags.map(t => `<span class="text-xs border px-2.5 py-1 rounded-full ${t.color}">${t.label}</span>`).join('')}</div>`;
}

function _fmtM(n) {
    n = Number(n);
    if (isNaN(n) || n === 0) return '—';
    if (n >= 1e9) return '$' + (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
    return '$' + n;
}
function _fmtNum(n) {
    n = Number(n);
    if (isNaN(n)) return '—';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
}
function _bmEsc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}
