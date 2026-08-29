/* References — 数据来源引用（Manus 签名：每个数据点带来源 + 抓取日期）。
   提升可信度 + GEO（AI 搜索更爱引用有来源标注的报告）。报告最末（总分总收尾后）。 */
function renderReferences(refs, lang) {
    const c = document.getElementById('section-references');
    if (!c) return;
    if (!refs || !refs.length) { c.innerHTML = ''; return; }
    const zh = !(lang || '').startsWith('en');
    const _esc = (typeof esc === 'function') ? esc : (s => (s || '').toString());

    let rows = '';
    refs.forEach((r, i) => {
        const date = r.date ? `<span style="color:#4b5563; font-size:11px;">${zh ? '抓取 ' : 'fetched '}${_esc(r.date)}</span>` : '';
        const original = /^https?:\/\//i.test(r.url || '')
            ? ` <a href="${_esc(r.url)}" target="_blank" rel="noopener" style="color:#60a5fa; text-decoration:underline; text-underline-offset:2px;">${zh ? '打开原始证据 ↗' : 'Open original evidence ↗'}</a>`
            : '';
        rows += `<div style="display:flex; gap:10px; padding:8px 0; border-top:1px solid rgba(255,255,255,0.05); font-size:12.5px; line-height:1.5;">
            <span style="color:#6b7280; flex:none;">[${i + 1}]</span>
            <span style="color:#d1d5db;"><strong style="color:#e5e7eb;">${_esc(r.source)}</strong> — ${_esc(r.used_for)} ${date}${original}</span>
        </div>`;
    });

    c.innerHTML = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-3">📚 ${zh ? '数据来源 References' : 'References'}</h3>
        <div>${rows}</div>
    </div>`;
}
