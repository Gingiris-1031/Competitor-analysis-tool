-- ════════════════════════════════════════════════════════════════════════
-- Growth Diagnostic Scorecards — 增长诊断评分卡。
-- 每张卡 = 一次「你 vs 竞品 vs 行业基准」诊断。免费预览层（总分 + 红黄绿灯）
-- 与付费解锁层（逐项修复方案）共用一行，unlocked 标记是否已付费解锁。
-- 分享页 /scorecard/<id> 走匿名只读（同 share/audit 模式），is_public 控制可见性。
--
-- Paste into Supabase SQL editor → Run. Idempotent.
-- ════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS scorecards (
    -- 不可猜的短 hash（分享链接用），server 生成。
    id           TEXT        PRIMARY KEY,
    -- 生成者（登录才有；匿名预览为 NULL）。
    user_id      UUID,
    -- 被诊断的自有域名。
    domain       TEXT        NOT NULL,
    -- 品类：pro_c / smb / b2b / default（决定付费转化基准）。
    category     TEXT        NOT NULL DEFAULT 'default',
    -- 用户手填的三漏斗数 + 可选 CAC / SEO 分。
    inputs       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- score_growth() 的完整输出（含 metrics + fixes）。
    result       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- 竞品对照：[{domain, overall_score, metrics}]。
    competitors  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- 分享可见性（默认公开，同 audit）。
    is_public    BOOLEAN     NOT NULL DEFAULT TRUE,
    -- 是否已付费解锁逐项修复方案。
    unlocked     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 按用户拉自己的历史评分卡。
CREATE INDEX IF NOT EXISTS idx_scorecards_user
    ON scorecards (user_id, created_at DESC);

-- ── RLS off: service-role only ────────────────────────────────────────────
-- 与 audit_cache 一致：表由 server 的 service-role 客户端读写，anon 无权限；
-- 匿名分享读取统一走后端 /api/scorecard/<id> 端点，不直接暴露表。
ALTER TABLE scorecards DISABLE ROW LEVEL SECURITY;
