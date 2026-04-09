function renderPropagation(prop) {
    const container = document.getElementById('section-propagation');
    if (!prop || prop.error || !prop.data_mode || prop.data_mode === 'empty') {
        container.innerHTML = '';
        return;
    }

    const root = prop.root_post || {};
    const inf = prop.influencer_analysis || {};
    const stages = prop.four_stage_timeline || {};
    const rhythm = prop.propagation_rhythm || {};
    const approx = prop.approximate_analysis;
    const followUps = prop.follow_up_activities || [];
    const layers = prop.propagation_layers || {};
    const isApprox = prop.data_mode === 'approximate';

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-1">🌐 Propagation Analysis</h3>
        <p class="text-xs text-gray-500 mb-5">4-stage Launch propagation · KOL influence map · Propagation rhythm</p>`;

    // ── Multi-channel fallback mode (Twitter unavailable, show PH/GitHub/Reddit signals) ──
    if (prop.data_mode === 'multi_channel_fallback') {
        const signals = prop.signals || [];
        const ph = prop.producthunt || {};
        const gh = prop.github || {};
        const rd = prop.reddit || {};
        const errors = prop.errors || [];

        if (errors.length) {
            html += `<div class="bg-yellow-900/10 border border-yellow-700/30 rounded-lg p-3 mb-5 text-xs text-yellow-300/80">${esc(prop.note || '⚠️ Twitter API unavailable')}</div>`;
        }

        // Stats grid
        html += `<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">`;
        if (ph.votes) {
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-[10px] text-gray-500">Product Hunt</div>
                <div class="text-sm font-mono text-orange-300 mt-0.5">${Number(ph.votes).toLocaleString()} votes</div>
                ${ph.comments ? `<div class="text-[10px] text-gray-500 mt-0.5">${ph.comments} comments</div>` : ''}
                ${ph.date ? `<div class="text-[10px] text-gray-500">${esc(ph.date)}</div>` : ''}
            </div>`;
        }
        if (gh.stars) {
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-[10px] text-gray-500">GitHub Stars</div>
                <div class="text-sm font-mono text-yellow-300 mt-0.5">${Number(gh.stars).toLocaleString()}</div>
            </div>`;
        }
        if (rd.posts) {
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-[10px] text-gray-500">Reddit</div>
                <div class="text-sm font-mono text-blue-300 mt-0.5">${rd.posts} posts</div>
                ${rd.members ? `<div class="text-[10px] text-gray-500 mt-0.5">${Number(rd.members).toLocaleString()} members</div>` : ''}
            </div>`;
        }
        html += `</div>`;

        // Signal list
        if (signals.length) {
            html += `<div class="space-y-2">`;
            for (const sig of signals) {
                html += `<div class="bg-gray-800 rounded-lg p-3 text-xs text-gray-300">${esc(sig)}</div>`;
            }
            html += `</div>`;
        }

        if (!signals.length && !ph.votes && !gh.stars && !rd.posts) {
            html += `<div class="text-xs text-gray-500">No propagation data available</div>`;
        }

    } else if (isApprox && approx) {
        // ── Approximate mode ────────────────────────────────────────────────
        html += `<div class="bg-yellow-900/10 border border-yellow-700/30 rounded-lg p-3 mb-5 text-xs text-yellow-300/80">${esc(approx.note || 'Approximate analysis mode')}</div>`;

        const agg = approx.aggregate_metrics || {};
        const est = approx.propagation_estimate || {};
        const best = approx.best_launch_tweet || {};

        if (best.text) {
            html += `<div class="bg-gray-800 rounded-lg p-4 mb-5 border-l-2 border-blue-500">
                <div class="text-xs font-semibold text-gray-400 mb-1">📌 Best Launch Post</div>
                <div class="text-xs text-gray-200 mb-2">${esc(best.text)}</div>
                <div class="flex flex-wrap gap-3 text-[10px] text-gray-400">
                    <span>❤️ ${(best.likes || 0).toLocaleString()}</span>
                    <span>🔄 ${(best.retweets || 0).toLocaleString()}</span>
                    ${best.views ? `<span>👁 ${Number(best.views).toLocaleString()}</span>` : ''}
                    ${best.created_at ? `<span class="text-gray-500">${esc(best.created_at.slice(0,20))}</span>` : ''}
                </div>
            </div>`;
        }

        // Stats grid
        html += `<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">`;
        const metricItems = [
            { label: '总 Retweets', val: (agg.total_retweets || 0).toLocaleString(), color: 'text-blue-300' },
            { label: '总 Likes',    val: (agg.total_likes || 0).toLocaleString(),    color: 'text-pink-300' },
            { label: '总 Views',    val: (agg.total_views || 0).toLocaleString(),    color: 'text-gray-300' },
            { label: 'Est. Reach',    val: (est.estimated_reach || 0).toLocaleString(), color: 'text-green-300' },
        ];
        for (const m of metricItems) {
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-[10px] text-gray-500">${esc(m.label)}</div>
                <div class="text-sm font-mono ${m.color} mt-0.5">${m.val}</div>
            </div>`;
        }
        html += `</div>`;

        if (est.viral_coefficient) {
            html += `<div class="text-xs text-gray-400 mb-4">
                📊 <span class="text-gray-300">Viral Coefficient (RT/tweet)</span>：<span class="font-mono text-yellow-300">${est.viral_coefficient}</span>
                ${est.engagement_rate != null ? `&nbsp;·&nbsp; <span class="text-gray-300">Engagement Rate</span>：<span class="font-mono text-yellow-300">${est.engagement_rate}%</span>` : ''}
            </div>`;
        }

    } else {
        // ── Full mode ────────────────────────────────────────────────────────

        // Root post
        if (root.text) {
            html += `<div class="bg-gray-800 rounded-lg p-4 mb-5 border-l-2 border-blue-500">
                <div class="text-xs font-semibold text-gray-400 mb-1">📌 Launch Post</div>
                <div class="text-xs text-gray-200 mb-2">${esc(root.text)}</div>
                <div class="flex flex-wrap gap-3 text-[10px] text-gray-400">
                    ${root.views ? `<span>👁 ${Number(root.views).toLocaleString()} views</span>` : ''}
                    <span>❤️ ${(root.likes || 0).toLocaleString()} likes</span>
                    <span>🔄 ${(root.retweets || 0).toLocaleString()} retweets</span>
                    <span>💬 ${(root.replies || 0).toLocaleString()} replies</span>
                    <span>💬 ${(root.quotes || 0).toLocaleString()} quotes</span>
                    ${root.bookmarks ? `<span>🔖 ${Number(root.bookmarks).toLocaleString()}</span>` : ''}
                </div>
            </div>`;
        }

        // Propagation layer counts
        const l1 = layers.layer_1_retweets || {};
        const l2 = layers.layer_2_quotes || {};
        if (l1.count > 0 || l2.count > 0) {
            html += `<div class="flex flex-wrap gap-3 mb-5">
                <div class="bg-gray-800 rounded-lg px-3 py-2">
                    <div class="text-[10px] text-gray-500">Layer 1 Retweets</div>
                    <div class="text-sm font-mono text-blue-300">${l1.count || 0}</div>
                </div>
                <div class="bg-gray-800 rounded-lg px-3 py-2">
                    <div class="text-[10px] text-gray-500">Layer 2 Quotes</div>
                    <div class="text-sm font-mono text-purple-300">${l2.count || 0}</div>
                </div>
                ${inf.total_kols > 0 ? `<div class="bg-gray-800 rounded-lg px-3 py-2">
                    <div class="text-[10px] text-gray-500">KOL Engaged (10K+)</div>
                    <div class="text-sm font-mono text-yellow-300">${inf.total_kols}</div>
                </div>` : ''}
            </div>`;
        }

        // Four-stage timeline
        const stageStyles = {
            stage_1_internal:  { color: 'bg-blue-900/50 border-blue-600/50 text-blue-300',   icon: '🔥' },
            stage_2_ecosystem: { color: 'bg-purple-900/50 border-purple-600/50 text-purple-300', icon: '🤝' },
            stage_3_kol:       { color: 'bg-yellow-900/50 border-yellow-600/50 text-yellow-300', icon: '⭐' },
            stage_4_mass:      { color: 'bg-green-900/50 border-green-600/50 text-green-300', icon: '🌊' },
        };
        const hasStageData = Object.values(stages).some(s => s.count > 0);
        if (hasStageData) {
            html += `<div class="mb-5">
                <h4 class="text-xs font-semibold text-gray-400 mb-2">🎯 4-Stage Propagation Model</h4>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-2">`;
            for (const [key, data] of Object.entries(stages)) {
                const st = stageStyles[key] || { color: 'bg-gray-800 border-gray-600 text-gray-300', icon: '📌' };
                html += `<div class="${st.color} rounded-lg p-3 border">
                    <div class="text-lg mb-1">${st.icon}</div>
                    <div class="text-[10px] text-gray-400 mb-1">${esc(data.label || key)}</div>
                    <div class="text-xl font-bold font-mono">${data.count || 0}</div>
                    ${data.users && data.users.length > 0 ? `<div class="mt-1.5 space-y-0.5">
                        ${data.users.slice(0, 2).map(u =>
                            `<div class="text-[9px] text-gray-400 truncate">@${esc(u.screen_name || '')} ${u.followers ? '(' + Number(u.followers).toLocaleString() + ')' : ''}</div>`
                        ).join('')}
                    </div>` : ''}
                </div>`;
            }
            html += `</div></div>`;
        }

        // KOL tier breakdown
        const tiers = inf.kol_tiers || {};
        const hasTierData = Object.values(tiers).some(v => v > 0);
        if (hasTierData) {
            const tierLabels = { mega_kol: 'Mega KOL (100K+)', big_kol: 'Big KOL (10K-100K)', mid_kol: 'Mid KOL (1K-10K)', small: 'Small (<1K)' };
            html += `<div class="mb-5">
                <h4 class="text-xs font-semibold text-gray-400 mb-2">👥 KOL Influence Tiers</h4>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-2">`;
            for (const [tier, count] of Object.entries(tiers)) {
                if (!count) continue;
                html += `<div class="bg-gray-800 rounded-lg p-2 text-center">
                    <div class="text-sm font-bold font-mono text-orange-300">${count}</div>
                    <div class="text-[9px] text-gray-500 mt-0.5">${esc(tierLabels[tier] || tier)}</div>
                </div>`;
            }
            html += `</div></div>`;
        }

        // Top influencers table
        const topInf = inf.top_influencers || [];
        if (topInf.length > 0) {
            html += `<div class="mb-5">
                <h4 class="text-xs font-semibold text-gray-400 mb-2">🌟 Top Influencers</h4>
                <div class="overflow-x-auto">
                <table class="w-full text-xs">
                    <thead><tr class="bg-gray-800 text-gray-400">
                        <th class="px-2 py-1.5 text-left">Account</th>
                        <th class="px-2 py-1.5 text-right">Followers</th>
                        <th class="px-2 py-1.5 text-left">Type</th>
                        <th class="px-2 py-1.5 text-left">Joined At</th>
                    </tr></thead>
                    <tbody>`;
            for (const u of topInf) {
                const hours = u.hours_after_launch != null
                    ? (u.hours_after_launch < 1 ? '<1h' : `${Math.round(u.hours_after_launch)}h`)
                    : 'N/A';
                html += `<tr class="border-t border-gray-800">
                    <td class="px-2 py-1.5 text-blue-400 font-medium">@${esc(u.screen_name || '')}</td>
                    <td class="px-2 py-1.5 text-right font-mono text-gray-300">${(u.followers || 0).toLocaleString()}</td>
                    <td class="px-2 py-1.5 text-gray-500">${esc(u.user_type || '')}</td>
                    <td class="px-2 py-1.5 text-gray-500">${esc(hours)}</td>
                </tr>`;
            }
            html += `</tbody></table></div></div>`;
        }
    }

    // ── Propagation rhythm (shown for both modes if available) ───────────────
    if (Object.keys(rhythm).length > 0) {
        const maxCount = Math.max(...Object.values(rhythm).map(b => b.count || 0), 1);
        html += `<div class="mb-5">
            <h4 class="text-xs font-semibold text-gray-400 mb-2">⏱ Propagation Rhythm (Time Distribution)</h4>
            <div class="space-y-2">`;
        for (const [bk, bv] of Object.entries(rhythm)) {
            const pct = Math.round(((bv.count || 0) / maxCount) * 100);
            html += `<div>
                <div class="flex items-center justify-between text-[10px] text-gray-400 mb-0.5">
                    <span>${esc(bv.label || bk)}</span>
                    <span class="font-mono">${bv.count || 0} users${bv.total_followers_reached ? ' · ' + Number(bv.total_followers_reached).toLocaleString() + ' followers reached' : ''}</span>
                </div>
                <div class="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                    <div class="h-full bg-blue-500 rounded-full" style="width:${pct}%"></div>
                </div>
            </div>`;
        }
        html += `</div></div>`;
    }

    // ── Follow-up activities ─────────────────────────────────────────────────
    if (followUps.length > 0) {
        const actIcons = { ama: '🎙', office_hours: '🏢', demo: '🎬', thread: '🧵', milestone: '🎯', media: '📰' };
        html += `<div>
            <h4 class="text-xs font-semibold text-gray-400 mb-2">🔁 Follow-up Activities</h4>
            <div class="flex flex-wrap gap-2">`;
        for (const act of followUps) {
            const icon = actIcons[act.type] || '📌';
            const hours = act.hours_after_launch != null ? `+${act.hours_after_launch}h` : '';
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2 max-w-xs">
                <div class="flex items-center gap-1.5 mb-1">
                    <span>${icon}</span>
                    <span class="text-[10px] font-medium text-gray-300">${esc(act.type)}</span>
                    ${hours ? `<span class="text-[9px] text-gray-500">${esc(hours)}</span>` : ''}
                </div>
                <div class="text-[10px] text-gray-400 truncate">${esc((act.tweet_text || '').slice(0,80))}</div>
            </div>`;
        }
        html += `</div></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
