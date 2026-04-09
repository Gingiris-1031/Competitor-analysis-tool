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
        <h3 class="text-lg font-semibold mb-1">🚀 Growth Deep Analysis</h3>
        <p class="text-xs text-gray-500 mb-6">Channel Breakdown · 0→1 Story · Launch Waves Timeline</p>`;

    // ── 1. Channel Breakdown ─────────────────────────────────────────────────
    if (cb && cb.active_channels && cb.active_channels.length) {
        html += `<div class="mb-8">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">📡 Channel Breakdown</h4>`;

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
            const tag = isDominant ? ' 👑 Dominant' : '';
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
                if (m.top_tweet_likes)          metrics.push(['Top Tweet Likes', m.top_tweet_likes.toLocaleString()]);
                if (m.avg_engagement)           metrics.push(['Avg Engagement', m.avg_engagement.toLocaleString()]);
                if (m.stars_total)              metrics.push(['Total Stars', m.stars_total.toLocaleString()]);
                if (m.top_repo_stars)           metrics.push(['Top Repo', m.top_repo_stars.toLocaleString()]);
                if (m.total_mentions)           metrics.push(['Mentions', m.total_mentions.toLocaleString()]);
                if (m.subreddit_members)        metrics.push(['Sub Members', m.subreddit_members.toLocaleString()]);
                if (m.monthly_traffic)          metrics.push(['Monthly Traffic', m.monthly_traffic.toLocaleString()]);
                if (m.total_keywords)           metrics.push(['Ranked KW', m.total_keywords.toLocaleString()]);
                if (m.equivalent_ad_cost)       metrics.push(['Equiv. Ad Cost', '$' + m.equivalent_ad_cost.toLocaleString()]);
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
                    const catLabels = { launch: '🚀 Launch', product_update: '⚙️ Update', community: '👥 Community', tutorial: '📖 Tutorial', kol_collab: '🤝 KOL', other: '💬 Other' };
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
                <h5 class="text-xs font-semibold text-gray-400 mb-2">🏆 Top Content Performance (Cross-platform)</h5>
                <div class="overflow-x-auto"><table class="w-full text-xs">
                    <thead><tr class="bg-gray-800 text-gray-400">
                        <th class="px-2 py-1.5 text-left">Platform</th>
                        <th class="px-2 py-1.5 text-left">Content Summary</th>
                        <th class="px-2 py-1.5 text-right">❤️</th>
                        <th class="px-2 py-1.5 text-right">Other</th>
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
            <h4 class="text-sm font-semibold text-gray-300 mb-3">📖 0→1 Growth Story</h4>`;

        // Key stats strip
        html += `<div class="flex flex-wrap gap-3 mb-4">`;
        if (z2o.first_seen && z2o.first_seen !== 'N/A') {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">Domain First Seen</div><div class="text-sm font-mono text-blue-300">${esc(z2o.first_seen)}</div></div>`;
        }
        if (z2o.current_traffic) {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">Current Monthly Traffic</div><div class="text-sm font-mono text-green-300">${z2o.current_traffic.toLocaleString()}</div></div>`;
        }
        if (z2o.growth_multiple) {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">Traffic Growth Multiple</div><div class="text-sm font-mono text-yellow-300">${z2o.growth_multiple}x</div></div>`;
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
                <h5 class="text-xs font-semibold text-gray-400 mb-2">⚡ Key Inflection Points</h5>
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

    // ── 3. Launch Waves — Timeline Bubble Chart ─────────────────────────────
    if (lw && lw.total_waves > 0) {
        const waves = lw.launches || [];
        html += `<div>
            <h4 class="text-sm font-semibold text-gray-300 mb-3">🌊 Launch Waves Timeline</h4>`;

        // Summary bar
        html += `<div class="flex flex-wrap gap-3 mb-5">
            <div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">Launch Waves</div><div class="text-sm font-mono text-blue-300">${lw.total_waves}</div></div>`;
        if (lw.launch_cadence) {
            html += `<div class="bg-gray-800 rounded-lg px-3 py-2"><div class="text-[10px] text-gray-500">Launch Cadence</div><div class="text-sm text-yellow-300">${esc(lw.launch_cadence)}</div></div>`;
        }
        html += `</div>`;

        // Channel colors
        const chColors = {
            'Product Hunt': {bg: '#f97316', text: '#fff'},
            'Twitter': {bg: '#3b82f6', text: '#fff'}, 'Twitter/X': {bg: '#3b82f6', text: '#fff'},
            'Hacker News': {bg: '#ef4444', text: '#fff'},
            'GitHub': {bg: '#22c55e', text: '#fff'},
            'Organic Traffic Spike': {bg: '#a855f7', text: '#fff'},
            'SEO': {bg: '#a855f7', text: '#fff'},
        };
        const defaultColor = {bg: '#6b7280', text: '#fff'};

        // Calculate max impact for bubble sizing
        const maxImpact = Math.max(...waves.map(w => {
            const imp = w.total_impact || {};
            return (imp.ph_votes || 0) + (imp.twitter_likes || 0) + (imp.traffic_peak || 0);
        }), 1);

        // Timeline visualization
        html += `<div class="relative" style="padding: 20px 0;">`;
        // Horizontal timeline line
        html += `<div style="position:absolute; top:50%; left:0; right:0; height:2px; background:rgba(255,255,255,0.08);"></div>`;

        // Waves as bubbles on the timeline
        html += `<div style="display:flex; align-items:center; justify-content:space-around; min-height:180px; position:relative;">`;

        for (let wi = 0; wi < waves.length; wi++) {
            const wave = waves[wi];
            const impact = wave.total_impact || {};
            const totalImpact = (impact.ph_votes || 0) + (impact.twitter_likes || 0) + (impact.traffic_peak || 0);
            const bubbleSize = Math.max(48, Math.min(100, 48 + (totalImpact / maxImpact) * 52));
            const primaryChannel = (wave.channels || ['Unknown'])[0];
            const color = chColors[primaryChannel] || defaultColor;
            const dateLabel = (wave.date_range || '').split(' ~ ')[0] || '';

            // Impact summary
            const impactParts = [];
            if (impact.ph_votes) impactParts.push(`${impact.ph_votes.toLocaleString()} PH`);
            if (impact.twitter_likes) impactParts.push(`${impact.twitter_likes.toLocaleString()} likes`);
            if (impact.traffic_peak) impactParts.push(`${impact.traffic_peak.toLocaleString()} traffic`);

            // Alternate above/below timeline
            const isAbove = wi % 2 === 0;
            const alignStyle = isAbove ? 'flex-direction:column-reverse;' : 'flex-direction:column;';

            html += `<div style="display:flex; ${alignStyle} align-items:center; gap:8px; flex:1; max-width:140px;">`;

            // Info label
            html += `<div style="text-align:center;">
                <div style="font-size:10px; color:#9ca3af; font-family:monospace;">${esc(dateLabel)}</div>
                <div style="font-size:9px; color:#6b7280; margin-top:2px;">${impactParts.join(' · ') || ''}</div>
            </div>`;

            // Bubble
            html += `<div style="width:${bubbleSize}px; height:${bubbleSize}px; border-radius:50%; background:${color.bg}; display:flex; flex-direction:column; align-items:center; justify-content:center; box-shadow:0 0 20px ${color.bg}40; cursor:default; position:relative; z-index:1;" title="${wave.channels?.join(', ')}">
                <div style="font-size:11px; font-weight:700; color:${color.text};">W${wave.wave_number}</div>
                <div style="font-size:8px; color:${color.text}; opacity:0.8;">${esc(primaryChannel).replace('Twitter/X','Twitter')}</div>
            </div>`;

            // Connector dot on timeline
            html += `<div style="width:8px; height:8px; border-radius:50%; background:${color.bg}; border:2px solid #111827;"></div>`;

            html += `</div>`;

            // Interval label between waves
            if (wi < waves.length - 1) {
                const nextDate = (waves[wi + 1].date_range || '').split(' ~ ')[0];
                if (dateLabel && nextDate) {
                    try {
                        const d1 = new Date(dateLabel), d2 = new Date(nextDate);
                        const days = Math.round((d2 - d1) / (1000 * 60 * 60 * 24));
                        if (days > 0 && days < 9999) {
                            html += `<div style="font-size:8px; color:#4b5563; white-space:nowrap; position:relative; z-index:2;">${days}d</div>`;
                        }
                    } catch(e) {}
                }
            }
        }

        html += `</div></div>`;

        // Channel legend
        const usedChannels = new Set();
        waves.forEach(w => (w.channels || []).forEach(c => usedChannels.add(c)));
        html += `<div style="display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; justify-content:center;">`;
        for (const ch of usedChannels) {
            const c = chColors[ch] || defaultColor;
            html += `<div style="display:flex; align-items:center; gap:4px;">
                <div style="width:8px; height:8px; border-radius:50%; background:${c.bg};"></div>
                <span style="font-size:10px; color:#9ca3af;">${esc(ch)}</span>
            </div>`;
        }
        html += `</div>`;

        // Expandable detail cards
        html += `<details class="mt-4"><summary class="text-xs text-gray-500 cursor-pointer hover:text-gray-300">📋 Expand wave details</summary><div class="space-y-3 mt-3">`;
        for (const wave of waves) {
            const impact = wave.total_impact || {};
            const impactBits = [];
            if (impact.ph_votes) impactBits.push(`⬆ ${impact.ph_votes.toLocaleString()} PH votes`);
            if (impact.twitter_likes) impactBits.push(`❤️ ${impact.twitter_likes.toLocaleString()} likes`);
            if (impact.traffic_peak) impactBits.push(`📈 ${impact.traffic_peak.toLocaleString()} traffic/mo`);

            html += `<div class="bg-gray-800 rounded-lg p-3 border border-gray-700">
                <div class="flex items-center gap-2 mb-1.5">
                    <span class="text-xs font-semibold text-blue-400">Wave ${wave.wave_number}</span>
                    <span class="text-[10px] text-gray-500 font-mono">${esc(wave.date_range || '')}</span>
                    ${(wave.channels || []).map(c => `<span class="text-[9px] bg-gray-700 rounded px-1.5 py-0.5 text-gray-300">${esc(c)}</span>`).join('')}
                </div>
                ${impactBits.length ? `<div class="text-[10px] text-green-400 mb-1.5">${impactBits.join('  ·  ')}</div>` : ''}
                <div class="space-y-0.5">`;
            for (const ev of (wave.events || [])) {
                html += `<div class="text-[10px] text-gray-400 flex gap-2">
                    <span class="font-mono text-gray-600 shrink-0">${esc((ev.date||'').slice(0,10))}</span>
                    <span class="text-gray-300 truncate">${esc((ev.name||'').slice(0,80))}</span>
                </div>`;
            }
            html += `</div></div>`;
        }
        html += `</div></details>`;

        html += `</div>`;
    }

    // Empty state
    if (!cb.active_channels?.length && !z2o.timeline?.length && !lw.total_waves) {
        html += `<div class="text-sm text-gray-500 text-center py-8">Insufficient data to generate growth analysis</div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
