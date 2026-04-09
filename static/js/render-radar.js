/**
 * Strategy Radar Map — 6-dimension SVG radar chart
 */
function renderStrategyRadar(radar) {
    const container = document.getElementById('section-radar');
    if (!radar || !radar.dimensions || !radar.dimensions.length) {
        container.innerHTML = '';
        return;
    }

    const dims = radar.dimensions;
    const n = dims.length;
    const avg = radar.avg_score || 0;

    // SVG parameters — wider viewBox to prevent label clipping
    const cx = 200, cy = 180, maxR = 110;
    const angleStep = (2 * Math.PI) / n;
    const startAngle = -Math.PI / 2;

    function polar(angle, r) {
        return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
    }

    // Grid rings
    let gridLines = '';
    for (const ring of [20, 40, 60, 80, 100]) {
        const r = (ring / 100) * maxR;
        const pts = [];
        for (let i = 0; i < n; i++) {
            pts.push(polar(startAngle + i * angleStep, r).join(','));
        }
        gridLines += `<polygon points="${pts.join(' ')}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>`;
    }

    // Axis lines
    let axisLines = '';
    for (let i = 0; i < n; i++) {
        const [x, y] = polar(startAngle + i * angleStep, maxR);
        axisLines += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>`;
    }

    // Data polygon
    const dataPoints = [];
    for (let i = 0; i < n; i++) {
        const r = (dims[i].score / 100) * maxR;
        dataPoints.push(polar(startAngle + i * angleStep, r).join(','));
    }
    const dataPolygon = `<polygon points="${dataPoints.join(' ')}" fill="rgba(59,130,246,0.15)" stroke="rgba(59,130,246,0.7)" stroke-width="2"/>`;

    // Data dots
    let dots = '';
    for (let i = 0; i < n; i++) {
        const r = (dims[i].score / 100) * maxR;
        const [x, y] = polar(startAngle + i * angleStep, r);
        dots += `<circle cx="${x}" cy="${y}" r="4" fill="#3b82f6" stroke="#1e3a5f" stroke-width="1.5"/>`;
    }

    // Axis labels — positioned further out, with score on same line
    let labels = '';
    for (let i = 0; i < n; i++) {
        const labelR = maxR + 32;
        const [x, y] = polar(startAngle + i * angleStep, labelR);
        const d = dims[i];
        const anchor = x < cx - 10 ? 'end' : x > cx + 10 ? 'start' : 'middle';
        const scoreColor = d.score >= 60 ? '#86efac' : d.score >= 30 ? '#fde68a' : '#fca5a5';
        // Label + score on two lines
        labels += `<text x="${x}" y="${y - 7}" text-anchor="${anchor}" dominant-baseline="central" fill="#9ca3af" font-size="11">${d.label}</text>`;
        labels += `<text x="${x}" y="${y + 9}" text-anchor="${anchor}" dominant-baseline="central" fill="${scoreColor}" font-size="13" font-weight="bold">${d.score}</text>`;
    }

    // Center score
    const centerScore = `
        <text x="${cx}" y="${cy - 8}" text-anchor="middle" fill="#e5e7eb" font-size="28" font-weight="bold">${avg}</text>
        <text x="${cx}" y="${cy + 14}" text-anchor="middle" fill="#6b7280" font-size="10">综合评分</text>
    `;

    const svg = `<svg viewBox="0 0 400 360" style="width:100%; max-width:400px; height:auto;">
        ${gridLines}${axisLines}${dataPolygon}${dots}${labels}${centerScore}
    </svg>`;

    // Build the card
    let html = `<div class="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">🎯 策略雷达图</h3>
            <span class="text-[10px] bg-blue-900/40 text-blue-300 border border-blue-700/40 px-2.5 py-1 rounded-full font-medium">Strategy Radar</span>
        </div>
        <div class="flex flex-col md:flex-row items-center gap-6">
            <div class="flex-shrink-0 w-full md:w-auto flex justify-center">${svg}</div>
            <div class="flex-1 space-y-2.5 w-full">`;

    // Dimension bars
    for (const d of dims) {
        const barColor = d.score >= 60 ? 'bg-green-500' : d.score >= 30 ? 'bg-yellow-500' : 'bg-red-500';
        const textColor = d.score >= 60 ? 'text-green-400' : d.score >= 30 ? 'text-yellow-400' : 'text-red-400';
        html += `<div>
            <div class="flex items-center justify-between mb-0.5">
                <span class="text-xs text-gray-400">${d.emoji} ${esc(d.label)}</span>
                <span class="text-xs font-mono ${textColor} font-bold">${d.score}</span>
            </div>
            <div class="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                <div class="${barColor} h-full rounded-full transition-all" style="width:${d.score}%"></div>
            </div>
        </div>`;
    }

    html += `</div></div></div>`;
    container.innerHTML = html;
}
