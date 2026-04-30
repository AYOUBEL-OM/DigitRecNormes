-- Abonnements Stripe + client Stripe sur entreprises
-- Exécuter sur PostgreSQL (Supabase ou local).

ALTER TABLE entreprises
  ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entreprises_stripe_customer_id
  ON entreprises (stripe_customer_id)
  WHERE stripe_customer_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entreprise_id UUID NOT NULL REFERENCES entreprises(id) ON DELETE CASCADE,
  stripe_customer_id VARCHAR(255),
  stripe_subscription_id VARCHAR(255),
  stripe_checkout_session_id VARCHAR(255),
  plan_code VARCHAR(32) NOT NULL,
  billing_cycle VARCHAR(32) NOT NULL DEFAULT 'monthly',
  status VARCHAR(32) NOT NULL,
  amount_cents INTEGER,
  currency VARCHAR(8) NOT NULL DEFAULT 'mad',
  start_date TIMESTAMPTZ,
  end_date TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_entreprise_id ON subscriptions (entreprise_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions (status);
CREATE INDEX IF NOT EXISTS ix_subscriptions_checkout_session ON subscriptions (stripe_checkout_session_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_stripe_subscription_id
  ON subscriptions (stripe_subscription_id)
  WHERE stripe_subscription_id IS NOT NULL;
