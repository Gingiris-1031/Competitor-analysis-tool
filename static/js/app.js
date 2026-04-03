let currentJobId = null;
let analysisStartTime = null;
let timerInterval = null;

async function startAnalysis() {
    const url = document.getElementById('url-input').value.trim();
    if (!url) { alert('请输入竞品网址'); return; }
    const name = document.getElementById('name-input').value.trim() || null;
    const btn = document.getElementById('start-btn');
    btn.disabled = true; btn.textContent = '⏳ 分析中...'; btn.classList.add('opacity-50');
    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('report-section').classList.add('hidden');
    analysisStartTime = Date.now();
    startTimer();
    try {
        const resp = await fetch('/api/analyze', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({url, product_name: name}),
        });
        const data = await resp.json();
        currentJobId = data.job_id;
        pollStatus();
    } catch(e) {
        alert('启动失败: '+e.message);
        btn.disabled=false; btn.textContent='🚀 开始调研'; btn.classList.remove('opacity-50');
        stopTimer();
    }
}

function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        const elapsed = Math.round((Date.now() - analysisStartTime) / 1000);
        const el = document.getElementById('prog-timer');
        if (el) el.textContent = `已用时 ${elapsed} 秒 · 预计 40-50 秒完成`;
    }, 1000);
}

function stopTimer() {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
    const elapsed = Math.round((Date.now() - analysisStartTime) / 1000);
    const el = document.getElementById('prog-timer');
    if (el) el.textContent = `✅ 分析完成，共用时 ${elapsed} 秒`;
}

async function pollStatus() {
    if (!currentJobId) return;
    try {
        const resp = await fetch(`/api/status/${currentJobId}`);
        const data = await resp.json();
        const statusMap = {pending: [0,'⏳'], running: [50,'🔄'], done: [100,'✅'], error: [100,'❌']};
        for (const [key, status] of Object.entries(data.progress||{})) {
            const el = document.getElementById(`prog-${key}`);
            if (!el) continue;
            const icon = el.querySelector('.status-icon');
            const bar = el.querySelector('.prog-bar > div');
            const [pct, emoji] = statusMap[status] || [0,'⏳'];
            icon.textContent = emoji;
            if (bar) {
                // Animate: running = slowly fill, done = full
                if (status === 'running') {
                    const elapsed = (Date.now() - analysisStartTime) / 1000;
                    const estimated = key === 'report' ? 25 : 20;
                    const progress = Math.min(90, (elapsed / estimated) * 80 + 10);
                    bar.style.width = progress + '%';
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
        if (data.status==='completed') { stopTimer(); await loadReport(); }
        else { setTimeout(pollStatus, 1200); }
    } catch(e) { setTimeout(pollStatus, 2000); }
}

async function loadReport() {
    const resp = await fetch(`/api/report/${currentJobId}`);
    const report = await resp.json();
    document.getElementById('report-section').classList.remove('hidden');
    renderWebsite(report.sections.website_analysis);
    renderProductHunt(report.sections.producthunt || {});
    renderSocial(report.sections.social_media);
    renderPropagation(report.sections.propagation || {});
    renderTraffic(report.sections.traffic_analysis);
    renderPeaks(report.sections.traffic_peaks || {});
    renderGrowth(report.sections.growth_analysis || {});
    renderInsights(report.sections.ai_insights || {});
    renderSummary(report.sections.summary);
    renderStrategy(report.sections.growth_strategy || {});
}

function esc(s) { if(!s) return ''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

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
        if (data.error) { alert('分享失败: ' + data.error); return; }

        // Build full URL with UTM
        const fullUrl = `${window.location.origin}${data.share_url}`;

        // Try clipboard API first
        if (navigator.clipboard) {
            await navigator.clipboard.writeText(fullUrl);
            btn.textContent = '✅ 链接已复制';
            btn.classList.add('bg-green-900');
        } else {
            // Fallback: show prompt
            prompt('复制分享链接:', fullUrl);
            btn.textContent = '✅ 链接已生成';
        }
        setTimeout(() => { btn.textContent = '🔗 分享报告'; btn.classList.remove('bg-green-900'); }, 3000);
    } catch(e) {
        alert('分享失败: ' + e.message);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('url-input').addEventListener('keypress', e => { if(e.key==='Enter') startAnalysis(); });

    // Auto-load shared report if URL matches /report/{job_id}
    const pathMatch = window.location.pathname.match(/^\/report\/([a-f0-9]+)/);
    if (pathMatch) {
        const sharedJobId = pathMatch[1];
        currentJobId = sharedJobId;
        // Rebuild the page to show report sections
        document.querySelector('main').innerHTML = `
            <div class="text-center py-4 text-gray-400 text-sm mb-4">🔍 竞品调研报告 — Powered by Gingiris</div>
            <div id="report-section">
                <div class="flex items-center justify-between mb-6">
                    <h2 class="text-xl font-bold">📊 调研报告</h2>
                    <div class="flex gap-2">
                        <button onclick="exportMarkdown()" class="bg-gray-800 hover:bg-gray-700 text-sm px-4 py-2 rounded-lg border border-gray-700">📄 导出 Markdown</button>
                    </div>
                </div>
                <div class="space-y-6">
                    <div id="section-website" class="fade-in"></div>
                    <div id="section-producthunt" class="fade-in"></div>
                    <div id="section-social" class="fade-in"></div>
                    <div id="section-propagation" class="fade-in"></div>
                    <div id="section-traffic" class="fade-in"></div>
                    <div id="section-peaks" class="fade-in"></div>
                    <div id="section-growth" class="fade-in"></div>
                    <div id="section-insights" class="fade-in"></div>
                    <div id="section-strategy" class="fade-in"></div>
                </div>
            </div>`;
        loadReport().catch(() => {
            document.querySelector('main').innerHTML = '<div class="text-center py-8 text-red-400">报告不存在或已过期</div>';
        });
    }
});
