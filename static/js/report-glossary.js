/* Analook report glossary.
 *
 * Keep metric definitions here rather than inside renderer templates. This is
 * the single reviewable knowledge source for field help in both EN and ZH.
 */
(function (global) {
    'use strict';

    global.AnalookReportGlossary = Object.freeze({
        organic_search_estimate: Object.freeze({
            title: { en: 'Organic search estimate', zh: '有机搜索流量估算' },
            description: {
                en: 'Estimated monthly visits from organic search, inferred from ranking keywords and expected click-through rates.',
                zh: '基于关键词排名和预期点击率推算的每月自然搜索访问量。',
            },
            caveat: {
                en: 'This is a directional estimate, not first-party analytics. Missing evidence stays blank instead of becoming zero.',
                zh: '这是趋势估算，不是网站一方分析数据；证据缺失时保持为空，不视为 0。',
            },
            source: 'DataForSEO / SEOReviewTools',
        }),
        twitter_followers: Object.freeze({
            title: { en: 'Twitter / X followers', zh: 'Twitter / X 粉丝' },
            description: {
                en: 'The latest publicly observable follower count for the matched official Twitter / X account.',
                zh: '匹配到的官方 Twitter / X 账号的最新公开粉丝数。',
            },
            caveat: {
                en: 'Account matching and public counts can lag or be unavailable. Treat the number as reach evidence, not engagement quality.',
                zh: '账号匹配和公开数据可能延迟或缺失；它表示触达规模，不代表互动质量。',
            },
            source: 'TwitterAPI.io / public web evidence',
        }),
        product_hunt_votes: Object.freeze({
            title: { en: 'Product Hunt votes', zh: 'Product Hunt 票数' },
            description: {
                en: 'Upvotes observed for the matched Product Hunt launch used in this report.',
                zh: '本报告匹配到的 Product Hunt 发布页获得的投票数。',
            },
            caveat: {
                en: 'Votes are a launch-distribution signal. They do not prove revenue, retention, or current active usage.',
                zh: '票数只是发布传播信号，不能证明收入、留存或当前活跃用户。',
            },
            source: 'Product Hunt public API / public page',
        }),
        first_seen: Object.freeze({
            title: { en: 'First seen', zh: '首次出现' },
            description: {
                en: 'The earliest website snapshot found for this domain in the available archive history.',
                zh: '在可用网页归档历史中找到的该域名最早快照时间。',
            },
            caveat: {
                en: 'This is not necessarily the company founding date or the website launch date; archives can have gaps.',
                zh: '它不一定是公司成立日期或网站上线日期，因为归档可能不完整。',
            },
            source: 'Internet Archive / Wayback Machine',
        }),
    });
})(window);
