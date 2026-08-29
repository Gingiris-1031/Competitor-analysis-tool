/* Research-map navigation for the structured competitor report.
 * Keeps the report readable as evidence modules grow: users start from a
 * decision, then choose the evidence chapter that answers their next question.
 */
function renderResearchMap(report) {
    const el = document.getElementById('section-research-map');
    if (!el) return;

    const s = report?.sections || {};
    const zh = (report?.meta?.lang || document.documentElement.lang || '').toLowerCase().startsWith('zh');
    const copy = zh ? {
        eyebrow: '研究路径', title: '从判断到证据，而不是从数据源开始',
        subtitle: '按下面顺序阅读；每章只回答一个关键决策问题。',
        chapters: [
            ['chapter-actions', '01', '决策摘要', '先看该复制、避开和验证什么'],
            ['chapter-positioning', '02', '定位与商业模式', '它卖给谁，靠什么变现'],
            ['chapter-archaeology', '03', '增长考古', '它在成名前做了什么'],
            ['chapter-channels', '04', '渠道与传播', '增长是如何被获得与放大的'],
            ['chapter-evidence', '05', '证据与来源', '结论的来源、时间与可信度'],
        ],
    } : {
        eyebrow: 'Research path', title: 'Read from decision to evidence',
        subtitle: 'Each chapter answers one decision question — not another data-source list.',
        chapters: [
            ['chapter-actions', '01', 'Decision brief', 'What to copy, avoid, and validate first'],
            ['chapter-positioning', '02', 'Positioning & monetization', 'Who they sell to and how they capture value'],
            ['chapter-archaeology', '03', 'Growth archaeology', 'What they did before they became visible'],
            ['chapter-channels', '04', 'Channels & propagation', 'How growth is acquired and amplified'],
            ['chapter-evidence', '05', 'Evidence & sources', 'Source, timing, and confidence behind each claim'],
        ],
    };

    const available = {
        'chapter-positioning': Boolean(s.pricing || s.bizmodel || s.website_analysis),
        'chapter-archaeology': Boolean(s.website_analysis || s.producthunt || s.github_oss || s.funding),
        'chapter-channels': Boolean(s.traffic_analysis || s.social_media || s.propagation),
        'chapter-actions': Boolean(s.ai_insights || s.growth_analysis || s.growth_strategy),
        'chapter-evidence': Boolean(s.references?.length),
    };
    const cards = copy.chapters.map(([id, number, title, description]) => `
        <button type="button" class="research-map-card ${available[id] ? '' : 'is-pending'}" data-target="${id}">
            <span class="research-map-number">${number}</span>
            <span><strong>${esc(title)}</strong><small>${esc(description)}</small></span>
            <span class="research-map-state">${available[id] ? '✓' : '—'}</span>
        </button>`).join('');

    el.innerHTML = `<section class="research-map fade-in" aria-label="${esc(copy.eyebrow)}">
        <div class="research-map-heading"><span>${esc(copy.eyebrow)}</span><h3>${esc(copy.title)}</h3><p>${esc(copy.subtitle)}</p></div>
        <div class="research-map-grid">${cards}</div>
    </section>`;
    el.querySelectorAll('[data-target]').forEach((button) => {
        button.addEventListener('click', () => {
            const chapter = document.getElementById(button.dataset.target);
            if (!chapter) return;
            const disclosure = chapter.closest('details');
            if (disclosure) disclosure.open = true;
            chapter.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });
}
