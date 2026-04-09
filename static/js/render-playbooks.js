/* render-playbooks.js — Gingiris Toolkit Context Recommendation (conversion-first design) */

const _PLAYBOOKS = {
    oss: {
        title: "Open-Source Project Integrated Marketing Action Manual",
        desc:  "Complete marketing execution framework for OSS projects from 0 to 10K Stars: community cold start, GitHub Trending, HN/PH launch cadence, developer content strategy",
        url:   "https://gingiris.gumroad.com/l/vhmkew",
        tag:   "🌟 OSS Growth",
        cta:   "Get OSS Marketing Playbook",
        why:   "The product you just analyzed is open source — this playbook covers the full replication path",
    },
    ph: {
        title: "Product Hunt Launch Action Guide",
        desc:  "Complete Product Hunt launch workflow: timing, pre-launch buildup, launch day SOP, post-launch review, with real case studies",
        url:   "https://gingiris.gumroad.com/l/zxamur",
        tag:   "🚀 PH Launch",
        cta:   "Get PH Launch Playbook",
        why:   "The competitor cold-started via Product Hunt — this playbook teaches you to replicate the same path",
    },
    launch: {
        title: "AI Product Global Launch Guide (with Case Studies)",
        desc:  "AI product global launch strategy: multi-wave launch cadence, community buildup, media outreach, with 10+ real case studies",
        url:   "https://gingiris.gumroad.com/l/nxkifd",
        tag:   "🌍 Global Launch",
        cta:   "Get Launch Strategy Guide",
        why:   "The competitor experienced multiple launch spikes — this guide helps you plan the same growth milestones",
    },
    b2b: {
        title: "AI Global B2B Product Full-Lifecycle Growth Guide",
        desc:  "B2B SaaS full lifecycle growth strategy: ICP definition, GTM path, Enterprise sales playbook, customer success framework",
        url:   "https://gingiris.gumroad.com/l/zaarq",
        tag:   "🏢 B2B Growth",
        cta:   "Get B2B Growth Guide",
        why:   "The competitor has validated a B2B enterprise monetization path — this guide helps you systematically replicate it",
    },
    bundle: {
        title: "Gingiris Complete Global Launch Playbook Bundle",
        desc:  "Includes all playbooks above + exclusive tool templates, get the complete Gingiris growth methodology in one bundle",
        url:   "https://gingiris.gumroad.com/l/gingiris-complete-global-launch-bundle",
        tag:   "📦 Complete Bundle",
        cta:   "Get Complete Playbook Bundle",
        why:   "",
    },
};

function renderPlaybooks(report) {
    const el = document.getElementById('section-playbooks');
    if (!el) return;

    const sections = report.sections || {};
    const meta     = report.meta    || {};
    const name     = meta.product_name || 'competitor';

    const pick   = _pickPlaybook(sections);
    const main   = _PLAYBOOKS[pick];
    const bundle = _PLAYBOOKS.bundle;

    el.innerHTML = `
    <div class="bg-gradient-to-br from-gray-900 via-gray-900 to-indigo-950/30 border border-indigo-800/40 rounded-xl p-6">

        <!-- Header -->
        <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-medium text-indigo-400 uppercase tracking-widest">Gingiris Toolkit Recommendation</span>
        </div>
        <p class="text-sm text-gray-400 mb-5">
            You just completed a deep analysis of <strong class="text-white">${_pbEsc(name)}</strong> — here are the actionable playbooks to replicate this growth path
        </p>

        <!-- Primary recommendation -->
        <div class="bg-gray-800/60 border border-indigo-700/50 rounded-xl p-5 mb-4 relative overflow-hidden">
            <div class="absolute top-0 right-0 bg-indigo-600 text-white text-xs font-medium px-3 py-1 rounded-bl-lg">Most Relevant</div>

            <div class="flex items-start gap-4">
                <div class="text-2xl flex-shrink-0 mt-0.5">📘</div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs bg-indigo-900/60 text-indigo-300 border border-indigo-700/50 px-2 py-0.5 rounded-full">${main.tag}</span>
                    </div>
                    <h4 class="text-base font-semibold text-white mb-1.5 leading-snug">${_pbEsc(main.title)}</h4>
                    <p class="text-sm text-gray-400 mb-2 leading-relaxed">${_pbEsc(main.desc)}</p>
                    ${main.why ? `<p class="text-xs text-indigo-300 bg-indigo-950/50 border border-indigo-800/40 rounded-lg px-3 py-2 mb-3">💡 ${_pbEsc(main.why)}</p>` : ''}
                    <a href="${_pbEscAttr(main.url)}" target="_blank" rel="noopener"
                       onclick="_trackPlaybook('${pick}')"
                       class="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors">
                        ${_pbEsc(main.cta)} →
                    </a>
                </div>
            </div>
        </div>

        <!-- Bundle upsell -->
        <div class="flex items-center justify-between bg-gray-800/40 border border-gray-700/50 rounded-lg px-4 py-3">
            <div class="flex items-center gap-3">
                <span class="text-lg">📦</span>
                <div>
                    <div class="text-sm font-medium text-gray-200">Want the complete methodology?</div>
                    <div class="text-xs text-gray-500">Gingiris Complete Global Launch Playbook Bundle — Complete bundle, get everything at once</div>
                </div>
            </div>
            <a href="${_pbEscAttr(bundle.url)}" target="_blank" rel="noopener"
               onclick="_trackPlaybook('bundle')"
               class="flex-shrink-0 ml-4 text-xs text-indigo-400 hover:text-indigo-300 border border-indigo-800 hover:border-indigo-600 px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap">
                View Bundle →
            </a>
        </div>

        <p class="text-xs text-gray-600 mt-3 text-center">By <a href="https://gingiris.com" target="_blank" class="hover:text-gray-400 transition-colors">Gingiris</a> · Focused on global product growth methodology</p>
    </div>`;
}

function _pickPlaybook(sections) {
    const gh  = sections.github_oss  || {};
    const ph  = sections.producthunt || {};
    const biz = sections.bizmodel    || {};
    const model = biz.model_type     || {};

    // OSS product with meaningful stars → OSS guide
    if (gh.found && (gh.stars || 0) > 500) return 'oss';

    // Multiple PH launches or high votes → launch guide with case studies
    const otherLaunches = (ph.other_launches || []).length;
    if (ph.found && otherLaunches >= 1) return 'launch';

    // Single PH launch → PH guide
    if (ph.found && (ph.votes || 0) > 100) return 'ph';

    // B2B / Enterprise model
    if (model.has_enterprise) return 'b2b';

    // Default: PH guide (most universally applicable)
    return 'ph';
}

function _trackPlaybook(key) {
    // Simple client-side tracking via beacon (non-blocking)
    try {
        const data = JSON.stringify({ type: 'playbook_click', key, ts: Date.now() });
        navigator.sendBeacon && navigator.sendBeacon('/api/track', data);
    } catch (_) {}
}

function _pbEsc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}
function _pbEscAttr(s) {
    return String(s || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}
