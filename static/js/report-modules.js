/* Report module registry.
 *
 * Renderers own a single section. This registry owns ordering and wiring so a
 * module can be changed, added or removed without editing the report lifecycle.
 */
(function (global) {
    'use strict';

    function call(name, args) {
        const renderer = global[name];
        if (typeof renderer !== 'function') return false;
        renderer(...args);
        return true;
    }

    const fullReportModules = Object.freeze([
        { key: 'thesis', run: (s, meta) => call('renderThesis', [s.thesis || {}, s.growth_score || {}, meta.lang]) },
        { key: 'references', run: (s, meta) => call('renderReferences', [s.references || [], meta.lang]) },
        { key: 'strategy_radar', run: (s) => call('renderStrategyRadar', [s.strategy_radar || {}]) },
        { key: 'website', run: (s, meta) => call('renderWebsite', [s.website_analysis || {}, s.evolution_summary || '', meta.lang]) },
        { key: 'github', run: (s) => call('renderGithub', [s.github_oss || {}]) },
        { key: 'producthunt', run: (s) => call('renderProductHunt', [s.producthunt || {}]) },
        { key: 'social', run: (s) => call('renderSocial', [s.social_media || {}]) },
        { key: 'propagation', run: (s) => call('renderPropagation', [s.propagation || {}]) },
        { key: 'traffic', run: (s) => call('renderTraffic', [s.traffic_analysis || {}]) },
        { key: 'pricing', run: (s) => call('renderPricing', [s.pricing || {}]) },
        { key: 'bizmodel', run: (s) => call('renderBizmodel', [s.bizmodel || {}]) },
        { key: 'funding', run: (s) => call('renderFunding', [s.funding || {}]) },
        { key: 'pr_news', run: (s) => call('renderPR', [s.pr_news || {}]) },
        { key: 'traffic_peaks', run: (s) => call('renderPeaks', [s.traffic_peaks || {}]) },
        { key: 'growth_analysis', run: (s) => call('renderGrowth', [s.growth_analysis || {}]) },
        { key: 'insights', run: (s) => call('renderInsights', [s.ai_insights || s.ai_summary || {}]) },
        { key: 'summary', run: (s) => call('renderSummary', [s.summary || {}]) },
        { key: 'strategy', run: (s) => call('renderStrategy', [s.growth_strategy || {}]) },
        { key: 'playbooks', run: (_s, _meta, report) => call('renderPlaybooks', [report]) },
    ]);

    const partialReportModules = Object.freeze({
        website: {
            renderer: 'renderWebsite',
            format: (data) => ({
                title: global._t('Website Evolution', '官网演变分析'),
                domain: data.domain,
                first_seen: data.first_seen,
                total_snapshots: data.total_snapshots,
                deep_timeline: data.deep_timeline || [],
                current: data.current_site || {},
                key_changes: data.key_changes || [],
            }),
        },
        social: {
            renderer: 'renderSocial',
            format: (data) => ({
                title: global._t('Social Media', '社交媒体'),
                brand: data.brand,
                channels: data.channels || {},
                propagation_metrics: data.propagation_metrics || {},
            }),
        },
        traffic: { renderer: 'renderTraffic', format: (data) => data },
        producthunt: { renderer: 'renderProductHunt', format: (data) => data },
        pricing: { renderer: 'renderPricing', format: (data) => data },
    });

    function renderFull(report) {
        const sections = report.sections || {};
        const meta = report.meta || {};
        fullReportModules.forEach((module) => module.run(sections, meta, report));
        global.AnalookFieldHelp?.enhance(document.getElementById('report-section'));
    }

    function renderPartial(partial, renderedKeys) {
        Object.entries(partial || {}).forEach(([key, data]) => {
            if (renderedKeys.has(key)) return;
            const module = partialReportModules[key];
            if (!module) return;
            try {
                if (call(module.renderer, [module.format(data)])) renderedKeys.add(key);
            } catch (_) {
                // A partial module must never block the remaining report.
            }
        });
        global.AnalookFieldHelp?.enhance(document.getElementById('report-section'));
    }

    global.AnalookReportModules = Object.freeze({
        fullReportModules,
        partialReportModules,
        renderFull,
        renderPartial,
    });
})(window);
