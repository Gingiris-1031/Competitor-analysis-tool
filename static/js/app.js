let currentJobId = null;
let analysisStartTime = null;
let timerInterval = null;
let currentMode = 'url'; // 'url' | 'text' | 'pdf'

// ── URL validation ──────────────────────────────────────────────────────────
function normalizeUrl(raw) {
    raw = raw.trim();
    if (!raw) return null;
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

// ── Mode switching ───────────────────────────────────────────────────────────
function switchMode(mode) {
    currentMode = mode;
    clearError();
    const modes = ['url', 'text', 'pdf'];
    modes.forEach(m => {
        const tab = document.getElementById(`tab-${m}`);
        const panel = document.getElementById(`panel-${m}`);
        if (tab) {
            tab.classList.toggle('bg-blue-600', m === mode);
            tab.classList.toggle('text-white', m === mode);
            tab.classList.toggle('text-gray-400', m !== mode);
            tab.classList.toggle('bg-gray-800', m !== mode);
        }
        if (panel) panel.classList.toggle('hidden', m !== mode);
    });
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
    hist = hist.filter(h => h.url !== url);
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
    if (currentMode === 'text') return startTextAnalysis();
    if (currentMode === 'pdf') return startPdfAnalysis();

    clearError();

    // ── Auth 检查：未登录则弹出登录框 ─────────────────────────────────────
    if (window._analookAuth && !window._analookAuth.user) {
        window._analookAuth.showModal();
        return;
    }

    const rawUrl = document.getElementById('url-input').value.trim();
    const normalized = normalizeUrl(rawUrl);
    if (!normalized) {
        showError('请输入有效的竞品网址，例如 lovable.dev 或 https://linear.app');
        document.getElementById('url-input').focus();
        return;
    }
    const name = document.getElementById('name-input').value.trim() || null;
    _beginProgress('🌐 正在分析竞品官网...');

    // 附带 Auth token
    const token = window._analookAuth?.getToken();
    const authHeaders = token ? { 'Authorization': `Bearer ${token}` } : {};

    try {
        const resp = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify({ url: normalized, product_name: name }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            // 积分不足 → 友好提示
            if (resp.status === 402) {
                _abortProgress('');
                showError('⚡ 积分不足！免费用户每月 3 次，升级 Pro 可获得 50 次。');
                return;
            }
            // 未登录 → 弹出登录框
            if (resp.status === 401) {
                _abortProgress('');
                window._analookAuth?.showModal();
                return;
            }
            throw new Error(err.detail || `服务器错误 ${resp.status}`);
        }
        const data = await resp.json();
        currentJobId = data.job_id;
        saveToHistory(data.job_id, normalized, name || normalized);
        pollStatus();
    } catch (e) {
        _abortProgress('启动失败：' + e.message);
    }
}

async function startTextAnalysis() {
    clearError();
    const text = (document.getElementById('text-input')?.value || '').trim();
    const name = (document.getElementById('text-name-input')?.value || '').trim() || '产品';
    if (!text || text.length < 30) {
        showError('请输入至少 30 个字的产品描述');
        return;
    }
    _beginProgress('📝 正在分析产品描述...');
    try {
        const resp = await fetch('/api/analyze-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, product_name: name }),
        });
        if (!resp.ok) throw new Error(`服务器错误 ${resp.status}`);
        const data = await resp.json();
        currentJobId = data.job_id;
        saveToHistory(data.job_id, `[描述] ${name}`, name);
        pollStatus();
    } catch (e) {
        _abortProgress('启动失败：' + e.message);
    }
}

async function startPdfAnalysis() {
    clearError();
    const fileInput = document.getElementById('pdf-input');
    const file = fileInput?.files?.[0];
    if (!file) { showError('请选择一个 PDF 文件'); return; }
    if (file.size > 20 * 1024 * 1024) { showError('PDF 文件不能超过 20MB'); return; }
    const name = (document.getElementById('pdf-name-input')?.value || '').trim() || file.name.replace('.pdf', '');
    _beginProgress('📄 正在解析 PDF 内容...');
    try {
        const form = new FormData();
        form.append('file', file);
        form.append('product_name', name);
        const resp = await fetch('/api/analyze-pdf', { method: 'POST', body: form });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `服务器错误 ${resp.status}`);
        }
        const data = await resp.json();
        currentJobId = data.job_id;
        saveToHistory(data.job_id, `[PDF] ${name}`, name);
        pollStatus();
    } catch (e) {
        _abortProgress('启动失败：' + e.message);
    }
}

function _beginProgress(label) {
    const btn = document.getElementById('start-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="inline-block animate-spin mr-1">⏳</span> 分析中...';

    document.getElementById('hero-section')?.classList.add('hidden');
    document.getElementById('history-section')?.classList.add('hidden');
    document.getElementById('input-section').classList.add('hidden');
    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('report-section').classList.add('hidden');
    document.getElementById('cancel-btn')?.classList.remove('hidden');

    const progLabel = document.getElementById('prog-label');
    if (progLabel) progLabel.textContent = label;

    document.querySelectorAll('.prog-bar-fill').forEach(b => {
        b.style.width = '0%';
        b.className = 'prog-bar-fill h-full bg-blue-500 rounded-full transition-all duration-500';
    });
    document.querySelectorAll('.status-icon').forEach(i => i.textContent = '⏳');

    analysisStartTime = Date.now();
    startTimer();
}

function _abortProgress(msg) {
    showError(msg);
    const btn = document.getElementById('start-btn');
    btn.disabled = false;
    btn.innerHTML = '🚀 开始调研';
    stopTimer();
    document.getElementById('progress-section').classList.add('hidden');
    document.getElementById('input-section').classList.remove('hidden');
    document.getElementById('hero-section')?.classList.remove('hidden');
    document.getElementById('cancel-btn')?.classList.add('hidden');
    renderHistory();
}

// ── Cancel analysis ──────────────────────────────────────────────────────────
async function cancelAnalysis() {
    if (!currentJobId) return;
    const btn = document.getElementById('cancel-btn');
    if (btn) { btn.disabled = true; btn.textContent = '取消中...'; }
    try {
        await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
    } catch {}
    // Reset UI
    const startBtn = document.getElementById('start-btn');
    if (startBtn) { startBtn.disabled = false; startBtn.innerHTML = '🚀 开始调研'; }
    stopTimer();
    document.getElementById('progress-section').classList.add('hidden');
    document.getElementById('input-section').classList.remove('hidden');
    document.getElementById('hero-section')?.classList.remove('hidden');
    if (btn) { btn.classList.add('hidden'); btn.disabled = false; btn.textContent = '⏹ 停止分析'; }
    currentJobId = null;
    renderHistory();
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
            document.getElementById('cancel-btn')?.classList.add('hidden');
            await loadReport();
        } else if (data.status === 'cancelled') {
            // already handled by cancelAnalysis()
        } else if (data.status === 'error') {
            stopTimer();
            document.getElementById('cancel-btn')?.classList.add('hidden');
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
        if (report.error) throw new Error(report.error);

        document.getElementById('progress-section').classList.add('hidden');
        document.getElementById('report-section').classList.remove('hidden');
        document.getElementById('input-section').classList.add('hidden');

        // Save to history
        const meta = report.meta || {};
        const urlForHistory = meta.url || document.getElementById('url-input')?.value || '';
        if (urlForHistory && urlForHistory !== '—') saveToHistory(currentJobId, urlForHistory, meta.product_name);

        // Render summary card
        renderSummaryCard(report);

        // Render all sections
        renderWebsite(report.sections.website_analysis || {});
        if (typeof renderGithub === 'function') renderGithub(report.sections.github_oss || {});
        renderProductHunt(report.sections.producthunt || {});
        renderSocial(report.sections.social_media || {});
        renderPropagation(report.sections.propagation || {});
        renderTraffic(report.sections.traffic_analysis || {});
        if (typeof renderPricing === 'function') renderPricing(report.sections.pricing || {});
        if (typeof renderBizmodel === 'function') renderBizmodel(report.sections.bizmodel || {});
        if (typeof renderFunding === 'function') renderFunding(report.sections.funding || {});
        if (typeof renderPR === 'function') renderPR(report.sections.pr_news || {});
        renderPeaks(report.sections.traffic_peaks || {});
        renderGrowth(report.sections.growth_analysis || {});
        renderInsights(report.sections.ai_insights || report.sections.ai_summary || {});
        if (typeof renderSummary === 'function') renderSummary(report.sections.summary || {});
        renderStrategy(report.sections.growth_strategy || {});
        if (typeof renderPlaybooks === 'function') renderPlaybooks(report);

        document.getElementById('hero-section')?.classList.add('hidden');

        const btn = document.getElementById('start-btn');
        if (btn) { btn.disabled = false; btn.innerHTML = '🚀 开始调研'; }
    } catch (e) {
        showError('加载报告失败：' + e.message);
        const btn = document.getElementById('start-btn');
        if (btn) { btn.disabled = false; btn.innerHTML = '🚀 开始调研'; }
    }
}

// ── Summary card ────────────────────────────────────────────────────────────
function renderSummaryCard(report) {
    const el = document.getElementById('section-summary-card');
    if (!el) return;
    const s = report.sections || {};
    const traffic = s.traffic_analysis?.domain_rank || {};
    const social = s.social_media?.channels || {};
    const ph = s.producthunt || {};
    const ws = s.website_analysis || {};

    const monthlyTraffic = traffic.organic_traffic || 0;
    let twitterFollowers = 0;
    for (const v of Object.values(social)) {
        if (v.detected && v.followers) { twitterFollowers = v.followers; break; }
    }
    const phScore = ph.found ? ph.votes : null;
    const firstSeen = ws.first_seen || '—';

    const twStr = twitterFollowers ? fmtNum(twitterFollowers) : '—';
    const trafficStr = monthlyTraffic ? fmtNum(monthlyTraffic) + '/mo' : '—';
    const phStr = phScore ? `⬆${fmtNum(phScore)}` : '未上线';

    el.innerHTML = `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-3">核心指标</div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
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
    try {
        const resp = await fetch(`/api/export/${currentJobId}`);
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            showError(data.error || '导出失败，报告尚未生成');
            return;
        }
        const text = await resp.text();
        const blob = new Blob([text], { type: 'text/markdown; charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `analook_report.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (e) {
        showError('导出失败：' + e.message);
    }
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
    document.getElementById('text-input')?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && e.ctrlKey) startAnalysis();
    });

    renderHistory();

    const pathMatch = window.location.pathname.match(/^\/report\/([a-f0-9]+)/);
    if (pathMatch) {
        loadSharedReport(pathMatch[1]).catch(() => {
            document.querySelector('main').innerHTML =
                '<div class="text-center py-8 text-red-400">报告不存在或已过期</div>';
        });
    }
});

