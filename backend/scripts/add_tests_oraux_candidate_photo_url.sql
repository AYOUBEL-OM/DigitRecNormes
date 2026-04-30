-- Photo d’identité candidat avant entretien oral (rapport + PDF).
ALTER TABLE tests_oraux
  ADD COLUMN IF NOT EXISTS candidate_photo_url TEXT;
