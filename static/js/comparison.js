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

// ── render compare table ───────────────────────────────────────────────────
// Each row = one metric; each column = one competitor. Numeric winners get
// a green highlight. Missing data shows "—".
function renderCompareTable(reports) {
    const valid = reports.filter(r => r.report);
    const thead = document.getElementById('compare-thead');
    const tbody = document.getElementById('compare-tbody');

    thead.innerHTML = `<tr>
        <th class="text-left text-xs text-gray-500 uppercase tracking-wider px-3 py-3 w-44">Metric</th>
        ${valid.map(r => `<th class="col-header text-left px-3 py-3">
            <div class="text-sm font-semibold text-white">${esc(r.label)}</div>
            <div class="text-xs text-gray-500 mt-0.5">${esc(r.jobId || '')}</div>
        </th>`).join('')}
    </tr>`;

    // Rows: (label, extractor fn → value, options)
    const rows = [
        ['Organic Traffic/mo',       r => r.sections?.traffic_analysis?.seo_metrics?.organic_traffic_estimate
                                         ?? r.sections?.traffic_analysis?.domain_rank?.organic_traffic],
        ['Ranked Keywords',          r => r.sections?.traffic_analysis?.domain_rank?.total_keywords],
        ['Top 10 Keywords',          r => r.sections?.traffic_analysis?.domain_rank?.keywords_top10],
        ['Backlinks',                r => r.sections?.traffic_analysis?.seo_metrics?.backlinks
                                         ?? r.sections?.traffic_analysis?.backlinks?.backlinks],
        ['Referring Domains',        r => r.sections?.traffic_analysis?.seo_metrics?.referring_domains
                                         ?? r.sections?.traffic_analysis?.backlinks?.referring_domains],
        ['Domain Authority',         r => r.sections?.traffic_analysis?.seo_metrics?.domain_authority],
        ['Twitter Followers',        r => r.sections?.social_media?.channels?.twitter?.followers],
        ['GitHub Stars',             r => r.sections?.github_oss?.stars],
        ['Product Hunt Votes',       r => r.sections?.producthunt?.votes],
        ['Equiv. Paid Cost',         r => r.sections?.traffic_analysis?.domain_rank?.estimated_paid_cost, { money: true }],
    ];

    // Pick winner per row (highest numeric value)
    tbody.innerHTML = rows.map(([label, fn, opts]) => {
        const rawVals = valid.map(r => {
            try { return fn(r.report); } catch { return null; }
        });
        const numericVals = rawVals.map(v => (typeof v === 'number' ? v : null));
        const maxVal = numericVals.reduce((m, v) => (v !== null && (m === null || v > m)) ? v : m, null);
        return `<tr class="metric-row">
            <td class="px-3 py-2.5 text-xs text-gray-400">${esc(label)}</td>
            ${rawVals.map(v => {
                const display = fmt(v, opts || {});
                const isWinner = typeof v === 'number' && v === maxVal && maxVal !== null && numericVals.filter(n => n === maxVal).length === 1;
                const cls = isWinner ? 'winner' : (display === '—' ? 'loser' : 'text-gray-200');
                return `<td class="px-3 py-2.5 font-mono text-sm ${cls}">${esc(display)}</td>`;
            }).join('')}
        </tr>`;
    }).join('');
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
