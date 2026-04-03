function renderInsights(ai) {
    const container = document.getElementById('section-insights');
    if (!ai || (typeof ai === 'object' && Object.keys(ai).length === 0)) { container.innerHTML = ''; return; }

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h3 class="text-lg font-semibold mb-4">🧠 AI 商业洞察</h3>`;

    if (ai.success && ai.content) {
        html += `<div class="ai-content">${formatMarkdown(ai.content)}</div>`;
        html += `<div class="text-[10px] text-gray-600 mt-4">分析来源: ${esc(ai.source || 'AI')}</div>`;
    } else if (ai.source === 'error') {
        html += `<div class="bg-red-900/10 border border-red-800/30 rounded-lg p-4">
            <div class="text-sm text-red-300 mb-2">⚠️ ${esc(ai.note || 'AI 分析出现异常')}</div>
            <div class="text-xs text-gray-500">报告其他部分正常生成，可忽略此错误。</div>
        </div>`;
    } else {
        html += `<div class="bg-yellow-900/10 border border-yellow-800/30 rounded-lg p-4">
            <div class="text-sm text-yellow-300 mb-2">${esc(ai.note || '需要配置 LLM API')}</div>
        </div>`;
    }

    // QA Module — only show input after AI analysis is done
    html += `<div class="mt-6 border-t border-gray-800 pt-5">
        <h4 class="text-sm font-semibold text-gray-300 mb-3">💬 追问分析</h4>`;

    if (!ai.success) {
        html += `<div class="bg-gray-800 rounded-lg p-4 text-center">
            <div class="text-sm text-gray-400">⏳ AI 分析完成后即可追问</div>
        </div>`;
    } else {
        html += `<div id="qa-history" class="space-y-3 mb-4 max-h-[600px] overflow-y-auto"></div>
        <div class="flex gap-2">
            <input type="text" id="qa-input" placeholder="输入你的问题（支持联网搜索），例如：复盘一下他们 2024 的增长策略"
                class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500">
            <button onclick="askQuestion()" id="qa-btn"
                class="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors shrink-0">
                发送
            </button>
        </div>
        <div class="flex items-center gap-1 mt-1.5 mb-2">
            <span class="text-[10px] text-gray-500">🌐 涉及具体事件/案例/历史的问题会自动联网搜索</span>
        </div>
        <div class="flex flex-wrap gap-2">
            ${['他们做对了什么关键决策？','SEO 策略具体怎么做的？','给竞品/后来者的核心建议？','他们的增长瓶颈在哪？','产品定位经历了哪些变化？','复盘一下他们的 launch 策略'].map(q =>
                `<button onclick="askQuickQuestion('${q}')" class="text-[10px] text-gray-400 bg-gray-800 hover:bg-gray-700 px-2 py-1 rounded border border-gray-700 transition-colors">${q}</button>`
            ).join('')}
        </div>`;
    }
    html += `</div>`;

    html += `</div>`;
    container.innerHTML = html;

    // Bind enter key
    setTimeout(() => {
        const input = document.getElementById('qa-input');
        if (input) input.addEventListener('keypress', e => { if(e.key==='Enter') askQuestion(); });
    }, 100);
}

function formatMarkdown(text) {
    let html = '';
    const lines = text.split('\n');
    let inList = false;

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
            if (inList) { html += '</div>'; inList = false; }
            continue;
        }
        if (trimmed.startsWith('### ')) {
            if (inList) { html += '</div>'; inList = false; }
            html += `<h4 class="text-sm font-semibold text-blue-300 mt-5 mb-2">${esc(trimmed.slice(4))}</h4>`;
        } else if (trimmed.startsWith('## ')) {
            if (inList) { html += '</div>'; inList = false; }
            html += `<h4 class="text-base font-semibold text-white mt-5 mb-2">${esc(trimmed.slice(3))}</h4>`;
        } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || /^\d+\.\s/.test(trimmed)) {
            if (!inList) { html += '<div class="space-y-1.5">'; inList = true; }
            const content = trimmed.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, '');
            html += `<div class="text-sm text-gray-300 leading-relaxed pl-3 border-l-2 border-gray-700">${formatInline(content)}</div>`;
        } else {
            if (inList) { html += '</div>'; inList = false; }
            html += `<div class="text-sm text-gray-300 leading-relaxed">${formatInline(trimmed)}</div>`;
        }
    }
    if (inList) html += '</div>';
    return html;
}

function formatInline(text) {
    // Bold
    let result = text.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>');
    // Links: [text](url)
    result = result.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" class="text-blue-400 hover:underline">$1 ↗</a>');
    // Auto-link URLs
    result = result.replace(/(^|[^"'])(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" class="text-blue-400 hover:underline">$2 ↗</a>');
    // Inline code
    result = result.replace(/`([^`]+)`/g, '<code class="bg-gray-800 px-1 rounded text-xs">$1</code>');
    return result;
}

async function askQuestion() {
    const input = document.getElementById('qa-input');
    const question = input.value.trim();
    if (!question || !currentJobId) {
        if (!currentJobId) alert('请先完成竞品分析');
        return;
    }

    const btn = document.getElementById('qa-btn');
    btn.disabled = true; btn.textContent = '⏳';
    input.value = '';

    // Add question to history
    const history = document.getElementById('qa-history');
    history.innerHTML += `<div class="bg-gray-800 rounded-lg p-3">
        <div class="text-xs text-blue-400 mb-1">你的问题:</div>
        <div class="text-sm text-white">${esc(question)}</div>
    </div>
    <div id="qa-loading" class="text-xs text-gray-500 pl-2">思考中...</div>`;

    try {
        const resp = await fetch('/api/qa', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({job_id: currentJobId, question}),
        });
        const data = await resp.json();
        document.getElementById('qa-loading')?.remove();

        if (data.answer) {
            let sourcesHtml = '';
            if (data.web_searched && data.sources && data.sources.length) {
                sourcesHtml = `<div class="mt-2 pt-2 border-t border-gray-700"><div class="text-[10px] text-gray-500 mb-1">🌐 联网搜索来源:</div><div class="flex flex-wrap gap-1">` +
                    data.sources.map(s => `<a href="${esc(s.url)}" target="_blank" class="text-[10px] text-blue-400 hover:underline bg-gray-800 px-1.5 py-0.5 rounded">${esc(s.title.substring(0,40))} ↗</a>`).join('') +
                    `</div></div>`;
            }
            const searchBadge = data.web_searched ? '<span class="text-[10px] bg-blue-900/50 text-blue-300 px-1.5 py-0.5 rounded ml-2">🌐 已联网搜索</span>' : '';
            history.innerHTML += `<div class="bg-gray-800/50 rounded-lg p-3 border-l-2 border-blue-500">
                <div class="text-xs text-green-400 mb-1">AI 回答${searchBadge}</div>
                <div class="ai-content">${formatMarkdown(data.answer)}</div>
                ${sourcesHtml}
            </div>`;
        } else {
            history.innerHTML += `<div class="text-xs text-red-400 pl-2">回答失败，请重试</div>`;
        }
    } catch(e) {
        document.getElementById('qa-loading')?.remove();
        history.innerHTML += `<div class="text-xs text-red-400 pl-2">请求失败: ${e.message}</div>`;
    }

    btn.disabled = false; btn.textContent = '发送';
    history.scrollTop = history.scrollHeight;
}

function askQuickQuestion(q) {
    document.getElementById('qa-input').value = q;
    askQuestion();
}
