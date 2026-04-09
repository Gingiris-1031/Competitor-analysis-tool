/**
 * render-pricing.js — Pricing structure display module
 */

function renderPricing(pricing) {
    const el = document.getElementById('section-pricing');
    if (!el) return;
    if (!pricing || (!pricing.found && !pricing.tiers)) { el.innerHTML = ''; return; }

    const modelLabel = {
        'freemium': '🆓 Freemium',
        'subscription': '💳 Subscription',
        'usage-based': '📊 Usage-based',
        'open-source': '🌐 Open Source',
        'unknown': '❓ Unknown',
    }[pricing.model] || pricing.model || '❓';

    const tags = [];
    if (pricing.free_plan)    tags.push('<span class="text-xs bg-green-900/40 text-green-300 border border-green-700/40 px-2 py-0.5 rounded-full">Free Plan</span>');
    if (pricing.free_trial)   tags.push('<span class="text-xs bg-blue-900/40 text-blue-300 border border-blue-700/40 px-2 py-0.5 rounded-full">Free Trial</span>');
    if (pricing.annual_discount) tags.push(`<span class="text-xs bg-yellow-900/40 text-yellow-300 border border-yellow-700/40 px-2 py-0.5 rounded-full">${pricing.annual_discount}</span>`);

    const tiers = pricing.tiers || [];
    let tiersHtml = '';
    if (tiers.length > 0) {
        tiersHtml = `
        <div class="mt-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-${Math.min(tiers.length, 4)} gap-4">
            ${tiers.map(t => {
                const price = t.price_monthly === 0
                    ? '<span class="text-2xl font-bold text-green-400">Free</span>'
                    : `<span class="text-2xl font-bold text-white">$${t.price_monthly}</span><span class="text-xs text-gray-500">/月</span>`;
                const annualNote = t.price_annual_monthly
                    ? `<p class="text-xs text-gray-500 mt-0.5">Annual: $${t.price_annual_monthly}/mo</p>`
                    : '';
                const features = (t.features || []).slice(0, 6).map(f =>
                    `<li class="flex gap-2 text-xs text-gray-300"><span class="text-blue-400 flex-shrink-0">✓</span>${_esc(f)}</li>`
                ).join('');
                const highlight = t.highlight
                    ? 'border-blue-600 ring-1 ring-blue-600'
                    : 'border-gray-700';
                return `
                <div class="relative bg-gray-800 rounded-xl border ${highlight} p-5 flex flex-col">
                    ${t.highlight ? '<div class="absolute -top-2.5 left-1/2 -translate-x-1/2 text-xs bg-blue-600 text-white px-3 py-0.5 rounded-full">Recommended</div>' : ''}
                    <h4 class="font-semibold text-white mb-2">${_esc(t.name)}</h4>
                    <div class="mb-1">${price}</div>
                    ${annualNote}
                    <ul class="mt-4 space-y-1.5 flex-1">${features}</ul>
                </div>`;
            }).join('')}
        </div>`;
    } else if (!pricing.found) {
        tiersHtml = `<p class="text-sm text-gray-500 mt-4">No public pricing page detected. May use enterprise pricing or private deployment model.</p>`;
    }

    const insights = pricing.insights || [];
    const insightsHtml = insights.length > 0 ? `
        <div class="mt-5 space-y-2">
            ${insights.map(ins => `
            <div class="flex gap-2 items-start text-sm text-gray-300">
                <span class="text-yellow-400 flex-shrink-0">💡</span>
                <span>${_esc(ins)}</span>
            </div>`).join('')}
        </div>` : '';

    const sourceHtml = pricing.source_url ? `
        <p class="text-xs text-gray-600 mt-4">Data Source:<a href="${pricing.source_url}" target="_blank" class="text-blue-500 hover:underline">${pricing.source_url}</a></p>
    ` : '';

    el.innerHTML = `
    <div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex flex-wrap items-center gap-3 mb-4">
            <h3 class="text-base font-semibold text-white">💰 Pricing Structure</h3>
            <span class="text-xs bg-purple-900/40 text-purple-300 border border-purple-700/40 px-2 py-0.5 rounded-full">${_esc(modelLabel)}</span>
            ${tags.join('')}
        </div>
        ${tiersHtml}
        ${insightsHtml}
        ${sourceHtml}
    </div>`;
}

function _esc(str) {
    return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
