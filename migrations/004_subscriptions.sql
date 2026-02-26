-- Migration 004: Stripe billing — contractor subscriptions table

CREATE TABLE IF NOT EXISTS contractor_subscriptions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  contractor_id UUID NOT NULL REFERENCES contractors(id) ON DELETE CASCADE,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  plan TEXT NOT NULL DEFAULT 'starter',       -- starter | pro
  status TEXT NOT NULL DEFAULT 'pending',      -- pending | active | past_due | canceled
  current_period_end TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(contractor_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sub_contractor ON contractor_subscriptions(contractor_id);
CREATE INDEX IF NOT EXISTS idx_sub_stripe_customer ON contractor_subscriptions(stripe_customer_id);

-- RLS
ALTER TABLE contractor_subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Contractors can view own subscription"
ON contractor_subscriptions FOR SELECT
TO authenticated
USING (
  contractor_id = (SELECT id FROM contractors WHERE user_id = auth.uid())
);

-- Service role full access
CREATE POLICY "Service role full access subscriptions"
ON contractor_subscriptions FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Add is_active column to projects if not exists (for subscription enforcement)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;

-- Updated_at trigger
CREATE OR REPLACE TRIGGER set_subscription_updated_at
  BEFORE UPDATE ON contractor_subscriptions
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();
