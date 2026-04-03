function _renderKeywordTable(keywords) {
    let html = `<div class="overflow-x-auto"><table class="w-full text-xs">
        <thead><tr class="bg-gray-800 text-gray-400"><th class="px-2 py-1.5 text-left">关键词</th><th class="px-2 py-1.5 text-right">排名</th><th class="px-2 py-1.5 text-right">月搜索量</th><th class="px-2 py-1.5 text-right">CPC</th><th class="px-2 py-1.5 text-left">竞争度</th></tr></thead>
        <tbody>`;
    for (const k of keywords) {
        const posColor = k.position <= 3 ? 'text-green-400' : k.position <= 10 ? 'text-blue-400' : 'text-gray-400';
        html += `<tr class="border-t border-gray-800"><td class="px-2 py-1.5">${esc(k.keyword)}</td><td class="px-2 py-1.5 text-right ${posColor} font-mono">#${k.position}</td><td class="px-2 py-1.5 text-right font-mono">${(k.search_volume||0).toLocaleString()}</td><td class="px-2 py-1.5 text-right">$${(k.cpc||0).toFixed(2)}</td><td class="px-2 py-1.5">${esc(k.competition||'—')}</td></tr>`;
    }
    html += `</tbody></table></div>`;
    return html;
}

function renderTraffic(tr) {
    const container = document.getElementById('section-traffic');
    const rank = tr.domain_rank || {};
    const bl = tr.backlinks || {};
    const kw = tr.top_keywords || {};
    const hist = tr.historical || {};
    const growth = tr.growth_analysis || {};

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-1">📈 流量与 SEO 分析</h3>
        <p class="text-xs text-gray-500 mb-4">数据来源: DataForSEO</p>`;

    // Core metrics grid
    if (rank.organic_traffic || bl.backlinks) {
        html += `<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">`;
        const metrics = [
            ['有机流量/月', rank.organic_traffic, 'text-blue-300'],
            ['排名关键词', rank.total_keywords, 'text-green-300'],
            ['Top 10 关键词', rank.keywords_top10, 'text-purple-300'],
            ['等效付费成本', rank.estimated_paid_cost ? '$'+rank.estimated_paid_cost.toLocaleString() : null, 'text-yellow-300'],
            ['反向链接', bl.backlinks, 'text-blue-300'],
            ['引用域名', bl.referring_domains, 'text-green-300'],
            ['域名排名', bl.domain_rank, 'text-purple-300'],
            ['引用 IP', bl.referring_ips, 'text-gray-300'],
        ];
        for (const [label, val, color] of metrics) {
            if (val !== null && val !== undefined) {
                const display = typeof val === 'number' ? val.toLocaleString() : val;
                html += `<div class="bg-gray-800 rounded-lg p-3"><div class="text-[10px] text-gray-400">${label}</div><div class="text-sm font-mono ${color} mt-1">${display}</div></div>`;
            }
        }
        html += `</div>`;
    }

    // Historical trend
    const histData = hist.history || [];
    if (histData.length > 0) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-3">📊 有机流量趋势</h4>`;
        // Simple bar chart using divs
        const maxEtv = Math.max(...histData.map(h => h.organic_traffic || 0));
        html += `<div class="flex items-end gap-1 mb-2" style="height:128px">`;
        for (const h of histData) {
            const etv = h.organic_traffic || 0;
            const pxHeight = maxEtv > 0 ? Math.max(Math.round((etv / maxEtv) * 120), 4) : 4;
            const idx = histData.indexOf(h);
            const prev = idx > 0 ? histData[idx - 1] : null;
            const growth = prev ? ((etv - (prev.organic_traffic||1)) / (prev.organic_traffic||1) * 100) : 0;
            const color = growth > 20 ? 'bg-green-500' : growth < -20 ? 'bg-red-500' : 'bg-blue-500';
            html += `<div class="flex-1 flex flex-col items-center justify-end h-full">
                <div class="text-[8px] text-gray-400 mb-1">${etv >= 1000 ? Math.round(etv/1000)+'K' : etv}</div>
                <div class="${color} rounded-t w-full opacity-80" style="height:${pxHeight}px" title="${h.date}: ${etv.toLocaleString()}"></div>
            </div>`;
        }
        html += `</div>`;
        // Labels
        html += `<div class="flex gap-1 text-[8px] text-gray-500">`;
        for (const h of histData) {
            html += `<div class="flex-1 text-center">${h.date.slice(2)}</div>`;
        }
        html += `</div>`;
        // Data table
        html += `<details class="mt-3"><summary class="text-xs text-gray-400 cursor-pointer hover:text-gray-200">查看月度数据</summary>
            <div class="mt-2 overflow-x-auto"><table class="w-full text-[10px]">
                <thead><tr class="bg-gray-800 text-gray-400"><th class="px-2 py-1 text-left">月份</th><th class="px-2 py-1 text-right">有机流量</th><th class="px-2 py-1 text-right">关键词数</th><th class="px-2 py-1 text-right">Top10</th><th class="px-2 py-1 text-right">新增</th><th class="px-2 py-1 text-right">丢失</th></tr></thead>
                <tbody>`;
        for (const h of histData.slice().reverse()) {
            html += `<tr class="border-t border-gray-800"><td class="px-2 py-1">${h.date}</td><td class="px-2 py-1 text-right font-mono">${(h.organic_traffic||0).toLocaleString()}</td><td class="px-2 py-1 text-right">${(h.keywords||0).toLocaleString()}</td><td class="px-2 py-1 text-right">${h.top10||0}</td><td class="px-2 py-1 text-right text-green-400">+${(h.new||0).toLocaleString()}</td><td class="px-2 py-1 text-right text-red-400">-${(h.lost||0).toLocaleString()}</td></tr>`;
        }
        html += `</tbody></table></div></details></div>`;
    }

    // Growth phases
    if (growth.phases && growth.phases.length) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-3">🔍 增长阶段分析</h4><div class="space-y-2">`;
        for (const p of growth.phases) {
            const icon = p.name.includes('探索') ? '🌱' : p.name.includes('爆发') ? '🚀' : p.name.includes('高位') ? '📈' : '⏳';
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-sm font-medium text-gray-200">${esc(p.name)}</div>
                <div class="text-xs text-blue-400">${esc(p.period)}</div>
                <div class="text-xs text-gray-400 mt-1">${esc(p.description)}</div>
            </div>`;
        }
        html += `</div></div>`;
    }

    // Milestones
    if (growth.milestones && growth.milestones.length) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">📌 关键里程碑</h4><div class="space-y-1">`;
        for (const m of growth.milestones) {
            html += `<div class="text-xs text-gray-300 bg-gray-800 rounded px-3 py-1.5">${esc(m)}</div>`;
        }
        html += `</div></div>`;
    }

    // Growth insights
    if (growth.insights && growth.insights.length) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">💡 增长洞察</h4><div class="space-y-1">`;
        for (const i of growth.insights) {
            html += `<div class="text-xs text-gray-300 bg-gray-800 rounded px-3 py-1.5">${esc(i)}</div>`;
        }
        html += `</div></div>`;
    }

    // Top keywords — branded
    const brandedKw = kw.branded_keywords || kw.keywords || [];
    const nonBrandedKw = kw.non_branded_keywords || [];

    if (brandedKw.length) {
        html += `<div class="mb-4"><h4 class="text-sm font-semibold text-gray-300 mb-2">🏷️ 品牌词排名 <span class="text-gray-500 font-normal">(${(kw.branded_count||brandedKw.length)} 个)</span></h4>`;
        html += _renderKeywordTable(brandedKw);
        html += `</div>`;
    }

    // Top keywords — non-branded (the real SEO power)
    if (nonBrandedKw.length) {
        html += `<div class="mb-4"><h4 class="text-sm font-semibold text-gray-300 mb-2">🔑 非品牌词 · 首页高曝光 <span class="text-gray-500 font-normal">(${(kw.non_branded_count||nonBrandedKw.length)} 个非品牌词进首页，按搜索量排序)</span></h4>`;
        html += _renderKeywordTable(nonBrandedKw);
        html += `</div>`;
    } else if (brandedKw.length === 0 && kw.keywords && kw.keywords.length) {
        // Fallback: legacy format without branded/non-branded split
        html += `<div class="mb-4"><h4 class="text-sm font-semibold text-gray-300 mb-2">🔑 Top 排名关键词 <span class="text-gray-500 font-normal">(共 ${(kw.total||0).toLocaleString()} 个)</span></h4>`;
        html += _renderKeywordTable(kw.keywords);
        html += `</div>`;
    }

    // Error fallback
    if (rank.error && !rank.organic_traffic) {
        html += `<div class="bg-yellow-900/20 border border-yellow-800/50 rounded-lg p-4">
            <p class="text-sm text-yellow-300">⚠️ ${esc(rank.error)}</p>
        </div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}

function renderSummary(sum) {
    const container = document.getElementById('section-summary');
    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-4">📋 综合评估</h3>
        <div class="space-y-2">`;
    for (const f of (sum.findings || [])) {
        html += `<div class="text-sm text-gray-300 leading-relaxed">${esc(f)}</div>`;
    }
    html += `</div></div>`;
    container.innerHTML = html;
}
