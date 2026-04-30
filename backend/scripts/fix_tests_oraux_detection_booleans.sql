-- ---------------------------------------------------------------------------
-- tests_oraux : colonnes de détection proctoring toujours booléennes (pas NULL).
-- À exécuter une fois sur PostgreSQL avant/après déploiement du modèle SQLAlchemy.
-- ---------------------------------------------------------------------------

UPDATE tests_oraux SET phone_detected = false WHERE phone_detected IS NULL;
UPDATE tests_oraux SET other_person_detected = false WHERE other_person_detected IS NULL;
UPDATE tests_oraux SET presence_anomaly_detected = false WHERE presence_anomaly_detected IS NULL;

ALTER TABLE tests_oraux
  ALTER COLUMN phone_detected SET DEFAULT false;

ALTER TABLE tests_oraux
  ALTER COLUMN other_person_detected SET DEFAULT false;

ALTER TABLE tests_oraux
  ALTER COLUMN presence_anomaly_detected SET DEFAULT false;

ALTER TABLE tests_oraux
  ALTER COLUMN phone_detected SET NOT NULL;

ALTER TABLE tests_oraux
  ALTER COLUMN other_person_detected SET NOT NULL;

ALTER TABLE tests_oraux
  ALTER COLUMN presence_anomaly_detected SET NOT NULL;
