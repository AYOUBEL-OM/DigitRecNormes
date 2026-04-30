-- Colonne dédiée au niveau d’expérience (Junior / Confirmé / Senior).
-- Avant cette colonne, `level` était un synonyme SQLAlchemy de `niveau_etude`,
-- ce qui écrasait l’expérience par le niveau d’études à l’enregistrement.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'offres'
      AND column_name = 'level'
  ) THEN
    ALTER TABLE offres ADD COLUMN level TEXT;
  END IF;
END $$;

-- Optionnel : anciennes lignes où `niveau_etude` contenait le niveau d’expérience (même colonne qu’avant).
UPDATE offres
SET
  level = TRIM(niveau_etude),
  niveau_etude = NULL
WHERE (level IS NULL OR TRIM(level) = '')
  AND niveau_etude IS NOT NULL
  AND TRIM(niveau_etude) IN ('Junior', 'Confirmé', 'Senior');
