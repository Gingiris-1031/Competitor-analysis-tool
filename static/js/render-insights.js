function renderInsights(ai) {
    const container = document.getElementById('section-insights');
    if (!ai || (typeof ai === 'object' && Object.keys(ai).length === 0)) { container.innerHTML = ''; return; }

    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">🧠 AI Business Insights</h3>
            <span class="text-[10px] bg-indigo-900/40 text-indigo-300 border border-indigo-700/40 px-2.5 py-1 rounded-full font-medium">🔮 Wayback + PH + Playbook Cross Analysis</span>
        </div>`;

    // AI Strategic Verdict card (if available)
    const verdict = ai.verdict;
    if (verdict && verdict.killer_move) {
        const repColor = verdict.replicability === 'High' ? 'text-green-400 bg-green-900/30 border-green-700/40'
            : verdict.replicability === 'Low' ? 'text-red-400 bg-red-900/30 border-red-700/40'
            : 'text-yellow-400 bg-yellow-900/30 border-yellow-700/40';
        const patternEmoji = {'开源社区驱动':'💻','PLG 产品驱动':'🎯','内容 SEO 驱动':'📝','社交病毒传播':'📢','模板飞轮驱动':'🔄','企业销售驱动':'🏢','OSS Community':'💻','PLG':'🎯','Content SEO':'📝','Social Viral':'📢','Template Flywheel':'🔄','Enterprise Sales':'🏢'}[verdict.growth_pattern] || '📊';
        html += `<div class="bg-gradient-to-r from-blue-900/20 to-purple-900/20 border border-blue-700/30 rounded-xl p-5 mb-6">
            <div class="flex items-start gap-4">
                <div class="text-3xl flex-shrink-0">${patternEmoji}</div>
                <div class="flex-1">
                    <div class="text-xs text-gray-500 mb-1">AI Strategic Verdict</div>
                    <div class="text-base font-bold text-white mb-2">${esc(verdict.one_line_verdict)}</div>
                    <div class="flex flex-wrap items-center gap-3 text-xs">
                        <span class="text-blue-300">🎯 Killer Move:${esc(verdict.killer_move)}</span>
                        <span class="text-purple-300">${patternEmoji} ${esc(verdict.growth_pattern)}</span>
                        <span class="${repColor} px-2 py-0.5 rounded-full border text-[10px]">Replicability:${esc(verdict.replicability)}</span>
                    </div>
                </div>
            </div>
        </div>`;
    }

    if (ai.success && ai.content) {
        html += `<div class="ai-content">${formatMarkdown(ai.content)}</div>`;
        html += `<div class="text-[10px] text-gray-600 mt-4">Analysis Source: ${esc(ai.source || 'AI')}</div>`;
    } else if (ai.source === 'error') {
        html += `<div class="bg-red-900/10 border border-red-800/30 rounded-lg p-4">
            <div class="text-sm text-red-300 mb-2">⚠️ ${esc(ai.note || 'AI analysis error')}</div>
            <div class="text-xs text-gray-500">Other report sections generated normally. You can ignore this error.</div>
        </div>`;
    } else {
        html += `<div class="bg-yellow-900/10 border border-yellow-800/30 rounded-lg p-4">
            <div class="text-sm text-yellow-300 mb-2">${esc(ai.note || 'LLM API configuration needed')}</div>
        </div>`;
    }

    // QA Module — only show input after AI analysis is done
    html += `<div class="mt-6 border-t border-gray-800 pt-5">
        <h4 class="text-sm font-semibold text-gray-300 mb-3">💬 Follow-up Q&A</h4>`;

    if (!ai.success) {
        html += `<div class="bg-gray-800 rounded-lg p-4 text-center">
            <div class="text-sm text-gray-400">⏳ Follow-up questions available after AI analysis completes</div>
        </div>`;
    } else {
        html += `<div id="qa-history" class="space-y-3 mb-4 max-h-[600px] overflow-y-auto"></div>
        <div class="flex gap-2">
            <input type="text" id="qa-input" placeholder="Ask a question (supports web search), e.g.: Review their 2024 growth strategy"
                class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500">
            <button onclick="askQuestion()" id="qa-btn"
                class="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors shrink-0">
                Send
            </button>
        </div>
        <div class="flex items-center gap-1 mt-1.5 mb-2">
            <span class="text-[10px] text-gray-500">🌐 Questions about specific events/cases/history will automatically trigger web search</span>
        </div>
        <div class="flex flex-wrap gap-2">
            ${['What key decisions did they get right?','How exactly did their SEO strategy work?','Core advice for competitors/newcomers?','Where are their growth bottlenecks?','How has their product positioning evolved?','Review their launch strategy'].map(q =>
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
    let listType = null; // 'bullet' | 'number' | 'sub'

    function closeList() {
        if (inList) { html += '</div>'; inList = false; listType = null; }
    }

    for (const line of lines) {
        const trimmed = line.trim();
        const indented = line.startsWith('  ') || line.startsWith('\t');

        if (!trimmed) {
            closeList();
            continue;
        }

        // H2 (##) — major section
        if (trimmed.startsWith('## ') && !trimmed.startsWith('### ')) {
            closeList();
            const title = trimmed.slice(3);
            html += `<h3 class="text-base font-bold text-white mt-6 mb-2 pb-1.5 border-b border-gray-800">${formatInline(title)}</h3>`;

        // H3 (###) — sub-section
        } else if (trimmed.startsWith('### ')) {
            closeList();
            const title = trimmed.slice(4);
            html += `<h4 class="text-sm font-semibold text-blue-300 mt-5 mb-1.5">${formatInline(title)}</h4>`;

        // H4 (####) — sub-sub-section
        } else if (trimmed.startsWith('#### ')) {
            closeList();
            const title = trimmed.slice(5);
            html += `<h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-4 mb-1">${esc(title)}</h5>`;

        // Indented bullet (sub-item)
        } else if (indented && (trimmed.startsWith('· ') || trimmed.startsWith('- ') || trimmed.startsWith('* '))) {
            if (!inList || listType !== 'sub') {
                if (inList && listType !== 'sub') { closeList(); }
                if (!inList) { html += '<div class="space-y-1 ml-4">'; inList = true; listType = 'sub'; }
            }
            const content = trimmed.replace(/^[·\-\*]\s+/, '');
            html += `<div class="text-xs text-gray-400 leading-relaxed pl-3 border-l border-gray-700">${formatInline(content)}</div>`;

        // Top-level bullet
        } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || trimmed.startsWith('· ')) {
            if (!inList || listType !== 'bullet') { closeList(); html += '<div class="space-y-2">'; inList = true; listType = 'bullet'; }
            const content = trimmed.replace(/^[·\-\*]\s+/, '');
            html += `<div class="text-sm text-gray-300 leading-relaxed pl-3 border-l-2 border-gray-700">${formatInline(content)}</div>`;

        // Numbered list
        } else if (/^\d+\.\s/.test(trimmed)) {
            if (!inList || listType !== 'number') { closeList(); html += '<div class="space-y-2">'; inList = true; listType = 'number'; }
            const num = trimmed.match(/^(\d+)\./)[1];
            const content = trimmed.replace(/^\d+\.\s+/, '');
            html += `<div class="text-sm text-gray-300 leading-relaxed flex gap-2"><span class="text-blue-400 font-mono shrink-0">${num}.</span><span>${formatInline(content)}</span></div>`;

        // Bold label paragraph: **Label**：content or **Label**: content
        } else if (/^\*\*[^*]+\*\*[：:]/.test(trimmed)) {
            closeList();
            const match = trimmed.match(/^\*\*([^*]+)\*\*[：:]\s*(.*)/s);
            if (match) {
                const label = match[1];
                const content = match[2];
                html += `<div class="text-sm leading-relaxed mt-2"><span class="font-semibold text-white">${esc(label)}：</span><span class="text-gray-300">${formatInline(content)}</span></div>`;
            } else {
                html += `<div class="text-sm text-gray-300 leading-relaxed">${formatInline(trimmed)}</div>`;
            }

        // Horizontal rule
        } else if (/^---+$/.test(trimmed)) {
            closeList();
            html += `<hr class="border-gray-800 my-4">`;

        // Regular paragraph
        } else {
            closeList();
            html += `<div class="text-sm text-gray-300 leading-relaxed">${formatInline(trimmed)}</div>`;
        }
    }
    closeList();
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
        if (!currentJobId) alert('Please complete the competitive analysis first');
        return;
    }

    const btn = document.getElementById('qa-btn');
    btn.disabled = true; btn.textContent = '⏳';
    input.value = '';

    // Add question to history
    const history = document.getElementById('qa-history');
    history.innerHTML += `<div class="bg-gray-800 rounded-lg p-3">
        <div class="text-xs text-blue-400 mb-1">Your question:</div>
        <div class="text-sm text-white">${esc(question)}</div>
    </div>
    <div id="qa-loading" class="text-xs text-gray-500 pl-2">Thinking...</div>`;

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
                sourcesHtml = `<div class="mt-2 pt-2 border-t border-gray-700"><div class="text-[10px] text-gray-500 mb-1">🌐 Web search sources:</div><div class="flex flex-wrap gap-1">` +
                    data.sources.map(s => `<a href="${esc(s.url)}" target="_blank" class="text-[10px] text-blue-400 hover:underline bg-gray-800 px-1.5 py-0.5 rounded">${esc(s.title.substring(0,40))} ↗</a>`).join('') +
                    `</div></div>`;
            }
            const searchBadge = data.web_searched ? '<span class="text-[10px] bg-blue-900/50 text-blue-300 px-1.5 py-0.5 rounded ml-2">🌐 Web searched</span>' : '';
            history.innerHTML += `<div class="bg-gray-800/50 rounded-lg p-3 border-l-2 border-blue-500">
                <div class="text-xs text-green-400 mb-1">AI Answer${searchBadge}</div>
                <div class="ai-content">${formatMarkdown(data.answer)}</div>
                ${sourcesHtml}
            </div>`;
        } else {
            history.innerHTML += `<div class="text-xs text-red-400 pl-2">Failed to answer, please retry</div>`;
        }
    } catch(e) {
        document.getElementById('qa-loading')?.remove();
        history.innerHTML += `<div class="text-xs text-red-400 pl-2">Request failed:${e.message}</div>`;
    }

    btn.disabled = false; btn.textContent = 'Send';
    history.scrollTop = history.scrollHeight;
}

function askQuickQuestion(q) {
    document.getElementById('qa-input').value = q;
    askQuestion();
}
