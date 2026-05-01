-- Migration : anciens plans BASIC / PRO / PREMIUM → LIMITED / UNLIMITED
-- (l’essai gratuit TRIAL est créé à l’inscription ou au login pour les comptes sans ligne.)

UPDATE subscriptions
SET plan_code = 'LIMITED'
WHERE UPPER(TRIM(plan_code)) = 'BASIC';

UPDATE subscriptions
SET plan_code = 'UNLIMITED'
WHERE UPPER(TRIM(plan_code)) IN ('PRO', 'PREMIUM');
