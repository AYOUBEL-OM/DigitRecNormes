-- ---------------------------------------------------------------------------
-- tests_oraux.suspicious_movements_count : jamais NULL (0 = aucun signal).
-- Exécuter sur PostgreSQL après alignement du modèle SQLAlchemy.
-- ---------------------------------------------------------------------------

UPDATE tests_oraux SET suspicious_movements_count = 0 WHERE suspicious_movements_count IS NULL;

ALTER TABLE tests_oraux
  ALTER COLUMN suspicious_movements_count SET DEFAULT 0;

ALTER TABLE tests_oraux
  ALTER COLUMN suspicious_movements_count SET NOT NULL;
