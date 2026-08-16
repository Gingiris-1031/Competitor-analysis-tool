-- Free accounts receive two one-time starter credits, not a monthly allowance.
-- This replaces the legacy signup trigger that still inserted three credits.
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (
    id, email, plan_type, credits_balance, credits_monthly_quota,
    reports_public_default, created_at, updated_at
  ) VALUES (
    NEW.id, NEW.email, 'free', 2, 2, TRUE, NOW(), NOW()
  ) ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;
