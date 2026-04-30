-- Migration tests_oraux : supprime les colonnes dupliquées / redondantes.
-- À exécuter APRÈS déploiement du code qui :
--   - n’utilise plus `eye_contact_score` (seul `eye_contact_score_global` est conservé) ;
--   - stocke le résumé proctoring dans `cheating_flags->summary_global` au lieu de `cheating_flags_global`.
--
-- Transaction recommandée.

BEGIN;

-- 1) Score regard : conserver la valeur la plus informative
UPDATE tests_oraux
SET eye_contact_score_global = COALESCE(eye_contact_score_global, eye_contact_score)
WHERE eye_contact_score IS NOT NULL;

-- 2) Résumé texte : copier vers JSONB avant DROP de la colonne Text
UPDATE tests_oraux
SET cheating_flags = jsonb_set(
  COALESCE(cheating_flags::jsonb, '{}'::jsonb),
  '{summary_global}',
  to_jsonb(COALESCE(cheating_flags_global, ''))
)
WHERE cheating_flags_global IS NOT NULL
  AND btrim(cheating_flags_global) <> ''
  AND (
    cheating_flags IS NULL
    OR NOT (cheating_flags::jsonb ? 'summary_global')
    OR btrim(COALESCE(cheating_flags->>'summary_global', '')) = ''
  );

-- 3) Suppression des colonnes SQL
ALTER TABLE tests_oraux DROP COLUMN IF EXISTS eye_contact_score;
ALTER TABLE tests_oraux DROP COLUMN IF EXISTS cheating_flags_global;

COMMIT;
