/**
 * Multi-competitor comparison page.
 *
 * Accepts 2–4 URLs or Analook job_ids, fetches the corresponding reports via
 * /api/v1/report/{id}, and renders a side-by-side table of key metrics.
 *
 * For raw URLs the page first POSTs to /api/analyze to kick off a job, then
 * polls /api/v1/status/{job_id} until completed. Every fresh analysis deducts
 * 1 credit (Auth required).
 *
 * Design choice: this page is a thin consumer of existing endpoints — no new
 * backend routes. That keeps the MVP scope small and reuses all the existing
 * auth/credit/persistence logic.
 */

const MAX_COLS = 4;
const MIN_COLS = 2;

// ── helpers ────────────────────────────────────────────────────────────────
const esc = s => (s ?? '').toString().replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));

function normalizeUrl(raw) {
    raw = (raw || '').trim();
    if (!raw) return null;
    // Accept bare domains
    if (!/^https?:\/\//i.test(raw)) raw = 'https://' + raw;
    try { new URL(raw); return raw; } catch { return null; }
}

function looksLikeJobId(s) {
    return /^[a-f0-9]{6,64}$/i.test((s || '').trim());
}

function fmt(val, opts = {}) {
    if (val === null || val === undefined || val === '') return '—';
    if (typeof val === 'number') {
        if (opts.money) return '$' + val.toLocaleString();
        return val.toLocaleString();
    }
    if (typeof val === 'object') {
        // Unwrap nested dicts (same defensive pattern as render-traffic.js)
        const n = val.backlinks ?? val.total ?? val.count ?? val.value;
        if (typeof n === 'number') return opts.money ? '$' + n.toLocaleString() : n.toLocaleString();
        return '—';
    }
    return String(val);
}

function showErr(msg) {
    const el = document.getElementById('compare-err');
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
}
function clearErr() {
    const el = document.getElementById('compare-err');
    if (el) el.classList.add('hidden');
}

// ── input rows ─────────────────────────────────────────────────────────────
function addInputRow(prefill = '') {
    const container = document.getElementById('input-rows');
    if (!container) return;
    if (container.children.length >= MAX_COLS) return;
    const idx = container.children.length;
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2';
    row.innerHTML = `
        <span class="text-xs text-gray-500 w-6">${idx + 1}.</span>
        <input type="text" placeholder="linear.app or 8-char job ID"
            class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            value="${esc(prefill)}" />
        <button class="remove-row text-xs text-gray-500 hover:text-red-400 px-2 py-1">✕</button>
    `;
    row.querySelector('.remove-row').addEventListener('click', () => {
        if (container.children.length > MIN_COLS) {
            row.remove();
            renumberRows();
        }
    });
    container.appendChild(row);
    renumberRows();
}

function renumberRows() {
    const rows = document.querySelectorAll('#input-rows > div');
    rows.forEach((r, i) => {
        const label = r.querySelector('span');
        if (label) label.textContent = `${i + 1}.`;
    });
}

function readInputs() {
    return [...document.querySelectorAll('#input-rows input')]
        .map(i => i.value.trim())
        .filter(Boolean);
}

// ── compare action ─────────────────────────────────────────────────────────
async function onCompareClick() {
    clearErr();
    const raw = readInputs();
    if (raw.length < MIN_COLS) return showErr(`At least ${MIN_COLS} competitors required`);
    if (raw.length > MAX_COLS) return showErr(`At most ${MAX_COLS} competitors per comparison`);

    // Classify each input: job_id | url
    const items = raw.map(v => {
        if (looksLikeJobId(v)) return { kind: 'id', value: v, label: v };
        const u = normalizeUrl(v);
        if (!u) return { kind: 'error', value: v, label: v };
        return { kind: 'url', value: u, label: u.replace(/^https?:\/\//, '').replace(/\/$/, '') };
    });

    if (items.some(i => i.kind === 'error')) {
        return showErr('One or more inputs are not a valid URL or job ID');
    }

    // If any URLs present, require auth (analyses deduct credits)
    if (items.some(i => i.kind === 'url')) {
        if (window._analookAuth && !window._analookAuth.user) {
            window._analookAuth.showModal();
            return;
        }
    }

    // Hide input panel, show status
    document.getElementById('input-panel').classList.add('hidden');
    const statusPanel = document.getElementById('status-panel');
    statusPanel.classList.remove('hidden');
    const statusList = document.getElementById('status-list');
    statusList.innerHTML = items.map((it, i) =>
        `<div id="st-${i}"><span class="text-gray-500">[${i + 1}]</span> ${esc(it.label)} — <span class="text-gray-400">queued…</span></div>`
    ).join('');

    // Kick off all jobs in parallel
    const reports = await Promise.all(items.map((it, i) => resolveReport(it, i)));

    if (reports.every(r => !r.report)) {
        showErr('All analyses failed. Check your URLs / credits and retry.');
        document.getElementById('input-panel').classList.remove('hidden');
        statusPanel.classList.add('hidden');
        return;
    }

    statusPanel.classList.add('hidden');
    renderCompareTable(reports);
    document.getElementById('result-panel').classList.remove('hidden');
}

/**
 * Set a row's status text. Accepts trusted HTML (allows <a> tags for
 * actionable links like "upgrade plan"). DO NOT pass user input or
 * server-returned strings to `text` — only hardcoded literals.
 */
function setRowStatus(idx, text, color = 'text-gray-400') {
    const el = document.getElementById(`st-${idx}`);
    if (!el) return;
    const span = el.querySelector('span:last-child');
    if (span) {
        span.className = color;
        span.innerHTML = text;
    }
}

/**
 * Resolve one input to a report.
 * Returns { idx, label, report } where report may be null on failure.
 */
async function resolveReport(item, idx) {
    try {
        let jobId = null;
        if (item.kind === 'id') {
            jobId = item.value;
            setRowStatus(idx, 'fetching cached report…');
        } else {
            // url: start analysis
            setRowStatus(idx, 'starting analysis…');
            const token = window._analookAuth?.getToken?.();
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ url: item.value }),
            });
            if (!res.ok) {
                // Map known status codes to actionable messages instead of
                // "failed to start: 401" which leaves the user guessing.
                let msg;
                if (res.status === 401) {
                    msg = '⚠️ 登录已过期，请刷新页面重新登录';
                    if (window._analookAuth?.showModal) window._analookAuth.showModal();
                } else if (res.status === 402) {
                    msg = '💳 积分不足，<a href="/pricing.html" class="underline">升级套餐</a>';
                } else if (res.status === 503) {
                    msg = '🚧 服务暂时不可用（后端配置错误），稍后再试';
                } else {
                    let body = '';
                    try { body = await res.text(); } catch {}
                    // body is server-returned text — escape before injecting via innerHTML
                    msg = `失败 (${res.status})${body ? ': ' + esc(body.slice(0, 100)) : ''}`;
                }
                setRowStatus(idx, msg, 'text-red-400');
                return { idx, label: item.label, report: null, error: res.status };
            }
            const data = await res.json();
            jobId = data.job_id;
            setRowStatus(idx, 'analyzing… (may take 2–5 min)');
            // Poll status
            jobId = await pollUntilComplete(jobId, idx);
            if (!jobId) {
                return { idx, label: item.label, report: null, error: 'timeout or failed' };
            }
        }
        setRowStatus(idx, 'loading report…');
        const r = await fetch(`/api/v1/report/${jobId}`);
        if (!r.ok) {
            setRowStatus(idx, `report ${jobId}: ${r.status}`, 'text-red-400');
            return { idx, label: item.label, report: null };
        }
        const report = await r.json();
        if (report.error) {
            setRowStatus(idx, `error: ${report.error}`, 'text-red-400');
            return { idx, label: item.label, report: null };
        }
        setRowStatus(idx, '✓ ready', 'text-green-400');
        return { idx, label: item.label, report, jobId };
    } catch (e) {
        setRowStatus(idx, `error: ${e.message || e}`, 'text-red-400');
        return { idx, label: item.label, report: null };
    }
}

async function pollUntilComplete(jobId, idx, maxMs = 6 * 60 * 1000) {
    const start = Date.now();
    // 3s → 5s → 8s polling backoff
    const intervals = [3000, 5000, 8000];
    let attempt = 0;
    while (Date.now() - start < maxMs) {
        const wait = intervals[Math.min(attempt, intervals.length - 1)];
        await new Promise(r => setTimeout(r, wait));
        attempt++;
        try {
            const res = await fetch(`/api/v1/status/${jobId}`);
            if (!res.ok) continue;
            const data = await res.json();
            if (data.status === 'completed') return jobId;
            if (data.status === 'failed') {
                setRowStatus(idx, 'analysis failed', 'text-red-400');
                return null;
            }
            const elapsed = Math.round((Date.now() - start) / 1000);
            setRowStatus(idx, `analyzing… ${elapsed}s`);
        } catch {}
    }
    setRowStatus(idx, 'timeout', 'text-red-400');
    return null;
}

// ── render compare ─────────────────────────────────────────────────────────
// 3 sections: AI verdict cards, strategy radar (6 dims), detailed metrics.
function renderCompareTable(reports) {
    const valid = reports.filter(r => r.report);
    if (!valid.length) return;
    renderVerdicts(valid);
    renderRadar(valid);
    renderMetrics(valid);
}

// ── 1. AI Verdict cards ─────────────────────────────────────────────────────
function renderVerdicts(valid) {
    const grid = document.getElementById('verdict-grid');
    if (!grid) return;
    // Responsive grid: 2 cols if 2 competitors, else min 1fr columns
    grid.style.gridTemplateColumns = `repeat(${valid.length}, minmax(0, 1fr))`;

    grid.innerHTML = valid.map(r => {
        const sections = r.report?.sections || {};
        const ai = sections.ai_insights || {};
        const verdict = ai.verdict || {};
        const oneLiner = verdict.one_line_verdict || '—';
        const killer = verdict.killer_move || '—';
        const pattern = verdict.growth_pattern || '—';
        const repl = verdict.replicability || '';
        const meta = r.report?.meta || {};
        const productName = meta.product_name || r.label || '';
        const url = meta.url || '';

        // Color-code replicability
        const replColor = repl === '高' ? 'text-green-400 bg-green-900/30 border-green-700/50'
                       : repl === '中' ? 'text-yellow-400 bg-yellow-900/30 border-yellow-700/50'
                       : repl === '低' ? 'text-red-400 bg-red-900/30 border-red-700/50'
                       : 'text-gray-400 bg-gray-800 border-gray-700';

        return `<div class="bg-gradient-to-br from-blue-900/20 to-gray-900 border border-gray-800 rounded-xl p-5">
            <div class="flex items-start justify-between mb-3">
                <div class="min-w-0">
                    <div class="text-base font-semibold text-white truncate">${esc(productName)}</div>
                    <div class="text-xs text-gray-500 truncate">${esc(url.replace(/^https?:\/\//, ''))}</div>
                </div>
                ${repl ? `<span class="text-[10px] px-2 py-0.5 rounded-full border ${replColor} font-medium flex-shrink-0">可复制：${esc(repl)}</span>` : ''}
            </div>
            <div class="mb-3">
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Killer Move</div>
                <div class="text-sm text-white font-medium leading-snug">${esc(killer)}</div>
            </div>
            <div class="mb-3">
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Verdict</div>
                <div class="text-sm text-blue-300 leading-snug">${esc(oneLiner)}</div>
            </div>
            <div>
                <div class="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Growth Pattern</div>
                <div class="text-xs text-gray-300">${esc(pattern)}</div>
            </div>
        </div>`;
    }).join('');
}

// ── 2. Strategy Radar (6 dimensions side-by-side) ───────────────────────────
function renderRadar(valid) {
    const wrap = document.getElementById('radar-table');
    if (!wrap) return;
    // Each row = one of the 6 dimensions. Each column = competitor.
    // Bar = score / 100 width. Winner per row gets a glow.
    const radars = valid.map(r => r.report?.sections?.strategy_radar || {});
    const dimList = radars.find(rd => rd.dimensions?.length)?.dimensions || [];
    if (!dimList.length) {
        wrap.innerHTML = `<p class="text-xs text-gray-500 text-center py-4">No strategy radar data available</p>`;
        return;
    }

    // Header: avg score per competitor
    let html = `<div class="grid gap-2 mb-4 pb-4 border-b border-gray-800" style="grid-template-columns: 140px repeat(${valid.length}, minmax(0, 1fr))">
        <div></div>
        ${valid.map(r => {
            const radar = r.report?.sections?.strategy_radar || {};
            const avg = radar.avg_score ?? 0;
            const total = radar.total_score ?? 0;
            return `<div class="text-center">
                <div class="text-2xl font-bold text-white">${avg}</div>
                <div class="text-[10px] text-gray-500">${esc(r.label)} · total ${total}/600</div>
            </div>`;
        }).join('')}
    </div>`;

    // Rows: one per dimension
    for (const dim of dimList) {
        const scores = valid.map(r => r.report?.sections?.strategy_radar?.dimensions?.find(d => d.key === dim.key)?.score ?? 0);
        const max = Math.max(...scores);
        html += `<div class="grid gap-2 items-center mb-2.5" style="grid-template-columns: 140px repeat(${valid.length}, minmax(0, 1fr))">
            <div class="text-xs text-gray-400">${dim.emoji} ${esc(dim.label)}</div>
            ${scores.map(s => {
                const isWinner = s === max && scores.filter(x => x === max).length === 1 && s > 0;
                const barColor = isWinner ? 'bg-green-500' : s >= 60 ? 'bg-blue-500' : s >= 30 ? 'bg-yellow-600' : 'bg-gray-700';
                const txtColor = isWinner ? 'text-green-300' : 'text-gray-300';
                return `<div class="flex items-center gap-2">
                    <div class="flex-1 h-5 bg-gray-800 rounded overflow-hidden">
                        <div class="${barColor} h-full transition-all" style="width:${Math.max(s, 2)}%"></div>
                    </div>
                    <div class="text-xs font-mono ${txtColor} w-8 text-right">${s}</div>
                </div>`;
            }).join('')}
        </div>`;
    }

    wrap.innerHTML = html;
}

// ── 3. Detailed metrics table ──────────────────────────────────────────────
function renderMetrics(valid) {
    const thead = document.getElementById('compare-thead');
    const tbody = document.getElementById('compare-tbody');

    thead.innerHTML = `<tr>
        <th class="text-left text-xs text-gray-500 uppercase tracking-wider px-3 py-3 w-48">Metric</th>
        ${valid.map(r => `<th class="col-header text-left px-3 py-3">
            <div class="text-sm font-semibold text-white">${esc(r.label)}</div>
            <div class="text-xs text-gray-500 mt-0.5">${esc(r.jobId || '')}</div>
        </th>`).join('')}
    </tr>`;

    // Group rows into sections for visual structure.
    const groups = [
        { title: 'Traffic & SEO', rows: [
            ['Organic Traffic/mo',  r => r.sections?.traffic_analysis?.seo_metrics?.organic_traffic_estimate
                                       ?? r.sections?.traffic_analysis?.domain_rank?.organic_traffic],
            ['Ranked Keywords',     r => r.sections?.traffic_analysis?.domain_rank?.total_keywords],
            ['Top 10 Keywords',     r => r.sections?.traffic_analysis?.domain_rank?.keywords_top10],
            ['Domain Authority',    r => r.sections?.traffic_analysis?.seo_metrics?.domain_authority],
            ['Backlinks',           r => r.sections?.traffic_analysis?.seo_metrics?.backlinks
                                       ?? r.sections?.traffic_analysis?.backlinks?.backlinks],
            ['Referring Domains',   r => r.sections?.traffic_analysis?.seo_metrics?.referring_domains
                                       ?? r.sections?.traffic_analysis?.backlinks?.referring_domains],
            ['Equiv. Paid Cost',    r => r.sections?.traffic_analysis?.domain_rank?.estimated_paid_cost, { money: true }],
        ]},
        { title: 'Social & Community', rows: [
            ['Twitter Followers',   r => r.sections?.social_media?.channels?.twitter?.followers],
            ['YouTube Subs',        r => r.sections?.social_media?.channels?.youtube?.subscribers],
            ['Reddit Detected',     r => r.sections?.social_media?.channels?.reddit?.detected ? 'Yes' : '—'],
            ['GitHub Stars',        r => r.sections?.github_oss?.stars],
            ['GitHub Contributors', r => r.sections?.github_oss?.contributors_count],
        ]},
        { title: 'Launch & Product', rows: [
            ['Product Hunt Votes',  r => r.sections?.producthunt?.votes],
            ['PH Reviews',          r => r.sections?.producthunt?.reviews_count],
            ['PH Launches',         r => 1 + (r.sections?.producthunt?.other_launches?.length || 0)],
            ['First Seen (Wayback)', r => (r.sections?.website_analysis?.first_seen || '').slice(0, 10) || null],
            ['Pricing Tiers',       r => r.sections?.pricing?.plans?.length],
            ['Total Funding',       r => r.sections?.funding?.total_raised],
        ]},
        { title: 'Content', rows: [
            ['Has Blog',            r => r.sections?.website_analysis?.current?.features?.blog ? 'Yes' : '—'],
            ['Has Docs',            r => r.sections?.website_analysis?.current?.features?.docs ? 'Yes' : '—'],
            ['Has Changelog',       r => r.sections?.website_analysis?.current?.features?.changelog ? 'Yes' : '—'],
            ['Has Case Studies',    r => r.sections?.website_analysis?.current?.features?.case_study ? 'Yes' : '—'],
        ]},
    ];

    let html = '';
    for (const group of groups) {
        html += `<tr class="bg-gray-850/50">
            <td colspan="${valid.length + 1}" class="px-3 py-2 text-[10px] text-gray-500 uppercase tracking-wider font-semibold border-t border-gray-800 bg-gray-900/60">
                ${esc(group.title)}
            </td>
        </tr>`;
        for (const [label, fn, opts] of group.rows) {
            const rawVals = valid.map(r => { try { return fn(r.report); } catch { return null; }});
            const numericVals = rawVals.map(v => typeof v === 'number' ? v : null);
            const maxVal = numericVals.reduce((m, v) => (v !== null && (m === null || v > m)) ? v : m, null);

            html += `<tr class="metric-row">
                <td class="px-3 py-2 text-xs text-gray-400">${esc(label)}</td>
                ${rawVals.map(v => {
                    const display = fmt(v, opts || {});
                    const isWinner = typeof v === 'number' && v === maxVal && maxVal !== null && maxVal > 0
                                  && numericVals.filter(n => n === maxVal).length === 1;
                    const cls = isWinner ? 'winner' : (display === '—' ? 'loser' : 'text-gray-200');
                    return `<td class="px-3 py-2 font-mono text-sm ${cls}">${esc(display)}</td>`;
                }).join('')}
            </tr>`;
        }
    }
    tbody.innerHTML = html;
}

// ── init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Parse ?ids=a,b,c or ?urls=a,b,c
    const params = new URLSearchParams(window.location.search);
    const ids = (params.get('ids') || '').split(',').map(s => s.trim()).filter(Boolean);
    const urls = (params.get('urls') || '').split(',').map(s => s.trim()).filter(Boolean);
    const prefill = [...ids, ...urls].slice(0, MAX_COLS);

    if (prefill.length === 0) {
        // default: 2 empty rows
        addInputRow();
        addInputRow();
    } else {
        prefill.forEach(p => addInputRow(p));
        while (document.querySelectorAll('#input-rows > div').length < MIN_COLS) addInputRow();
    }

    document.getElementById('add-row-btn')?.addEventListener('click', () => addInputRow());
    document.getElementById('compare-btn')?.addEventListener('click', onCompareClick);

    // Auto-compare ONLY when every input is a cached job_id (cheap: no credits
    // deducted). For `?urls=` params, keep the prefill but require a manual
    // click — a shared link shouldn't be able to burn someone's credits on
    // page load.
    const allCheap = prefill.length >= MIN_COLS
        && ids.length >= MIN_COLS
        && urls.length === 0;
    if (allCheap) {
        setTimeout(onCompareClick, 100);
    }
});
