/**
 * render-strategy.js — 定制增长策略 Playbook 推荐渲染模块
 */

function renderStrategy(gs) {
    const container = document.getElementById('section-strategy');
    if (!gs || gs.error || (!gs.primary && !(gs.secondary && gs.secondary.length))) {
        if (container) container.innerHTML = '';
        return;
    }

    const primary = gs.primary || null;
    const secondary = gs.secondary || [];
    const gt = gs.growth_tools || null;
    const productName = gs.product_name || '竞品';

    let html = `<div class="bg-gray-900 rounded-xl border border-emerald-700/30 p-6">
        <div class="flex items-center justify-between mb-1">
            <h3 class="text-lg font-semibold">📋 定制增长策略</h3>
            <span class="text-[10px] bg-emerald-900/40 text-emerald-300 border border-emerald-700/40 px-2.5 py-1 rounded-full font-medium">💡 Gingiris Playbook 独家推荐</span>
        </div>
        <p class="text-xs text-gray-500 mb-2">基于 Wayback 历史演变 + PH Launch 记录 + 社交传播数据的交叉分析，自动匹配最适合的增长 Playbook</p>
        <p class="text-[10px] text-emerald-400/60 mb-6">⚡ 这些定制建议融合了多个独家数据源，是 GPT/Claude 对话无法提供的深度分析</p>`;

    // ── Primary Playbook ────────────────────────────────────────────────────
    if (primary) {
        html += _renderPrimaryCard(primary, productName);
    }

    // ── Secondary Playbooks ─────────────────────────────────────────────────
    if (secondary.length > 0) {
        html += `<div class="mt-4">
            <h4 class="text-xs font-semibold text-gray-400 mb-3">辅助推荐</h4>
            <div class="grid grid-cols-1 md:grid-cols-${Math.min(secondary.length, 2)} gap-3">`;
        for (const s of secondary) {
            html += _renderSecondaryCard(s);
        }
        html += `</div></div>`;
    }

    // ── Growth Tools (always shown) ─────────────────────────────────────────
    if (gt) {
        html += _renderToolsCard(gt);
    }

    // ── Score debug strip (collapsed) ──────────────────────────────────────
    const allScores = gs.all_scores || {};
    if (Object.keys(allScores).length) {
        const scoreItems = Object.entries(allScores)
            .map(([k, v]) => `<span class="text-[9px] bg-gray-800 rounded px-1.5 py-0.5">${esc(k)} <span class="text-blue-400">${v}</span>/4</span>`)
            .join('');
        html += `<div class="mt-4 pt-4 border-t border-gray-800">
            <div class="text-[10px] text-gray-600 mb-1">匹配得分明细</div>
            <div class="flex flex-wrap gap-1">${scoreItems}</div>
        </div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}

function _renderPrimaryCard(pb, productName) {
    const reasonsHtml = (pb.reasons || []).slice(0, 3)
        .map(r => `<li class="flex gap-2 items-start"><span class="text-emerald-400 shrink-0 mt-0.5">✓</span><span>${esc(r)}</span></li>`)
        .join('');

    const tipsHtml = (pb.custom_tips || []).slice(0, 3).map((tip, i) => `
        <div class="flex gap-3 p-3 bg-gray-900/80 rounded-lg border-l-2 border-emerald-500">
            <span class="text-emerald-400 font-bold text-sm shrink-0">Step ${i + 1}</span>
            <p class="text-xs text-gray-300 leading-relaxed">${esc(tip)}</p>
        </div>`).join('');

    const scoreStars = '★'.repeat(Math.min(pb.score || 0, 4)) + '☆'.repeat(Math.max(0, 4 - (pb.score || 0)));

    return `<div class="bg-gray-800 rounded-xl border border-emerald-500/30 p-5">
        <div class="flex items-start justify-between mb-3">
            <div class="flex items-center gap-3">
                <span class="text-3xl">${esc(pb.emoji || '📘')}</span>
                <div>
                    <div class="flex items-center gap-2">
                        <span class="text-sm font-semibold text-white">${esc(pb.label)}</span>
                        <span class="text-[10px] bg-emerald-600 text-white rounded-full px-2 py-0.5 font-medium">主推</span>
                        <span class="text-[10px] text-emerald-400/70 font-mono">${scoreStars}</span>
                    </div>
                    <div class="text-[10px] text-gray-500 mt-0.5">${esc(pb.description || '')}</div>
                </div>
            </div>
            <a href="${esc(pb.url)}" target="_blank" rel="noopener"
               class="shrink-0 text-xs bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg transition-colors font-medium">
                查看 Playbook →
            </a>
        </div>

        ${reasonsHtml ? `<div class="mb-4 bg-gray-900/50 rounded-lg p-3">
            <div class="text-[10px] text-emerald-400/80 font-medium mb-2">📌 为什么推荐这个 Playbook（基于竞品实际数据）</div>
            <ul class="space-y-1.5 text-xs text-gray-300">${reasonsHtml}</ul>
        </div>` : ''}

        ${tipsHtml ? `<div>
            <div class="text-[10px] text-emerald-400/80 font-medium mb-2">🎯 基于 ${esc(productName)} 数据的定制行动建议</div>
            <div class="space-y-2">${tipsHtml}</div>
        </div>` : ''}
    </div>`;
}

function _renderSecondaryCard(pb) {
    const reasonsHtml = (pb.reasons || []).slice(0, 2)
        .map(r => `<li class="flex gap-1.5 text-[11px] text-gray-400"><span class="text-emerald-500 shrink-0">✓</span><span>${esc(r)}</span></li>`)
        .join('');

    const tip = (pb.custom_tips || [])[0];
    const scoreStars = '★'.repeat(Math.min(pb.score || 0, 4)) + '☆'.repeat(Math.max(0, 4 - (pb.score || 0)));

    return `<div class="bg-gray-800 rounded-lg border border-gray-700 p-4">
        <div class="flex items-start justify-between mb-2">
            <div class="flex items-center gap-2">
                <span class="text-lg">${esc(pb.emoji || '📘')}</span>
                <span class="text-xs font-semibold text-gray-200">${esc(pb.label)}</span>
                <span class="text-[9px] text-gray-500 font-mono">${scoreStars}</span>
            </div>
            <a href="${esc(pb.url)}" target="_blank" rel="noopener"
               class="text-[10px] text-emerald-400 hover:text-emerald-300 shrink-0">查看 →</a>
        </div>
        ${reasonsHtml ? `<ul class="space-y-1 mb-2">${reasonsHtml}</ul>` : ''}
        ${tip ? `<div class="text-[10px] text-gray-400 mt-2 leading-relaxed border-t border-gray-700 pt-2"><span class="text-emerald-400/70">💡</span> ${esc(tip)}</div>` : ''}
    </div>`;
}

function _renderToolsCard(gt) {
    return `<div class="mt-4 flex items-center justify-between bg-gray-800/50 border border-gray-700 rounded-lg px-4 py-3">
        <div class="flex items-center gap-2">
            <span class="text-base">${esc(gt.emoji || '🛠️')}</span>
            <div>
                <span class="text-xs font-medium text-gray-300">${esc(gt.label)}</span>
                <span class="text-[10px] text-gray-500 ml-2">${esc(gt.description || '')}</span>
            </div>
        </div>
        <a href="${esc(gt.url)}" target="_blank" rel="noopener"
           class="text-[10px] text-gray-400 hover:text-gray-200 shrink-0">查看工具库 →</a>
    </div>`;
}
