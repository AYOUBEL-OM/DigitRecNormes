-- Table pour la persistance des résultats de tests écrits (PostgreSQL).
-- Exécuter une fois si la table n’existe pas encore.

CREATE TABLE IF NOT EXISTS public.tests_ecrits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_candidature UUID NOT NULL REFERENCES public.candidatures (id) ON DELETE CASCADE,
    score_ecrit DOUBLE PRECISION NOT NULL,
    status_reussite BOOLEAN NOT NULL,
    date_passage TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tests_ecrits_candidature ON public.tests_ecrits (id_candidature);
