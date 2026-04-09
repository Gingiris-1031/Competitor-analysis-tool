function renderPeaks(tp) {
    const container = document.getElementById('section-peaks');
    if (!tp || (!tp.summary && !tp.error)) { container.innerHTML = ''; return; }
    if (tp.error || !tp.summary || !tp.summary.total_weeks) {
        container.innerHTML = `
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 class="text-base font-semibold text-white flex items-center gap-2 mb-3">
                <span>📈</span> Google Trends 流量峰值分析
            </h3>
            <div class="text-sm text-yellow-400/80 bg-yellow-400/5 border border-yellow-400/20 rounded-lg px-4 py-3">
                ⚠️ ${tp.error || 'Google Trends 数据暂时无法获取，请重新生成报告。'}
            </div>
        </div>`;
        return;
    }

    const s = tp.summary || {};
    const phases = tp.growth_phases || [];
    const peaks = tp.detected_peaks || [];
    const unmatched = tp.unmatched_peaks || [];
    const trendsData = tp.trends_data || [];

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex items-center justify-between mb-1">
            <h3 class="text-lg font-semibold">📈 Google Trends 流量峰值分析</h3>
            <span class="text-[10px] bg-purple-900/40 text-purple-300 border border-purple-700/40 px-2.5 py-1 rounded-full font-medium">📊 多源交叉归因分析</span>
        </div>
        <p class="text-xs text-gray-500 mb-5">品牌搜索热度 · 增长阶段 · Launch 关联</p>`;

    // ── Summary stats strip ──────────────────────────────────────────────────
    html += `<div class="flex flex-wrap gap-3 mb-6">`;
    const stats = [
        { label: '查询词', val: s.primary_query || '', color: 'text-blue-300' },
        { label: '峰值热度', val: String(s.max_interest || 0), sub: s.max_interest_date || '', color: 'text-yellow-300' },
        { label: '平均热度', val: String(s.avg_interest || 0), color: 'text-gray-300' },
        { label: '近期趋势', val: s.recent_trend || 'N/A', color: s.recent_trend === '上升' ? 'text-green-300' : (s.recent_trend === '下降' ? 'text-red-300' : 'text-gray-300') },
        { label: '当前阶段', val: s.current_phase || 'N/A', color: 'text-purple-300' },
        { label: '检测峰值', val: String(s.total_peaks_detected || 0), sub: `已关联 ${s.matched_peaks || 0} / 未匹配 ${s.unmatched_peaks || 0}`, color: 'text-orange-300' },
    ];
    for (const st of stats) {
        html += `<div class="bg-gray-800 rounded-lg px-3 py-2 min-w-[90px]">
            <div class="text-[10px] text-gray-500">${esc(st.label)}</div>
            <div class="text-sm font-mono ${st.color} mt-0.5">${esc(st.val)}</div>
            ${st.sub ? `<div class="text-[9px] text-gray-500">${esc(st.sub)}</div>` : ''}
        </div>`;
    }
    html += `</div>`;

    // ── Traffic Quality Scoring (ring charts) ────────────────────────────────
    const tq = s.traffic_quality;
    if (tq) {
        const metrics = [
            { label: '有机真实度', score: tq.organic_authenticity, emoji: '🎯', desc: '峰值来源可追溯性' },
            { label: '增长持续性', score: tq.growth_sustainability, emoji: '📈', desc: '近期 vs 长期热度' },
            { label: '渠道多样性', score: tq.channel_diversity, emoji: '🌐', desc: '流量渠道丰富度' },
            { label: '品牌护城河', score: tq.brand_moat, emoji: '🏰', desc: '搜索热度趋势' },
        ];
        html += `<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">`;
        for (const m of metrics) {
            const pct = m.score;
            const color = pct >= 60 ? '#22c55e' : pct >= 30 ? '#eab308' : '#ef4444';
            const bgColor = pct >= 60 ? 'rgba(22,163,74,0.1)' : pct >= 30 ? 'rgba(234,179,8,0.1)' : 'rgba(239,68,68,0.1)';
            // SVG ring chart
            const r = 28, cx = 32, cy = 32, circum = 2 * Math.PI * r;
            const dashLen = (pct / 100) * circum;
            html += `<div class="bg-gray-800 rounded-xl p-3 text-center" style="background:${bgColor}">
                <svg viewBox="0 0 64 64" style="width:56px; height:56px; margin:0 auto;">
                    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="5"/>
                    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="5"
                        stroke-dasharray="${dashLen} ${circum}" stroke-linecap="round"
                        transform="rotate(-90 ${cx} ${cy})" style="transition:stroke-dasharray 0.5s"/>
                    <text x="${cx}" y="${cy + 1}" text-anchor="middle" dominant-baseline="central" fill="${color}" font-size="14" font-weight="bold">${pct}</text>
                </svg>
                <div class="text-xs font-medium text-gray-300 mt-1">${m.emoji} ${esc(m.label)}</div>
                <div class="text-[9px] text-gray-500">${esc(m.desc)}</div>
            </div>`;
        }
        html += `</div>`;
    }

    // ── Sparkline chart (text-based bar chart) ───────────────────────────────
    if (trendsData.length > 0) {
        const maxVal = Math.max(...trendsData.map(d => d.value), 1);
        // Show every Nth point to keep width manageable (~52 bars max)
        const step = Math.max(1, Math.floor(trendsData.length / 52));
        const sampled = trendsData.filter((_, i) => i % step === 0);

        // Identify peak indices in sampled data
        const peakTimestamps = new Set(peaks.map(p => p.peak_timestamp));

        html += `<div class="mb-6">
            <h4 class="text-xs font-semibold text-gray-400 mb-2">📊 搜索热度时间线</h4>
            <div class="flex items-end gap-px overflow-x-auto pb-1" style="height:72px; min-width:0">`;
        for (const d of sampled) {
            const pct = Math.round((d.value / maxVal) * 100);
            const isPeak = peakTimestamps.has(d.timestamp);
            const barColor = isPeak ? 'bg-orange-400' : 'bg-blue-600';
            const title = `${d.date_label}: ${d.value}`;
            html += `<div class="flex-1 flex flex-col items-center justify-end" style="min-width:4px; max-width:14px">
                <div class="${barColor} rounded-t w-full opacity-80 hover:opacity-100 cursor-default transition-opacity"
                    style="height:${Math.max(pct, 2)}%" title="${esc(title)}"></div>
            </div>`;
        }
        html += `</div>
            <div class="flex justify-between text-[9px] text-gray-600 mt-1">
                <span>${esc(sampled[0]?.date_label || '')}</span>
                <span class="text-orange-400/70">橙色 = 峰值周</span>
                <span>${esc(sampled[sampled.length - 1]?.date_label || '')}</span>
            </div>
        </div>`;
    }

    // ── Growth phases ────────────────────────────────────────────────────────
    if (phases.length > 0) {
        const phaseColors = {
            '冷启动期': 'bg-gray-700 text-gray-300',
            '爬坡期':   'bg-blue-900/60 text-blue-300',
            '爆发期':   'bg-green-900/60 text-green-300',
            '高位运行期': 'bg-yellow-900/60 text-yellow-300',
            '回落期':   'bg-red-900/40 text-red-300',
        };
        html += `<div class="mb-6">
            <h4 class="text-xs font-semibold text-gray-400 mb-2">🔄 增长阶段划分</h4>
            <div class="space-y-1.5">`;
        for (const ph of phases) {
            const cls = phaseColors[ph.phase] || 'bg-gray-800 text-gray-300';
            const channels = (ph.active_channels || []).join(' · ') || '—';
            const insights = ph.insights || [];
            const peakBadge = ph.peak_count ? `<span class="text-[9px] bg-orange-900/50 text-orange-300 rounded px-1 ml-1">${ph.peak_count} 峰值</span>` : '';
            html += `<div class="${cls} rounded-lg px-3 py-2">
                <div class="flex items-center justify-between">
                    <div>
                        <span class="text-xs font-medium">${esc(ph.phase)}</span>${peakBadge}
                        <span class="text-[10px] text-gray-500 ml-2 font-mono">${esc(ph.start_date)} → ${esc(ph.end_date)}</span>
                    </div>
                    <div class="text-right">
                        <div class="text-[10px] text-gray-400">${ph.week_count} 周 · 均值 ${ph.avg_value}</div>
                        <div class="text-[10px] text-gray-500">渠道: ${esc(channels)}</div>
                    </div>
                </div>`;
            if (insights.length > 0) {
                html += `<div class="mt-1.5 space-y-0.5">`;
                for (const ins of insights) {
                    html += `<div class="text-[10px] text-gray-400 pl-2 border-l border-gray-600">${esc(ins)}</div>`;
                }
                html += `</div>`;
            }
            html += `</div>`;
        }
        html += `</div></div>`;
    }

    // ── Detected peaks (with attribution) ───────────────────────────────────
    if (peaks.length > 0) {
        html += `<div class="mb-6">
            <h4 class="text-xs font-semibold text-gray-400 mb-2">🔍 检测到的峰值事件</h4>
            <div class="space-y-3">`;
        for (const pk of peaks) {
            const status = pk.status || 'unmatched';
            const attr = pk.attribution || {};
            const isAttributed = status === 'attributed';
            const isPhMatched = status === 'ph_matched' || status === 'matched';
            const isUnmatched = status === 'unmatched';

            // Border & badge based on attribution status
            let borderColor, badge;
            if (isAttributed) {
                const conf = attr.confidence === 'high' ? 'text-green-400' : 'text-yellow-400';
                const confLabel = attr.confidence === 'high' ? '高可信度' : '中等可信度';
                borderColor = 'border-green-600/60';
                badge = `<span class="text-[9px] bg-green-900/50 ${conf} rounded px-1.5 py-0.5">✅ 已归因·${confLabel}</span>`;
            } else if (isPhMatched) {
                borderColor = 'border-blue-600/60';
                badge = `<span class="text-[9px] bg-blue-900/50 text-blue-400 rounded px-1.5 py-0.5">🏆 PH 发布</span>`;
            } else {
                borderColor = 'border-orange-600/60';
                badge = `<span class="text-[9px] bg-orange-900/50 text-orange-400 rounded px-1.5 py-0.5">❓ 未匹配</span>`;
            }

            html += `<div class="bg-gray-800 rounded-lg px-3 py-2.5 border-l-2 ${borderColor}">
                <div class="flex items-center justify-between mb-1.5">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-xs font-mono text-gray-300">${esc(pk.peak_date_label || '')}</span>
                        <span class="text-xs font-bold text-orange-300">热度 ${pk.peak_value}</span>
                        ${badge}
                        ${attr.primary_channel && isAttributed ? `<span class="text-[9px] text-gray-500">via ${esc(attr.primary_channel)}</span>` : ''}
                    </div>
                    <span class="text-[10px] text-gray-500">${pk.weeks_in_event || 1} 周</span>
                </div>`;

            // Attribution sources
            if (attr.all_sources && attr.all_sources.length > 0) {
                const channelIcons = { 'Hacker News': '📰', 'Product Hunt': '🏆', 'Twitter/X': '🐦', 'Reddit': '💬' };
                html += `<div class="space-y-2 mt-1">`;
                for (const src of attr.all_sources) {
                    const icon = channelIcons[src.channel] || '🔗';
                    html += `<div>
                        <div class="flex items-center gap-1 mb-0.5">
                            <span class="text-[10px] font-semibold text-gray-300">${icon} ${esc(src.channel)}</span>
                            <span class="text-[9px] text-gray-600">impact ${src.impact_score}</span>
                        </div>
                        <div class="space-y-0.5 pl-3">`;
                    for (const ev of (src.events || []).slice(0, 3)) {
                        const title = (ev.title || '').slice(0, 70);
                        let meta = '';
                        if (src.channel === 'Hacker News') {
                            const url = ev.url || '';
                            meta = `${ev.points || 0} pts · 💬${ev.comments || 0} · ${ev.date || ''}`;
                            html += `<div class="text-[10px] text-gray-400">
                                <a href="${esc(url)}" target="_blank" class="text-blue-400 hover:underline">${esc(title)}</a>
                                <span class="text-gray-600 ml-1">${esc(meta)}</span>
                            </div>`;
                        } else if (src.channel === 'Product Hunt') {
                            meta = `⬆${ev.votes || 0} · ${ev.date || ''}`;
                            html += `<div class="text-[10px] text-gray-400">${esc(title)} <span class="text-gray-600">${esc(meta)}</span></div>`;
                        } else if (src.channel === 'Twitter/X') {
                            meta = `❤️${ev.likes || 0} 🔄${ev.retweets || 0} · ${ev.date || ''}`;
                            html += `<div class="text-[10px] text-gray-400">${esc(title)} <span class="text-gray-600">${esc(meta)}</span></div>`;
                        } else if (src.channel === 'Reddit') {
                            meta = `⬆${ev.upvotes || 0} · r/${ev.subreddit || ''} · ${ev.date || ''}`;
                            html += `<div class="text-[10px] text-gray-400">${esc(title)} <span class="text-gray-600">${esc(meta)}</span></div>`;
                        }
                    }
                    html += `</div></div>`;
                }
                html += `</div>`;
                // Attribution summary sentence
                if (attr.summary) {
                    html += `<div class="mt-1.5 text-[10px] text-gray-500 italic">${esc(attr.summary)}</div>`;
                }
            } else if (isPhMatched && pk.matched_launches && pk.matched_launches.length > 0) {
                // Legacy PH-matched display
                html += `<div class="space-y-0.5">`;
                for (const m of pk.matched_launches) {
                    const delta = m.delta_days != null
                        ? (m.delta_days >= 0 ? `峰值晚于 Launch ${m.delta_days} 天` : `峰值早于 Launch ${Math.abs(m.delta_days)} 天`)
                        : '';
                    html += `<div class="text-[10px] text-gray-400">📌 ${esc((m.label || '').slice(0, 60))} <span class="text-gray-500">${esc(delta)}</span></div>`;
                }
                html += `</div>`;
            } else {
                // Unmatched fallback
                const msg = attr.summary || pk.hypothesis || '未找到明确来源';
                html += `<div class="text-[10px] text-orange-300/70 mt-0.5">${esc(msg)}</div>`;
            }

            html += `</div>`;
        }
        html += `</div></div>`;
    }

    // ── Unmatched peaks — deep investigation results ──────────────────────────
    if (unmatched.length > 0) {
        // Check if any unmatched peaks now have attribution (from Brave investigation)
        const investigated = unmatched.filter(p => p.attribution && p.attribution.attributed);
        const stillUnmatched = unmatched.filter(p => !p.attribution || !p.attribution.attributed);

        if (investigated.length > 0) {
            html += `<div class="mb-4">
                <h4 class="text-xs font-semibold text-gray-400 mb-2">🔎 深度调查发现的事件</h4>
                <div class="space-y-2">`;
            for (const pk of investigated) {
                const attr = pk.attribution || {};
                html += `<div class="bg-gray-800 rounded-lg px-3 py-2.5 border-l-2 border-yellow-600/60">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs font-mono text-yellow-300">${esc(pk.peak_date_label || '')}</span>
                        <span class="text-[9px] bg-yellow-900/50 text-yellow-400 rounded px-1.5 py-0.5">🔎 深度调查</span>
                    </div>
                    <div class="text-xs text-gray-300 mb-1.5">${esc(attr.summary || '')}</div>`;
                // Show found events
                for (const src of (attr.all_sources || [])) {
                    for (const ev of (src.events || []).slice(0, 3)) {
                        html += `<div class="flex items-start gap-2 mb-1">
                            <span class="text-[10px] text-gray-500 flex-shrink-0">${esc(ev.source || src.channel || '')}</span>
                            <a href="${esc(ev.url || '')}" target="_blank" rel="noopener" class="text-[10px] text-blue-400 hover:underline truncate">${esc(ev.title || '')}</a>
                        </div>`;
                    }
                }
                html += `</div>`;
            }
            html += `</div></div>`;
        }

        if (stillUnmatched.length > 0) {
            html += `<div class="bg-orange-900/10 border border-orange-800/30 rounded-lg p-3">
                <div class="text-xs text-orange-300 font-medium mb-1">⚠️ ${stillUnmatched.length} 个未归因的流量峰值</div>
                <div class="text-[10px] text-gray-400">可能来自：付费广告投放、线下活动、口碑传播、或数据源未覆盖的渠道</div>
            </div>`;
        }
    }

    html += `</div>`;
    container.innerHTML = html;
}
