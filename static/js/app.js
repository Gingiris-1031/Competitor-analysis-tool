// i18n: zh pages set window._ANALOOK_LANG='zh' before loading shared JS.
// TAAFT rejected the EN site twice for Chinese strings in dynamic UI (2026-07-07).
var _LANG_ZH = (typeof window !== 'undefined') && (window._ANALOOK_LANG === 'zh' || location.pathname.startsWith('/zh'));
var _t = _t || function (en, zh) { return _LANG_ZH ? zh : en; };
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

// ── History (server-side when logged in, localStorage fallback) ────────────
const HISTORY_KEY = 'analook_history';
const MAX_HISTORY = 5;
// null = 未同步过，使用 localStorage; [] = 已同步且服务端为空，要显示空; [...] = 服务端数据
let _serverHistory = null;
let _historySyncSeq = 0; // 防止旧请求覆盖新请求 / 登出后回写

function saveToHistory(jobId, url, productName) {
    let hist = loadHistoryRaw();
    hist = hist.filter(h => h.jobId !== jobId);
    hist.unshift({ jobId, url, productName: productName || url, ts: Date.now() });
    hist = hist.slice(0, MAX_HISTORY);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(hist)); } catch {}
    // 登录用户：乐观更新服务端缓存（按 jobId 去重，避免同 URL 多 job 误删）
    if (_serverHistory !== null) {
        _serverHistory = [
            { jobId, url, productName: productName || url, ts: Date.now() },
            ..._serverHistory.filter(h => h.jobId !== jobId),
        ].slice(0, MAX_HISTORY);
    }
    renderHistory();
}

function loadHistoryRaw() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch { return []; }
}

/**
 * 拉取服务端历史（登录用户）。
 * - 未登录：把 _serverHistory 置 null，回退到 localStorage
 * - 登录且同步成功：_serverHistory 设为数组（可为空数组）
 * - 网络错误：保持 _serverHistory 为 null（fallback localStorage）
 */
async function syncServerHistory() {
    const seq = ++_historySyncSeq;
    const token = window._analookAuth?.getToken?.();
    if (!token) {
        _serverHistory = null;
        renderHistory();
        return;
    }
    try {
        const res = await fetch('/api/v1/reports', { headers: { Authorization: `Bearer ${token}` } });
        // 如果中途有更新的 sync 请求/登出，丢弃这次结果
        if (seq !== _historySyncSeq) return;
        // 二次校验 token（防止 await 期间登出导致写入旧用户数据）
        if (!window._analookAuth?.getToken?.()) {
            _serverHistory = null;
            renderHistory();
            return;
        }
        if (!res.ok) {
            _serverHistory = null;
            renderHistory();
            return;
        }
        const data = await res.json();
        if (seq !== _historySyncSeq) return;
        _serverHistory = (data.reports || []).slice(0, MAX_HISTORY).map(r => {
            const t = r.created_at ? new Date(r.created_at).getTime() : NaN;
            return {
                jobId: r.id,
                url: r.url || '',
                productName: r.product_name || r.url || '',
                ts: Number.isFinite(t) ? t : Date.now(),
            };
        });
        renderHistory();
    } catch (e) {
        if (seq === _historySyncSeq) {
            _serverHistory = null;
            renderHistory();
        }
    }
}

function renderHistory() {
    // _serverHistory !== null 表示已同步成功（可能是空数组），此时不要回退 localStorage
    const hist = (_serverHistory !== null) ? _serverHistory : loadHistoryRaw();
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
    if (s < 60) return _t(`${s}s ago`, `${s}秒前`);
    if (s < 3600) return _t(`${Math.round(s/60)}m ago`, `${Math.round(s/60)}分钟前`);
    if (s < 86400) return _t(`${Math.round(s/3600)}h ago`, `${Math.round(s/3600)}小时前`);
    return _t(`${Math.round(s/86400)}d ago`, `${Math.round(s/86400)}天前`);
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
        showError(_t('Enter a valid competitor URL, e.g. lovable.dev or https://linear.app', '请输入有效的竞品网址，例如 lovable.dev 或 https://linear.app'));
        document.getElementById('url-input').focus();
        return;
    }
    const name = document.getElementById('name-input').value.trim() || null;
    _beginProgress(_t('🌐 Analyzing competitor website...', '🌐 正在分析竞品官网...'));

    // 附带 Auth token
    const token = window._analookAuth?.getToken();
    const authHeaders = token ? { 'Authorization': `Bearer ${token}` } : {};

    try {
        const resp = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders },
            body: JSON.stringify({ url: normalized, product_name: name, lang: window._ANALOOK_LANG || 'en' }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            // 积分不足 → 友好提示
            if (resp.status === 402) {
                _abortProgress('');
                showUpgradeModal();
                return;
            }
            // 未登录 → 弹出登录框
            if (resp.status === 401) {
                _abortProgress('');
                window._analookAuth?.showModal();
                return;
            }
            throw new Error(err.detail || _t(`Server error ${resp.status}`, `服务器错误 ${resp.status}`));
        }
        const data = await resp.json();
        currentJobId = data.job_id;
        saveToHistory(data.job_id, normalized, name || normalized);
        pollStatus();
    } catch (e) {
        _abortProgress(_t('Failed to start: ', '启动失败：') + e.message);
    }
}

async function startTextAnalysis() {
    clearError();
    const text = (document.getElementById('text-input')?.value || '').trim();
    const name = (document.getElementById('text-name-input')?.value || '').trim() || _t('Product', '产品');
    if (!text || text.length < 30) {
        showError(_t('Please enter a product description of at least 30 characters', '请输入至少 30 个字的产品描述'));
        return;
    }
    _beginProgress(_t('📝 Analyzing product description...', '📝 正在分析产品描述...'));
    try {
        const resp = await fetch('/api/analyze-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, product_name: name }),
        });
        if (!resp.ok) throw new Error(_t(`Server error ${resp.status}`, `服务器错误 ${resp.status}`));
        const data = await resp.json();
        currentJobId = data.job_id;
        saveToHistory(data.job_id, _t(`[text] ${name}`, `[描述] ${name}`), name);
        pollStatus();
    } catch (e) {
        _abortProgress(_t('Failed to start: ', '启动失败：') + e.message);
    }
}

async function startPdfAnalysis() {
    clearError();
    const fileInput = document.getElementById('pdf-input');
    const file = fileInput?.files?.[0];
    if (!file) { showError(_t('Please choose a PDF file', '请选择一个 PDF 文件')); return; }
    if (file.size > 20 * 1024 * 1024) { showError(_t('PDF must be under 20MB', 'PDF 文件不能超过 20MB')); return; }
    const name = (document.getElementById('pdf-name-input')?.value || '').trim() || file.name.replace('.pdf', '');
    _beginProgress(_t('📄 Parsing PDF content...', '📄 正在解析 PDF 内容...'));
    try {
        const form = new FormData();
        form.append('file', file);
        form.append('product_name', name);
        const resp = await fetch('/api/analyze-pdf', { method: 'POST', body: form });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || _t(`Server error ${resp.status}`, `服务器错误 ${resp.status}`));
        }
        const data = await resp.json();
        currentJobId = data.job_id;
        saveToHistory(data.job_id, `[PDF] ${name}`, name);
        pollStatus();
    } catch (e) {
        _abortProgress(_t('Failed to start: ', '启动失败：') + e.message);
    }
}

function _beginProgress(label) {
    const btn = document.getElementById('start-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="inline-block animate-spin mr-1">⏳</span> ' + _t('Analyzing...', '分析中...');

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
    btn.innerHTML = _t('🚀 Start Analysis', '🚀 开始调研');
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
    if (btn) { btn.disabled = true; btn.textContent = _t('Cancelling...', '取消中...'); }
    try {
        await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
    } catch {}
    // Reset UI
    const startBtn = document.getElementById('start-btn');
    if (startBtn) { startBtn.disabled = false; startBtn.innerHTML = _t('🚀 Start Analysis', '🚀 开始调研'); }
    stopTimer();
    document.getElementById('progress-section').classList.add('hidden');
    document.getElementById('input-section').classList.remove('hidden');
    document.getElementById('hero-section')?.classList.remove('hidden');
    if (btn) { btn.classList.add('hidden'); btn.disabled = false; btn.textContent = _t('⏹ Stop', '⏹ 停止分析'); }
    currentJobId = null;
    renderHistory();
}

// ── Timer ───────────────────────────────────────────────────────────────────
function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        const elapsed = Math.round((Date.now() - analysisStartTime) / 1000);
        const el = document.getElementById('prog-timer');
        if (el) el.textContent = _t(`Elapsed ${elapsed}s`, `已用时 ${elapsed} 秒`);
    }, 1000);
}

function stopTimer() {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
    const elapsed = Math.round((Date.now() - analysisStartTime) / 1000);
    const el = document.getElementById('prog-timer');
    if (el) el.textContent = _t(`✅ Done in ${elapsed}s`, `✅ 完成，共用时 ${elapsed} 秒`);
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
        // Progressive rendering: show completed sections while still running
        if (data.partial_results && data.status !== 'completed') {
            _renderPartialResults(data.partial_results);
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
            showError(_t('Something went wrong during analysis — refresh and retry', '分析过程中出错，请刷新重试'));
            const btn = document.getElementById('start-btn');
            if (btn) { btn.disabled = false; btn.innerHTML = _t('🚀 Start Analysis', '🚀 开始调研'); }
        } else {
            setTimeout(pollStatus, 1200);
        }
    } catch (e) {
        setTimeout(pollStatus, 2000);
    }
}

// ── Progressive rendering (show sections as they complete) ──────────────────
const _partialRendered = new Set();
function _renderPartialResults(partial) {
    // Show report section alongside progress
    const reportSec = document.getElementById('report-section');
    if (reportSec && reportSec.classList.contains('hidden')) {
        reportSec.classList.remove('hidden');
    }

    // Render each completed module that hasn't been rendered yet
    // Use the report.py format functions via a lightweight shim
    const moduleMap = {
        'website':     { section: 'website_analysis', render: typeof renderWebsite !== 'undefined' ? renderWebsite : null,
                         format: (d) => ({ title: _t("Website Evolution", "官网演变分析"), domain: d.domain, first_seen: d.first_seen, total_snapshots: d.total_snapshots, deep_timeline: d.deep_timeline || [], current: d.current_site || {}, key_changes: d.key_changes || [] }) },
        'social':      { section: 'social_media', render: typeof renderSocial !== 'undefined' ? renderSocial : null,
                         format: (d) => ({ title: _t("Social Media", "社交媒体"), brand: d.brand, channels: d.channels || {}, propagation_metrics: d.propagation_metrics || {} }) },
        'traffic':     { section: 'traffic_analysis', render: typeof renderTraffic !== 'undefined' ? renderTraffic : null, format: (d) => d },
        'producthunt': { section: 'producthunt', render: typeof renderProductHunt !== 'undefined' ? renderProductHunt : null, format: (d) => d },
        'pricing':     { section: 'pricing', render: typeof renderPricing !== 'undefined' ? renderPricing : null, format: (d) => d },
    };

    for (const [key, data] of Object.entries(partial)) {
        if (_partialRendered.has(key)) continue;
        const info = moduleMap[key];
        if (!info || !info.render) continue;
        try {
            const formatted = info.format ? info.format(data) : data;
            info.render(formatted);
            _partialRendered.add(key);
        } catch (e) {
            // Skip render errors for partial data
        }
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
        if (typeof renderResearchMap === 'function') renderResearchMap(report);

        // Render all sections
        if (typeof renderThesis === 'function') renderThesis(report.sections.thesis || {}, report.sections.growth_score || {}, meta.lang);
        if (typeof renderReferences === 'function') renderReferences(report.sections.references || [], meta.lang);
        if (typeof renderStrategyRadar === 'function') renderStrategyRadar(report.sections.strategy_radar || {});
        renderWebsite(report.sections.website_analysis || {}, report.sections.evolution_summary || '', meta.lang);
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

        _maybeShowLastCreditBanner();
        _renderPostReportCTA();

        document.getElementById('hero-section')?.classList.add('hidden');

        const btn = document.getElementById('start-btn');
        if (btn) { btn.disabled = false; btn.innerHTML = _t('🚀 Start Analysis', '🚀 开始调研'); }
    } catch (e) {
        showError(_t('Failed to load report: ', '加载报告失败：') + e.message);
        const btn = document.getElementById('start-btn');
        if (btn) { btn.disabled = false; btn.innerHTML = _t('🚀 Start Analysis', '🚀 开始调研'); }
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
    const phStr = phScore ? `⬆${fmtNum(phScore)}` : _t('Not launched', '未上线');

    el.innerHTML = `
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
        <div class="text-xs text-gray-500 uppercase tracking-wider mb-3">${_t("Core Metrics", "核心指标")}</div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">${_t("Organic search estimate", "有机搜索流量估算")}</div>
                <div class="text-xl font-bold text-white">${trafficStr}</div>
                <div class="text-xs text-gray-600 mt-0.5">via keyword rankings</div>
            </div>
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">${_t("Twitter followers", "Twitter 粉丝")}</div>
                <div class="text-xl font-bold text-white">${twStr}</div>
            </div>
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">Product Hunt</div>
                <div class="text-xl font-bold text-white">${phStr}</div>
            </div>
            <div class="bg-gray-800/60 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-1">${_t("First seen", "首次出现")}</div>
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
            showError(data.error || _t('Export failed — report not ready yet', '导出失败，报告尚未生成'));
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
        showError(_t('Export failed: ', '导出失败：') + e.message);
    }
}

async function shareReport() {
    if (!currentJobId) return;
    const btn = document.getElementById('share-btn');
    try {
        const resp = await fetch(`/api/share/${currentJobId}`);
        const data = await resp.json();
        if (data.error) { showError(_t('Share failed: ', '分享失败: ') + data.error); return; }
        const fullUrl = `${window.location.origin}${data.share_url}`;
        if (navigator.clipboard) {
            await navigator.clipboard.writeText(fullUrl);
        } else {
            prompt(_t('Copy share link:', '复制分享链接：'), fullUrl);
        }
        const orig = btn.innerHTML;
        btn.innerHTML = _t('✅ Copied', '✅ 已复制');
        btn.classList.add('bg-green-900', 'border-green-700');
        setTimeout(() => { btn.innerHTML = orig; btn.classList.remove('bg-green-900', 'border-green-700'); }, 3000);
    } catch (e) {
        showError(_t('Share failed: ', '分享失败：') + e.message);
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
    // 暴露给 auth.js 调用：首次同步交给 auth.js 的 onAuthStateChange 触发
    window.syncServerHistory = syncServerHistory;

    const pathMatch = window.location.pathname.match(/^(?:\/zh)?\/report\/([a-f0-9]+)/);
    if (pathMatch) {
        const jobId = pathMatch[1];
        loadSharedReport(jobId).catch(() => {
            // Friendly 404 — common cause is a report from before the
            // Supabase persistence fix (job_ids in old localStorage history
            // point to reports that never made it to the server).
            document.querySelector('main').innerHTML = `
                <div class="max-w-2xl mx-auto py-12 px-6 text-center">
                    <div class="text-5xl mb-4">📭</div>
                    <h2 class="text-xl font-semibold text-white mb-3">This report can't be loaded</h2>
                    <p class="text-gray-400 leading-relaxed mb-6">
                        Job <code class="bg-gray-800 px-2 py-0.5 rounded text-blue-300">${esc(jobId)}</code>
                        wasn't found on the server. It may have expired,
                        or it was generated during a backend issue
                        (April 2026 Supabase mis-config — reports from that
                        window weren't persisted).
                    </p>
                    <a href="/" class="inline-block bg-blue-600 hover:bg-blue-500 text-white font-medium px-5 py-2.5 rounded-lg">
                        ← Run a fresh analysis
                    </a>
                </div>`;
        });
    }
});

// ── Upgrade modal ────────────────────────────────────────────────────────────────────────────
function showUpgradeModal() {
    const modal = document.getElementById('upgrade-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
}

function hideUpgradeModal() {
    const modal = document.getElementById('upgrade-modal');
    if (modal) modal.classList.add('hidden');
}

// Wire up upgrade modal buttons
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('upgrade-close-btn')?.addEventListener('click', hideUpgradeModal);
    document.getElementById('upgrade-modal')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) hideUpgradeModal();
    });

    async function _doCheckout(plan) {
        const headers = {'Content-Type': 'application/json'};
        const token = window._analookAuth?.getToken?.();
        if (token) headers['Authorization'] = 'Bearer ' + token;
        try {
            hideUpgradeModal();
            const resp = await fetch('/api/checkout', {
                method: 'POST', headers,
                body: JSON.stringify({
                    plan,
                    success_url: window.location.origin + '/?payment=success&plan=' + plan,
                    cancel_url: window.location.origin + '/?payment=canceled',
                }),
            });
            const data = await resp.json();
            if (data.url) window.location.href = data.url;
            else alert('Error: ' + (data.error || 'Unknown'));
        } catch(e) { alert('Network error: ' + e.message); }
    }

    document.getElementById('upgrade-single-btn')?.addEventListener('click', () => _doCheckout('single_report'));
    document.getElementById('upgrade-pro-btn')?.addEventListener('click', () => _doCheckout('pro'));
});

// ── Last-credit banner ────────────────────────────────────────────────────────────────────
async function _maybeShowLastCreditBanner() {
    const token = window._analookAuth?.getToken?.();
    if (!token) return;
    try {
        const res = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token }});
        if (!res.ok) return;
        const profile = await res.json();
        if (profile.credits_balance === 1 && profile.plan_type === 'free') {
            _showLastCreditBanner();
        }
    } catch(e) {}
}

async function _renderPostReportCTA() {
    const container = document.getElementById('post-report-cta-buttons');
    if (!container) return;

    const token = window._analookAuth?.getToken?.();
    let credits = null;
    let planType = 'free';

    if (token) {
        try {
            const res = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token }});
            if (res.ok) {
                const p = await res.json();
                credits = p.credits_balance;
                planType = p.plan_type;
            }
        } catch(e) {}
    }

    // Has credits left (or Pro) → show "Analyze another" button
    if (credits === null || credits > 0 || planType !== 'free') {
        container.innerHTML = `
            <button onclick="newAnalysis()" class="inline-flex items-center gap-2 bg-[color:var(--ink)] hover:bg-white text-[color:var(--bg)] font-medium text-sm px-6 py-3 rounded-full transition-colors">
                Analyze another competitor &rarr;
            </button>`;
    } else {
        // No credits → show upgrade options
        container.innerHTML = `
            <button onclick="_doCheckout('single')" class="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm px-6 py-3 rounded-full transition-colors">
                Get 1 more report &mdash; $5
            </button>
            <button onclick="showUpgradeModal()" class="inline-flex items-center gap-2 bg-[color:var(--cream-elev)] hover:bg-[color:var(--elev)] border border-[color:var(--warm-border)] text-[color:var(--ink)] font-medium text-sm px-6 py-3 rounded-full transition-colors">
                Pro &mdash; $19/mo &middot; 30 reports
            </button>`;
    }
}

function _showLastCreditBanner() {
    const existing = document.getElementById('last-credit-banner');
    if (existing) return;
    const banner = document.createElement('div');
    banner.id = 'last-credit-banner';
    banner.className = 'fixed bottom-0 left-0 right-0 bg-amber-900/95 border-t border-amber-700 px-4 py-3 z-40 flex items-center justify-between gap-3';
    banner.innerHTML = `
        <span class="text-amber-100 text-sm">⚡ <strong>1 free report left</strong> this month — make it count, or upgrade for unlimited access.</span>
        <div class="flex gap-2 flex-shrink-0">
            <button onclick="document.getElementById('last-credit-banner').remove()" class="text-amber-400 hover:text-amber-200 text-xs px-2 py-1">Dismiss</button>
            <button onclick="showUpgradeModal()" class="bg-amber-500 hover:bg-amber-400 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">Upgrade →</button>
        </div>
    `;
    document.body.appendChild(banner);
}
