let currentJobId = null;
let analysisStartTime = null;
let timerInterval = null;

// ── URL validation ──────────────────────────────────────────────────────────
function normalizeUrl(raw) {
    raw = raw.trim();
    if (!raw) return null;
    // Accept bare domains like "lovable.dev" → prepend https://
    if (!/^https?:\/\//i.test(raw)) raw = 'https://' + raw;
    try { new URL(raw); return raw; } catch { return null; }
}

function showError(msg) {
    const el = document.getElementById('error-msg');
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
}
function clearError() {
    const el = document.getElementById('error-msg');
    if (el) el.classList.add('hidden');
}

// ── Example chips ───────────────────────────────────────────────────────────
function fillExample(domain) {
    document.getElementById('url-input').value = domain;
    document.getElementById('url-input').focus();
    clearError();
}

// ── History (localStorage) ──────────────────────────────────────────────────
const HISTORY_KEY = 'analook_history';
const MAX_HISTORY = 5;

function saveToHistory(jobId, url, productName) {
    let hist = loadHistoryRaw();
    hist = hist.filter(h => h.url !== url); // dedupe by url
    hist.unshift({ jobId, url, productName: productName || url, ts: Date.now() });
    hist = hist.slice(0, MAX_HISTORY);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(hist)); } catch {}
    renderHistory();
}

function loadHistoryRaw() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch { return []; }
}

function renderHistory() {
    const hist = loadHistoryRaw();
    const section = document.getElementById('history-section');
    const list = document.getElementById('history-list');
    if (!section || !list || hist.length === 0) {
        if (section) section.classList.add('hidden');
        return;
    }
    section.classList.remove('hidden');
    list.innerHTML = hist.map(h => {
        const ago = formatAgo(h.ts);
        return `<div class="history-item flex items-center justify-between bg-gray-900 border border-gray-800 rounded-lg px-4 py-2.5 cursor-pointer transition-colors" onclick="loadSharedReport('${esc(h.jobId)}')">
            <div>
                <span class="text-sm font-medium text-white">${esc(h.productName)}</span>
                <span class="ml-2 text-xs text-gray-500">${esc(h.url)}</span>
            </div>
            <span class="text-xs text-gray-600 flex-shrink-0 ml-4">${ago}</span>
        </div>`;
    }).join('');
}

function formatAgo(ts) {
    const s = Math.round((Date.now() - ts) / 1000);
    if (s < 60) return `${s}秒前`;
    if (s < 3600) return `${Math.round(s/60)}分钟前`;
    if (s < 86400) return `${Math.round(s/3600)}小时前`;
    return `${Math.round(s/86400)}天前`;
}

// ── Analysis start ──────────────────────────────────────────────────────────
async function startAnalysis() {
    clearError();
    const rawUrl = document.getElementById('url-input').value.trim();
    const normalized = normalizeUrl(rawUrl);
    if (!normalized) {
        showError('请输入有效的竞品网址，例如 lovable.dev 或 https://linear.app');
        document.getElementById('url-input').focus();
        return;
    }
    const name = document.getElementById('name-input').value.trim() || null;
    const btn = document.getElementById('start-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="inline-block animate-spin mr-1">⏳</span> 分析中...';

    document.getElementById('hero-section')?.classList.add('hidden');
    document.getElementById('history-section')?.classList.add('hidden');
    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('report-section').classList.add('hidden');

    // Reset progress bars
    document.querySelectorAll('.prog-bar-fill').forEach(b => {
        b.style.width = '0%';
        b.className = 'prog-bar-fill h-full bg-blue-500 rounded-full transition-all duration-500';
    });
    document.querySelectorAll('.status-icon').forEach(i => i.textContent = '⏳');

    analysisStartTime = Date.now();
    startTimer();

    try {
        const resp = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: normalized, product_name: name }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `服务器错误 ${resp.status}`);
        }
        const data = await resp.json();
        currentJobId = data.job_id;
        pollStatus();
    } catch (e) {
        showError('启动失败：' + e.message);
        btn.disabled = false;
        btn.innerHTML = '🚀 开始调研';
        stopTimer();
        document.getElementById('progress-section').classList.add('hidden');
        document.getElementById('hero-section')?.classList.remove('hidden');
        renderHistory();
    }
}

// ── Timer ───────────────────────────────────────────────────────────────────
function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        const elapsed = Math.round((Date.now() - analysisStartTime) / 1000);
        const el = document.getElementById('prog-timer');
        if (el) el.textContent = `已用时 ${elapsed} 秒`;
    }, 1000);
}

function stopTimer() {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
    const elapsed = Math.round((Date.now() - analysisStartTime) / 1000);
    const el = document.getElementById('prog-timer');
    if (el) el.textContent = `✅ 完成，共用时 ${elapsed} 秒`;
}

// ── Poll status ─────────────────────────────────────────────────────────────
async function pollStatus() {
    if (!currentJobId) return;
    try {
        const resp = await fetch(`/api/status/${currentJobId}`);
        const data = await resp.json();
        const statusMap = { pending: [0, '⏳'], running: [50, '🔄'], done: [100, '✅'], error: [100, '❌'] };
        for (const [key, status] of Object.entries(data.progress || {})) {
            const el = document.getElementById(`prog-${key}`);
            if (!el) continue;
            const icon = el.querySelector('.status-icon');
            const bar = el.querySelector('.prog-bar-fill');
            const [, emoji] = statusMap[status] || [0, '⏳'];
            if (icon) icon.textContent = emoji;
            if (bar) {
                if (status === 'running') {
                    const elapsed = (Date.now() - analysisStartTime) / 1000;
                    const estimated = key === 'report' ? 25 : 20;
                    bar.style.width = Math.min(90, (elapsed / estimated) * 80 + 10) + '%';
                } else if (status === 'done') {
                    bar.style.width = '100%';
                    bar.classList.remove('bg-blue-500');
                    bar.classList.add('bg-green-500');
                } else if (status === 'error') {
                    bar.style.width = '100%';
                    bar.classList.remove('bg-blue-500');
                    bar.classList.add('bg-red-500');
                }
            }
        }
        if (data.status === 'completed') {
            stopTimer();
            await loadReport();
        } else if (data.status === 'error') {
            stopTimer();
            showError('分析过程中出错，请刷新重试');
            const btn = document.getElementById('start-btn');
            if (btn) { btn.disabled = false; btn.innerHTML = '🚀 开始调研'; }
        } else {
            setTimeout(pollStatus, 1200);
        }
    } catch (e) {
        setTimeout(pollStatus, 2000);
    }
}

// ── Load & render report ────────────────────────────────────────────────────
async function loadReport() {
    try {
        const resp = await fetch(`/api/report/${currentJobId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const report = await resp.json();

        document.getElementById('progress-section').classList.add('hidden');
        document.getElementById('report-section').classList.remove('hidden');
        document.getElementById('input-section').classList.add('hidden');
        document.getElementById('hero-section')?.classList.add('hidden');

        // Save to history
        const meta = report.meta || {};
        const urlForHistory = meta.url || document.getElementById('url-input')?.value || '';
        saveToHistory(currentJobId, urlForHistory, meta.product_name);

        // Summary card
        renderSummaryCard(report);

        // Sections
        renderWebsite(report.sections.website_analysis || {});
        renderProductHunt(report.sections.producthunt || {});
        renderSocial(report.sections.social_media || {});
        renderPropagation(report.sections.propagation || {});
        renderTraffic(report.sections.traffic_analysis || {});
        renderPeaks(report.sections.traffic_peaks || {});
        renderGrowth(report.sections.growth_analysis || {});
        renderInsights(report.sections.ai_insights || {});
        if (typeof renderSummary === 'function') renderSummary(report.sections.summary || {});
        renderStrategy(report.sections.growth_strategy || {});

        // Reset start button
        const btn = document.getElementById('start-btn');
        if (btn) { btn.disabled = false; btn.innerHTML = '🚀 开始调研'; }
    } catch (e) {
        showError('报告加载失败：' + e.message);
    }
}

// ── Summary card ────────────────────────────────────────────────────────────
function renderSummaryCard(report) {
    const container = document.getElementById('section-summary-card');
    if (!container) return;
    const meta = report.meta || {};
    const s = report.sections || {};
    const traffic = s.traffic_analysis || {};
    const social = s.social_media || {};
    const ph = s.producthunt || {};
    const ws = s.website_analysis || {};

    const monthlyTraffic = traffic.monthly_organic_traffic || traffic.monthly_visits || null;
    const trafficStr = monthlyTraffic ? fmtNum(monthlyTraffic) + '/月' : '—';
    const firstSeen = ws.first_seen || '—';
    const phScore = ph.score || ph.votes_count || null;
    const phStr = phScore ? `${fmtNum(phScore)} 票` : (ph.found ? '已上线' : '—');
    const twitterFollowers = social.twitter?.followers || social.twitter?.followers_count || null;
    const twStr = twitterFollowers ? fmtNum(twitterFollowers) : '—';

    container.innerHTML = `<div class="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div class="flex items-start justify-between mb-4">
            <div>
                <h3 class="text-lg font-bold text-white">${esc(meta.product_name || '竞品')}</h3>
                <a href="${esc(meta.url || '')}" target="_blank" class="text-xs text-blue-400 hover:underline">${esc(meta.url || '')}</a>
            </div>
            <span class="text-xs text-gray-600">${meta.generated_at ? new Date(meta.generated_at).toLocaleString('zh-CN') : ''}</span>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">月均流量</div>
                <div class="text-xl font-bold text-white">${trafficStr}</div>
            </div>
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">Twitter 粉丝</div>
                <div class="text-xl font-bold text-white">${twStr}</div>
            </div>
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">Product Hunt</div>
                <div class="text-xl font-bold text-white">${phStr}</div>
            </div>
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">首次出现</div>
                <div class="text-xl font-bold text-white">${esc(firstSeen)}</div>
            </div>
        </div>
    </div>`;
}

function fmtNum(n) {
    n = Number(n);
    if (isNaN(n)) return '—';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
}

// ── New analysis ────────────────────────────────────────────────────────────
function newAnalysis() {
    document.getElementById('report-section').classList.add('hidden');
    document.getElementById('input-section').classList.remove('hidden');
    document.getElementById('hero-section')?.classList.remove('hidden');
    document.getElementById('url-input').value = '';
    document.getElementById('name-input').value = '';
    clearError();
    renderHistory();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Load shared report ──────────────────────────────────────────────────────
async function loadSharedReport(jobId) {
    currentJobId = jobId;
    document.getElementById('input-section').classList.add('hidden');
    document.getElementById('hero-section')?.classList.add('hidden');
    document.getElementById('history-section')?.classList.add('hidden');
    document.getElementById('progress-section').classList.add('hidden');
    await loadReport();
}

// ── Export & share ──────────────────────────────────────────────────────────
async function exportMarkdown() {
    if (!currentJobId) return;
    window.open(`/api/export/${currentJobId}`, '_blank');
}

async function shareReport() {
    if (!currentJobId) return;
    const btn = document.getElementById('share-btn');
    try {
        const resp = await fetch(`/api/share/${currentJobId}`);
        const data = await resp.json();
        if (data.error) { showError('分享失败: ' + data.error); return; }
        const fullUrl = `${window.location.origin}${data.share_url}`;
        if (navigator.clipboard) {
            await navigator.clipboard.writeText(fullUrl);
        } else {
            prompt('复制分享链接：', fullUrl);
        }
        const orig = btn.innerHTML;
        btn.innerHTML = '✅ 已复制';
        btn.classList.add('bg-green-900', 'border-green-700');
        setTimeout(() => { btn.innerHTML = orig; btn.classList.remove('bg-green-900', 'border-green-700'); }, 3000);
    } catch (e) {
        showError('分享失败：' + e.message);
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function esc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('url-input')?.addEventListener('keypress', e => {
        if (e.key === 'Enter') startAnalysis();
    });

    // Render history on load
    renderHistory();

    // Auto-load shared report if URL matches /report/{job_id}
    const pathMatch = window.location.pathname.match(/^\/report\/([a-f0-9]+)/);
    if (pathMatch) {
        loadSharedReport(pathMatch[1]).catch(() => {
            document.querySelector('main').innerHTML =
                '<div class="text-center py-8 text-red-400">报告不存在或已过期</div>';
        });
    }
});
