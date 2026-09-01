function renderSocial(sm) {
    const container = document.getElementById('section-social');
    const channels = sm.channels || {};
    const pm = sm.propagation_metrics || {};
    const zh = (document.documentElement.lang || '').toLowerCase().startsWith('zh');
    const tx = (en, cn) => zh ? cn : en;
    const verified = ch => Boolean(ch && ch.detected === true && ch.verification?.status === 'verified');
    const usefulTweets = tweets => (tweets || []).filter(t => {
        const text = String(t.text || '').replace(/https?:\/\/\S+/g, '').trim();
        return text.length >= 40 && !/^[@#\s]+$/.test(text);
    });

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-4">📱 Social Media Channel Analysis</h3>

        <div class="space-y-2 mb-6">`;

    // Channel cards
    for (const [key, ch] of Object.entries(channels)) {
        const isVerified = verified(ch);
        const statusColor = isVerified ? 'text-green-700' : 'text-amber-700';
        const statusText = isVerified
            ? tx('✓ Verified official account', '✓ 已验证官方账号')
            : (ch.detected ? tx('Unverified · excluded from score', '未验证 · 不计入评分') : tx('No verified account', '未找到已验证账号'));
        let extras = [];
        if (isVerified && ch.followers) extras.push(`${ch.followers} followers`);
        if (isVerified && ch.following) extras.push(`${ch.following} following`);
        if (isVerified && ch.subscribers) extras.push(`${ch.subscribers} subscribers`);
        if (isVerified && ch.video_count) extras.push(`${ch.video_count} videos`);
        if (isVerified && ch.stars_total) extras.push(`⭐ ${ch.stars_total} total stars`);
        if (isVerified && ch.public_repos) extras.push(`${ch.public_repos} repos`);
        if (isVerified && ch.subreddit_members) extras.push(`${ch.subreddit_members} members`);
        if (isVerified && ch.total_mentions) extras.push(`${ch.total_mentions} mentions`);
        if (isVerified && ch.handle) extras.push(ch.handle);

        html += `<div class="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
            <div class="flex items-center gap-3 flex-wrap">
                <span class="${statusColor} font-medium text-sm min-w-[80px]">${esc(ch.platform||key)}</span>
                <span class="text-xs text-gray-500">${statusText}</span>
                ${extras.length ? `<span class="text-xs text-gray-400">${extras.join(' · ')}</span>` : ''}
                ${ch.note && !ch.detected ? `<span class="text-xs text-gray-500">${esc(ch.note)}</span>` : ''}
            </div>
            ${isVerified && ch.url ? `<a href="${esc(ch.url)}" target="_blank" rel="noopener" class="text-xs text-[color:var(--accent)] hover:underline shrink-0">${tx('Open evidence', '打开证据')} →</a>` : ''}
        </div>`;
    }
    html += `</div>`;

    // GitHub top repos
    const gh = channels.github;
    if (verified(gh) && gh.top_repos && gh.top_repos.length) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">GitHub Top Repos</h4>
            <div class="space-y-1">`;
        for (const r of gh.top_repos) {
            html += `<div class="flex items-center justify-between bg-gray-800 rounded px-3 py-2 text-xs">
                <span class="text-gray-200">${esc(r.name)}</span>
                <div class="flex gap-3 text-gray-400">
                    <span>⭐ ${r.stars}</span>
                    <span>${esc(r.language||'')}</span>
                </div>
            </div>`;
        }
        html += `</div></div>`;
    }

    // Reddit top posts
    const reddit = channels.reddit;
    if (verified(reddit) && reddit.top_posts && reddit.top_posts.length) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">Reddit Popular Discussions</h4>
            <div class="space-y-1.5">`;
        for (const p of reddit.top_posts.slice(0,8)) {
            html += `<a href="${esc(p.url)}" target="_blank" class="block bg-gray-800 rounded px-3 py-2 hover:bg-gray-750">
                <div class="text-xs text-gray-200">${esc(p.title)}</div>
                <div class="text-[10px] text-gray-500 mt-0.5">r/${esc(p.subreddit)} · ⬆${p.upvotes} · 💬${p.comments} · u/${esc(p.author)}</div>
            </a>`;
        }
        html += `</div></div>`;

        // Mentioned subreddits
        if (reddit.mentioned_subreddits && reddit.mentioned_subreddits.length) {
            html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">Mentioned Subreddits</h4>
                <div class="flex flex-wrap gap-1.5">`;
            for (const s of reddit.mentioned_subreddits) {
                html += `<span class="bg-gray-800 text-xs px-2 py-1 rounded text-gray-300">r/${esc(s.name)} (${s.count})</span>`;
            }
            html += `</div></div>`;
        }
    }

    // Propagation metrics
    if ((pm.data_sources || []).length) html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-3">📊 Propagation Metrics Overview</h4>
        <div class="overflow-x-auto"><table class="w-full text-xs">
            <thead><tr class="bg-gray-800"><th class="text-left px-3 py-2 text-gray-400">Metric</th><th class="text-left px-3 py-2 text-gray-400">Value</th><th class="text-left px-3 py-2 text-gray-400">Notes</th></tr></thead>
            <tbody>
                <tr class="border-t border-gray-800"><td class="px-3 py-2 text-gray-300">Total Participants</td><td class="px-3 py-2 font-mono">${(pm.total_participants||0).toLocaleString()}</td><td class="px-3 py-2 text-gray-500">Followers + Subscribers + Members</td></tr>
                <tr class="border-t border-gray-800"><td class="px-3 py-2 text-gray-300">Est. Impressions</td><td class="px-3 py-2 font-mono">${(pm.estimated_impressions||0).toLocaleString()}</td><td class="px-3 py-2 text-gray-500">Conservative estimate (based on followers)</td></tr>
                <tr class="border-t border-gray-800"><td class="px-3 py-2 text-gray-300">Total Engagement</td><td class="px-3 py-2 font-mono">${(pm.total_engagement||0).toLocaleString()}</td><td class="px-3 py-2 text-gray-500">Likes + Retweets + Upvotes + Stars</td></tr>
                <tr class="border-t border-gray-800"><td class="px-3 py-2 text-gray-300">Data Source</td><td class="px-3 py-2" colspan="2">${(pm.data_sources||[]).join(', ')||'N/A'}</td></tr>
            </tbody>
        </table></div>
        ${pm.breakdown && pm.breakdown.length ? `<div class="mt-2 space-y-0.5">${pm.breakdown.map(b => `<div class="text-[10px] text-gray-400">• ${esc(b)}</div>`).join('')}</div>` : ''}
        ${pm.note ? `<div class="text-xs text-yellow-400/80 mt-2">${esc(pm.note)}</div>` : ''}
    </div>`;

    // Twitter deep analysis (from Caravo API)
    const tw = channels.twitter;
    const usableTweets = verified(tw) ? usefulTweets(tw.top_tweets) : [];
    if (usableTweets.length) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">🐦 Twitter/X Key Posts Analysis</h4>
            <div class="space-y-2">`;
        for (const t of usableTweets.slice(0, 5)) {
            html += `<div class="bg-gray-800 rounded-lg p-3">
                <div class="text-xs text-gray-200 mb-2">${esc(t.text)}</div>
                <div class="flex flex-wrap gap-3 text-[10px] text-gray-400">
                    ${t.views ? `<span>👁 ${Number(t.views).toLocaleString()} views</span>` : ''}
                    <span>❤️ ${(t.likes||0).toLocaleString()} likes</span>
                    <span>🔄 ${(t.retweets||0).toLocaleString()} retweets</span>
                    <span>💬 ${(t.replies||0).toLocaleString()} replies</span>
                    ${t.bookmarks ? `<span>🔖 ${Number(t.bookmarks).toLocaleString()} bookmarks</span>` : ''}
                </div>
                ${t.created_at ? `<div class="text-[10px] text-gray-500 mt-1">${esc(t.created_at)}</div>` : ''}
            </div>`;
        }
        html += `</div></div>`;
    } else if (verified(tw) && tw.top_tweets && tw.top_tweets.length) {
        html += `<div class="mb-6 rounded-lg border border-[color:var(--warm-border)] bg-white/60 p-4 text-xs text-[color:var(--ink-muted)]">
            ${tx('The collected posts are mostly links or low-context updates, so no strategy conclusion is generated from them.', '抓到的帖子以链接或低信息量更新为主，本报告不会据此生成策略结论。')}
        </div>`;
    }

    // Twitter profile summary
    if (verified(tw) && tw.profile && tw.profile.name) {
        html += `<div class="mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-2">📊 Twitter Account Overview</h4>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
                <div class="bg-gray-800 rounded p-2"><div class="text-[10px] text-gray-400">Followers</div><div class="text-sm font-mono">${tw.followers ? Number(tw.followers).toLocaleString() : '?'}</div></div>
                <div class="bg-gray-800 rounded p-2"><div class="text-[10px] text-gray-400">Following</div><div class="text-sm font-mono">${tw.following ? Number(tw.following).toLocaleString() : '?'}</div></div>
                <div class="bg-gray-800 rounded p-2"><div class="text-[10px] text-gray-400">Tweets</div><div class="text-sm font-mono">${tw.profile.statuses_count ? Number(tw.profile.statuses_count).toLocaleString() : '?'}</div></div>
                <div class="bg-gray-800 rounded p-2"><div class="text-[10px] text-gray-400">Listed</div><div class="text-sm font-mono">${tw.profile.listed_count || '?'}</div></div>
            </div></div>`;
    }

    // Manual supplement needed (fallback)
    if (tw && !tw.detected && tw.key_posts_framework) {
        html += `<div class="mb-4"><h4 class="text-sm font-semibold text-gray-300 mb-2">🔍 Data Requiring Manual Collection</h4>
            <div class="bg-yellow-900/10 border border-yellow-800/30 rounded-lg p-3">
                <div class="text-xs text-yellow-300 mb-2">The following data requires Twitter API or manual collection:</div>
                <ul class="space-y-1">`;
        for (const item of (tw.key_posts_framework.needed_data||[])) {
            html += `<li class="text-xs text-gray-400">• ${esc(item)}</li>`;
        }
        html += `</ul></div></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
