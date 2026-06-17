-- Promo codes system
-- Created: 2026-06-17

CREATE TABLE IF NOT EXISTS promo_codes (
  code TEXT PRIMARY KEY,
  credits_reward INT NOT NULL DEFAULT 20,
  max_uses INT DEFAULT NULL,  -- NULL = unlimited
  used_count INT NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  code TEXT NOT NULL REFERENCES promo_codes(code),
  redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, code)  -- one use per user per code
);

-- Seed the GINGIRIS20 code
INSERT INTO promo_codes (code, credits_reward, active)
VALUES ('GINGIRIS20', 20, TRUE)
ON CONFLICT (code) DO NOTHING;
