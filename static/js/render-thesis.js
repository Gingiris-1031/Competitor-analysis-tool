/* 核心论断 Thesis + 公开增长成熟度分 —— 报告最顶部（总分总的「总」）。
   判断先行：用户一进报告先看到全局判断 + 分数灯，再往下看分维度诊断。
   维度标签按 report 语言用 key 本地化，避免 EN 报告混中文。 */
function renderThesis(thesis, score, lang) {
    const c = document.getElementById('section-thesis');
    if (!c) return;
    if (!thesis || !thesis.headline) { c.innerHTML = ''; return; }
    const zh = !(lang || '').startsWith('en');
    const t = (cn, en) => zh ? cn : en;

    const dimLabel = {
        traffic: ['流量体量', 'Traffic'], seo: ['SEO 强度', 'SEO strength'],
        commercialization: ['商业化', 'Commercialization'],
        distribution: ['分发/社媒', 'Distribution'], momentum: ['社区/势能', 'Community & momentum'],
    };
    const gl = k => (dimLabel[k] || ['', ''])[zh ? 0 : 1];
    const gradeColor = { green: '#4ade80', yellow: '#fbbf24', red: '#f87171' };

    const dims = (score && score.dimensions) || [];
    const overall = (score && score.overall_score) != null ? score.overall_score : (thesis.score || 0);
    const band = thesis.band || '';

    let lights = '';
    for (const d of dims) {
        const col = gradeColor[d.grade] || '#9ca3af';
        lights += `<div style="display:flex; align-items:center; gap:6px; font-size:12px; color:#9ca3af;">
            <span style="width:9px; height:9px; border-radius:50%; background:${col}; box-shadow:0 0 6px ${col}80;"></span>
            ${esc(gl(d.key) || d.label || d.key)}</div>`;
    }

    c.innerHTML = `
    <div style="background:linear-gradient(135deg,#16161A 0%,#1a1410 100%); border:1px solid rgba(251,146,60,0.25); border-radius:16px; padding:22px 24px; margin-bottom:20px;">
        <div style="display:flex; align-items:center; gap:20px; flex-wrap:wrap;">
            <div style="display:flex; align-items:baseline; gap:4px;">
                <span style="font-family:'Instrument Serif',Georgia,serif; font-size:52px; line-height:1; color:#FB923C;">${overall}</span>
                <span style="font-size:18px; color:#6b7280;">/100</span>
            </div>
            <div style="flex:1; min-width:220px;">
                <div style="font-size:11px; letter-spacing:0.1em; text-transform:uppercase; color:#FB923C; font-weight:700; margin-bottom:4px;">${t('核心论断 · 公开增长成熟度', 'Verdict · Public Growth Maturity')}</div>
                <div style="font-size:14.5px; line-height:1.65; color:#e5e7eb;">${esc(thesis.headline)}</div>
            </div>
        </div>
        <div style="display:flex; gap:18px; flex-wrap:wrap; margin-top:16px; padding-top:14px; border-top:1px solid rgba(255,255,255,0.06);">
            ${lights}
        </div>
        <div style="font-size:10px; color:#4b5563; margin-top:10px;">${t('基于公开信号（流量 / SEO / 商业化 / 分发 / 社区势能）打分。往下看分维度诊断 →', 'Scored from public signals (traffic / SEO / commercialization / distribution / community). Dimensional diagnosis below →')}</div>
    </div>`;
}
