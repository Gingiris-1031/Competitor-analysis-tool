/* render-playbooks.js — Gingiris 工具包上下文推荐（转化优先设计） */

const _PLAYBOOKS = {
    oss: {
        title: "Open-Source Project Integrated Marketing Action Manual",
        desc:  "开源项目从 0 到 10K Stars 的完整营销执行框架：社区冷启动、GitHub Trending、HN/PH 发布节奏、开发者内容策略",
        url:   "https://gingiris.gumroad.com/l/vhmkew",
        tag:   "🌟 开源增长",
        cta:   "获取开源营销手册",
        why:   "你刚分析的竞品是开源产品 — 这份手册覆盖完整复制路径",
    },
    ph: {
        title: "Product Hunt Launch Action Guide",
        desc:  "Product Hunt 发布全流程：选时机、造势期、发布当天执行 SOP、复盘优化，含真实案例拆解",
        url:   "https://gingiris.gumroad.com/l/zxamur",
        tag:   "🚀 PH 发布",
        cta:   "获取 PH 发布手册",
        why:   "竞品通过 Product Hunt 完成冷启动 — 这份手册教你复制同样的路径",
    },
    launch: {
        title: "AI Product Global Launch Guide (with Case Studies)",
        desc:  "AI 产品出海全球发布策略：多波 Launch 节奏、社区造势、媒体触达，含 10+ 真实案例拆解",
        url:   "https://gingiris.gumroad.com/l/nxkifd",
        tag:   "🌍 全球发布",
        cta:   "获取发布策略指南",
        why:   "竞品经历多次 Launch 爆发期 — 这份指南帮你规划同样的增长节点",
    },
    b2b: {
        title: "AI Global B2B Product Full-Lifecycle Growth Guide",
        desc:  "B2B SaaS 全生命周期增长策略：ICP 定义、GTM 路径、Enterprise 销售动作、客户成功体系",
        url:   "https://gingiris.gumroad.com/l/zaarq",
        tag:   "🏢 B2B 增长",
        cta:   "获取 B2B 增长指南",
        why:   "竞品已验证 B2B 企业级变现路径 — 这份指南帮你系统复制",
    },
    bundle: {
        title: "Gingiris Complete Global Launch Playbook Bundle",
        desc:  "包含以上全部手册 + 独家工具模板，一次获取 Gingiris 完整增长方法论",
        url:   "https://gingiris.gumroad.com/l/gingiris-complete-global-launch-bundle",
        tag:   "📦 全套合集",
        cta:   "获取完整 Playbook Bundle",
        why:   "",
    },
};

function renderPlaybooks(report) {
    const el = document.getElementById('section-playbooks');
    if (!el) return;

    const sections = report.sections || {};
    const meta     = report.meta    || {};
    const name     = meta.product_name || '竞品';

    const pick   = _pickPlaybook(sections);
    const main   = _PLAYBOOKS[pick];
    const bundle = _PLAYBOOKS.bundle;

    el.innerHTML = `
    <div class="bg-gradient-to-br from-gray-900 via-gray-900 to-indigo-950/30 border border-indigo-800/40 rounded-xl p-6">

        <!-- Header -->
        <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-medium text-indigo-400 uppercase tracking-widest">Gingiris 工具包推荐</span>
        </div>
        <p class="text-sm text-gray-400 mb-5">
            你刚完成了对 <strong class="text-white">${_pbEsc(name)}</strong> 的深度拆解 — 以下是帮你直接复制这套增长路径的执行手册
        </p>

        <!-- Primary recommendation -->
        <div class="bg-gray-800/60 border border-indigo-700/50 rounded-xl p-5 mb-4 relative overflow-hidden">
            <div class="absolute top-0 right-0 bg-indigo-600 text-white text-xs font-medium px-3 py-1 rounded-bl-lg">最相关推荐</div>

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
                    <div class="text-sm font-medium text-gray-200">想要完整方法论？</div>
                    <div class="text-xs text-gray-500">Gingiris Complete Global Launch Playbook Bundle — 全套合集，一次获取</div>
                </div>
            </div>
            <a href="${_pbEscAttr(bundle.url)}" target="_blank" rel="noopener"
               onclick="_trackPlaybook('bundle')"
               class="flex-shrink-0 ml-4 text-xs text-indigo-400 hover:text-indigo-300 border border-indigo-800 hover:border-indigo-600 px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap">
                查看合集 →
            </a>
        </div>

        <p class="text-xs text-gray-600 mt-3 text-center">由 <a href="https://gingiris.com" target="_blank" class="hover:text-gray-400 transition-colors">Gingiris</a> 出品 · 专注出海产品增长方法论</p>
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
