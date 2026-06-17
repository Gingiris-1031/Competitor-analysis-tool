-- Fix: new user signup trigger was giving 3 credits, should be 2
-- Update the handle_new_user function to use 2 as default free tier credits

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (
    id,
    email,
    plan_type,
    credits_balance,
    credits_monthly_quota,
    reports_public_default,
    created_at,
    updated_at
  ) VALUES (
    NEW.id,
    NEW.email,
    'free',
    2,   -- free tier: 2 credits (was 3)
    2,   -- free tier monthly quota: 2 (was 3)
    TRUE,
    NOW(),
    NOW()
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;
