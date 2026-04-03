function renderGrowth(ga) {
    const container = document.getElementById('section-growth');
    if (!ga || ga.error || (!ga.channel_breakdown && !ga.zero_to_one_story && !ga.launch_waves)) {
        container.innerHTML = '';
        return;
    }

    const cb = ga.channel_breakdown || {};
    const z2o = ga.zero_to_one_story || {};
    const lw = ga.launch_waves || {};

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-1">🚀 增长深度分析</h3>
        <p class="text-xs text-gray-500 mb-6">渠道拆解 · 0→1 故事线 · 多波 Launch 时间线</p>`;

    // ── 1. Channel Breakdown ─────────────────────────────────────────────────
    if (cb && cb.active_channels && cb.active_channels.length) {
        html += `<div class="mb-8">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">📡 增长渠道拆解</h4>`;

        // Active channel pills + dominant badge
        html += `<div class="flex flex-wrap gap-2 mb-4">`;
        const dominant = cb.dominant_channel || '';
        for (const ch of (cb.active_channels || [])) {
            const isDominant = cb.channel_metrics && Object.entries(cb.channel_metrics).some(
                ([k, v]) => k === dominant && (v.platform || k) === ch
            );
            const badge = isDominant
                ? 'bg-blue-600 text-white font-semibold'
                : 'bg-gray-800 text-gray-300';
            const tag = isDominant ? ' 👑 主导' : '';
            html += `<span class="text-xs px-3 py-1 rounded-full ${badge}">${esc(ch)}${tag}</span>`;
        }
        html += `</div>`;

        // Channel metrics cards
        const cm = cb.channel_metrics || {};
        if (Object.keys(cm).length) {
            html += `<div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">`;
            const iconMap = { twitter: '🐦', github: '⭐', seo: '🔍', reddit: '🤖', youtube: '📺' };
            for (const [key, m] of Object.entries(cm)) {
                const icon = iconMap[key] || '📊';
                const platform = m.platform || key;
                const metrics = [];
                if (m.followers != null)        metrics.push(['Followers', m.followers.toLocaleString()]);
                if (m.total_tweets)             metrics.push(['Tweets', m.total_tweets.toLocaleString()]);
                if (m.top_tweet_likes)          metrics.push(['Top 推文 Likes', m.top_tweet_likes.toLocaleString()]);
                if (m.avg_engagement)           metrics.push(['平均互动', m.avg_engagement.toLocaleString()]);
                if (m.stars_total)              metrics.push(['Total Stars', m.stars_total.toLocaleString()]);
                if (m.top_repo_stars)           metrics.push(['Top Repo', m.top_repo_stars.toLocaleString()]);
                if (m.total_mentions)           metrics.push(['提及次数', m.total_mentions.toLocaleString()]);
                if (m.subreddit_members)        metrics.push(['Sub 成员', m.subreddit_members.toLocaleString()]);
                if (m.monthly_traffic)          metrics.push(['月均流量', m.monthly_traffic.toLocaleString()]);
                if (m.total_keywords)           metrics.push(['排名词', m.total_keywords.toLocaleString()]);
                if (m.equivalent_ad_cost)       metrics.push(['等效广告', '$' + m.equivalent_ad_cost.toLocaleString()]);
                if (m.subscribers != null)      metrics.push(['Subscribers', String(m.subscribers)]);
                if (m.video_count != null)      metrics.push(['Videos', String(m.video_count)]);

                html += `<div class="bg-gray-800 rounded-lg p-3">
                    <div class="text-xs text-gray-400 mb-2">${icon} ${esc(platform)}</div>
                    <div class="grid grid-cols-2 gap-x-4 gap-y-1">`;
                for (const [label, val] of metrics) {
                    html += `<div class="text-[10px] text-gray-500">${esc(label)}</div><div class="text-[10px] text-blue-300 font-mono text-right">${esc(val)}</div>`;
                }
                html += `</div>`;

                // Content categories (Twitter)
                const cats = m.content_categories || {};
                if (Object.keys(cats).length) {
                    const catLabels = { launch: '🚀 发布', product_update: '⚙️ 更新', community: '👥 社区', tutorial: '📖 教程', kol_collab: '🤝 KOL', other: '💬 其他' };
                    html += `<div class="mt-2 pt-2 border-t border-gray-700 flex flex-wrap gap-1">`;
                    for (const [cat, count] of Object.entries(cats).sort((a, b) => b[1] - a[1])) {
                        html += `<span class="text-[9px] bg-gray-700 rounded px-1.5 py-0.5">${catLabels[cat] || cat} ×${count}</span>`;
                    }
                    html += `</div>`;
                }
                html += `</div>`;
            }
            html += `</div>`;
        }

        // Top content table
        const topContent = cb.top_content || [];
        if (topContent.length) {
            html += `<div>
                <h5 class="text-xs font-semibold text-gray-400 mb-2">🏆 Top 内容表现（跨平台）</h5>
                <div class="overflow-x-auto"><table class="w-full text-xs">
                    <thead><tr class="bg-gray-800 text-gray-400">
                        <th class="px-2 py-1.5 text-left">平台</th>
                        <th class="px-2 py-1.5 text-left">内容摘要</th>
                        <th class="px-2 py-1.5 text-right">❤️</th>
                        <th class="px-2 py-1.5 text-right">其他</th>
                    </tr></thead>
                    <tbody>`;
            for (const c of topContent) {
                const platform = c.platform || '';
                const text = (c.text || '').slice(0, 70);
                const likes = c.likes || 0;
                let other = '';
                if (c.retweets) other = `🔁 ${c.retweets}`;
                else if (c.comments) other = `💬 ${c.comments}`;
                else if (c.subreddit) other = `r/${c.subreddit}`;
                html += `<tr class="border-t border-gray-800">
                    <td class="px-2 py-1.5 text-gray-400 whitespace-nowrap">${esc(platform)}</td>
                    <td class="px-2 py-1.5 text-gray-300 max-w-xs truncate">${esc(text)}</td>
                    <td class="px-2 py-1.5 text-right font-mono text-pink-300">${likes.toLocaleString()}</td>
                    <td class="px-2 py-1.5 text-right text-gray-500">${esc(other)}</td>
                </tr>`;
            }
            html += `</tbody></table></div></div>`;
        }

        html += `</div>`;
    }

    // ── 2. 0→1 Story ────────────────────────────────────────────────────────
    if (z2o && (z2o.timeline && z2o.timeline.length || z2o.current_traffic)) {
        html += `<div class="mb-8">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">📖 0→1 成长故事线</h4>`;

        // Key stats strip
        html += `<div class="flex flex-wrap gap-3 mb-4">`;
        if (z2o.first_seen && z2o.first_seen !== 'N/A') {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">域名首次出现</div><div class="text-sm font-mono text-blue-300">${esc(z2o.first_seen)}</div></div>`;
        }
        if (z2o.current_traffic) {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">当前月均流量</div><div class="text-sm font-mono text-green-300">${z2o.current_traffic.toLocaleString()}</div></div>`;
        }
        if (z2o.growth_multiple) {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">流量增长倍数</div><div class="text-sm font-mono text-yellow-300">${z2o.growth_multiple}x</div></div>`;
        }
        html += `</div>`;

        // Timeline
        const timeline = z2o.timeline || [];
        if (timeline.length) {
            const typeStyle = {
                milestone:      { icon: '🏁', color: 'border-blue-500',   dot: 'bg-blue-500'   },
                launch:         { icon: '🚀', color: 'border-green-500',  dot: 'bg-green-500'  },
                traffic_spike:  { icon: '📈', color: 'border-yellow-500', dot: 'bg-yellow-500' },
                seo_milestone:  { icon: '🔑', color: 'border-purple-500', dot: 'bg-purple-500' },
                website_change: { icon: '🔄', color: 'border-gray-500',   dot: 'bg-gray-500'   },
            };
            html += `<div class="relative pl-6 space-y-3">
                <div class="absolute left-2 top-0 bottom-0 w-px bg-gray-700"></div>`;
            for (const ev of timeline) {
                const style = typeStyle[ev.type] || { icon: '📌', color: 'border-gray-600', dot: 'bg-gray-600' };
                const date = (ev.date || '').slice(0, 10);
                html += `<div class="relative">
                    <div class="absolute -left-4 top-1.5 w-2.5 h-2.5 rounded-full ${style.dot} ring-2 ring-gray-900"></div>
                    <div class="bg-gray-800 rounded-lg px-3 py-2 border-l-2 ${style.color}">
                        <div class="flex items-center gap-2 mb-0.5">
                            <span class="text-[10px] text-gray-500 font-mono">${esc(date)}</span>
                            <span class="text-[10px] text-gray-500">${style.icon} ${esc(ev.source || '')}</span>
                        </div>
                        <div class="text-xs text-gray-200">${esc(ev.event || '')}</div>
                    </div>
                </div>`;
            }
            html += `</div>`;
        }

        // Key inflection points
        const inflections = z2o.key_inflection_points || [];
        if (inflections.length) {
            html += `<div class="mt-4">
                <h5 class="text-xs font-semibold text-gray-400 mb-2">⚡ 关键拐点</h5>
                <div class="space-y-2">`;
            for (const ip of inflections) {
                const pct = ip.growth_pct || 0;
                html += `<div class="bg-gray-800 rounded-lg px-3 py-2 flex items-center justify-between">
                    <div>
                        <span class="text-[10px] text-gray-500 font-mono">${esc(ip.date || '')}</span>
                        <div class="text-xs text-gray-300 mt-0.5">
                            ${(ip.traffic_before||0).toLocaleString()} → ${(ip.traffic_after||0).toLocaleString()} <span class="text-green-400">+${pct}%</span>
                        </div>
                    </div>
                    <div class="text-lg font-bold text-green-400">+${pct}%</div>
                </div>`;
            }
            html += `</div></div>`;
        }

        html += `</div>`;
    }

    // ── 3. Launch Waves ──────────────────────────────────────────────────────
    if (lw && lw.total_waves > 0) {
        html += `<div>
            <h4 class="text-sm font-semibold text-gray-300 mb-3">🌊 多波 Launch 分析</h4>`;

        // Summary bar
        html += `<div class="flex flex-wrap gap-3 mb-4">
            <div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">总 Launch 波次</div><div class="text-sm font-mono text-blue-300">${lw.total_waves}</div></div>`;
        if (lw.launch_cadence) {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">发布节奏</div><div class="text-sm text-yellow-300">${esc(lw.launch_cadence)}</div></div>`;
        }
        html += `</div>`;

        // Wave cards
        html += `<div class="space-y-3">`;
        for (const wave of (lw.launches || [])) {
            const channels = (wave.channels || []).join(' · ');
            const impact = wave.total_impact || {};
            const impactBits = [];
            if (impact.ph_votes)       impactBits.push(`⬆ ${impact.ph_votes.toLocaleString()} PH votes`);
            if (impact.twitter_likes)  impactBits.push(`❤️ ${impact.twitter_likes.toLocaleString()} likes`);
            if (impact.traffic_peak)   impactBits.push(`📈 ${impact.traffic_peak.toLocaleString()} 流量/月`);

            html += `<div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
                <div class="flex items-start justify-between mb-2">
                    <div>
                        <span class="text-xs font-semibold text-blue-400">Wave ${wave.wave_number}</span>
                        <span class="text-[10px] text-gray-500 ml-2 font-mono">${esc(wave.date_range || '')}</span>
                    </div>
                    <div class="flex flex-wrap gap-1 justify-end">
                        ${(wave.channels || []).map(c => `<span class="text-[9px] bg-gray-700 rounded px-1.5 py-0.5 text-gray-300">${esc(c)}</span>`).join('')}
                    </div>
                </div>
                ${impactBits.length ? `<div class="text-[10px] text-green-400 mb-2">${impactBits.join('  ·  ')}</div>` : ''}
                <div class="space-y-1">`;
            for (const ev of (wave.events || [])) {
                const date = (ev.date || '').slice(0, 10);
                const name = (ev.name || '').slice(0, 80);
                html += `<div class="text-xs text-gray-400 flex gap-2">
                    <span class="font-mono text-gray-600 shrink-0">${esc(date)}</span>
                    <span class="text-gray-500 shrink-0">${esc(ev.channel || '')}</span>
                    <span class="text-gray-300 truncate">${esc(name)}</span>
                </div>`;
            }
            html += `</div></div>`;
        }
        html += `</div>`;

        html += `</div>`;
    }

    // Empty state
    if (!cb.active_channels?.length && !z2o.timeline?.length && !lw.total_waves) {
        html += `<div class="text-sm text-gray-500 text-center py-8">暂无足够数据生成增长分析</div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
