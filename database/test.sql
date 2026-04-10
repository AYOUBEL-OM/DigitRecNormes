-- =====================================================
-- Schéma ATS - Plateforme de Recrutement SaaS
-- Base de données : MySQL
-- =====================================================

CREATE DATABASE IF NOT EXISTS DigitRec
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE DigitRec;

-- -----------------------------------------------------
-- Table : entreprises
-- Comptes des entreprises (recruteurs)
-- -----------------------------------------------------
CREATE TABLE entreprises (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  mot_de_passe_hash VARCHAR(255) NOT NULL,
  nom_entreprise VARCHAR(255) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_entreprises_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table : offres
-- Offres d'emploi créées par les entreprises
-- type_test : QCM ou Exercice
-- lien_uuid : identifiant unique pour l'URL de candidature
-- -----------------------------------------------------
CREATE TABLE offres (
  id INT AUTO_INCREMENT PRIMARY KEY,
  entreprise_id INT NOT NULL,
  titre VARCHAR(255) NOT NULL,
  description TEXT NOT NULL,
  type_test ENUM('QCM', 'Exercice') NOT NULL DEFAULT 'QCM',
  lien_uuid VARCHAR(36) NOT NULL UNIQUE,
  actif BOOLEAN DEFAULT TRUE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_offres_entreprise FOREIGN KEY (entreprise_id) REFERENCES entreprises(id) ON DELETE CASCADE,
  INDEX idx_offres_entreprise (entreprise_id),
  INDEX idx_offres_lien_uuid (lien_uuid),
  INDEX idx_offres_actif (actif)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table : candidats
-- Comptes des candidats
-- -----------------------------------------------------
CREATE TABLE candidats (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  mot_de_passe_hash VARCHAR(255) NOT NULL,
  nom VARCHAR(255) NOT NULL,
  prenom VARCHAR(255) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_candidats_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------
-- Table : candidatures
-- Candidatures (lien Candidat <-> Offre + CV)
-- Un candidat ne peut postuler qu'une fois par offre
-- -----------------------------------------------------
CREATE TABLE candidatures (
  id INT AUTO_INCREMENT PRIMARY KEY,
  candidat_id INT NOT NULL,
  offre_id INT NOT NULL,
  cv_path VARCHAR(512) NOT NULL COMMENT 'Chemin du fichier CV uploadé',
  statut ENUM('nouvelle', 'en_cours', 'acceptee', 'refusee') DEFAULT 'nouvelle',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_candidatures_candidat FOREIGN KEY (candidat_id) REFERENCES candidats(id) ON DELETE CASCADE,
  CONSTRAINT fk_candidatures_offre FOREIGN KEY (offre_id) REFERENCES offres(id) ON DELETE CASCADE,
  CONSTRAINT uq_candidat_offre UNIQUE (candidat_id, offre_id),
  INDEX idx_candidatures_offre (offre_id),
  INDEX idx_candidatures_candidat (candidat_id),
  INDEX idx_candidatures_statut (statut)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
