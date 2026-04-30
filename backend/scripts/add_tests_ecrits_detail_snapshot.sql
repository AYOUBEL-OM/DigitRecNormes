-- Rapport test écrit (dashboard entreprise) : détail Q/R au moment de la soumission.
-- À exécuter une fois sur PostgreSQL / Supabase si la colonne n’existe pas encore.

ALTER TABLE tests_ecrits
  ADD COLUMN IF NOT EXISTS detail_snapshot JSONB;

COMMENT ON COLUMN tests_ecrits.detail_snapshot IS
  'Snapshot JSON (version 1) : questions/réponses QCM ou consigne/réponse exercice.';
