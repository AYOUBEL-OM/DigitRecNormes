# DigitRec

Plateforme SaaS de recrutement (**ATS**) qui automatise le parcours candidat : dépôt de CV, filtrage intelligent, tests écrits (QCM / exercices), entretien oral avec enregistrement et analyse, proctoring caméra, scoring consolidé et rapports pour les équipes RH.

---

## Présentation du projet

### Objectif

Réduire le temps de tri des candidatures et structurer la décision RH grâce à des étapes standardisées : analyse automatique des CV, évaluation technique écrite, évaluation orale avec indicateurs comportementaux, puis synthèses exploitables (dashboard, exports).

### Problématique

Les processus manuels ne scalent pas ; les entreprises ont besoin d’un **fil conducteur unique** (offre → candidature → tests → oral → décision) avec traçabilité et scores comparables.

### Solution proposée

Une application **full-stack** : frontend **React / TypeScript** (Vite), backend **FastAPI**, persistance **PostgreSQL**, authentification **JWT** dédiée **candidat** et **entreprise**, intégrations **IA** (Groq pour LLM et transcription Whisper), génération de **rapports** (JSON enrichi, **PDF** pour l’entretien oral via ReportLab).

### Concept de filtrage intelligent

Les CV sont analysés (texte extrait des PDF notamment via **PyMuPDF**, scoring et filtrage métier dans `cv_filtering`) pour orienter la suite du parcours ; les seuils et règles reflètent la logique métier codée dans le backend, pas une simple iframe externe.

---

## Fonctionnalités principales

| Domaine | Description |
|--------|-------------|
| **Gestion entreprises** | Comptes entreprise, paramètres, accès dashboard |
| **Gestion candidats** | Inscription / connexion candidat, profil |
| **Offres d’emploi** | Création et publication d’offres, liens d’accès publics |
| **Candidatures** | Dépôt candidature, suivi par offre |
| **Analyse CV IA** | Extraction texte, analyse et scoring CV côté serveur |
| **Scoring CV** | Agrégation dans le flux candidature / décision de passage aux étapes suivantes |
| **QCM automatisés** | Génération et correction de quiz (types QCM / exercice selon configuration) |
| **Entretien oral intelligent** | Questions oral, enregistrement audio, transcription, scores par question |
| **Transcription audio** | **Groq Whisper** (`oral_answer_analysis.transcribe_audio`) |
| **Proctoring** | Événements caméra / navigateur agrégés (présence, regard, suspicion, navigation, etc.) |
| **Génération PDF** | Rapport d’entretien oral PDF (**ReportLab**, `oral_report_service.build_pdf_bytes`) |
| **Dashboard RH** | Données agrégées par entreprise (`/api/dashboard`) |
| **Scoring final** | Scores oraux, écrits et globaux selon modèles et services métier |
| **Rapports détaillés** | Payload JSON entreprise (oral + écrit), synthèses IA avec **fallback** si Groq indisponible |
| **Abonnements** | Intégration **Stripe** (plans, webhooks — variables d’environnement dédiées) |

---

## Architecture du système

### Frontend

SPA **React 18** + **TypeScript**, bundlée avec **Vite** (port dev par défaut **8080**). Routage **react-router-dom**, données souvent via **TanStack Query**, UI **Tailwind CSS** et composants type **shadcn/ui** (Radix UI). Appels API via services centralisés (ex. `authService`), jetons JWT en **localStorage**. Module entretien oral dédié sous `Frontend/src/oral-interview/` (caméra, proctoring, enregistrement).

### Backend

API **FastAPI** (`app/main.py`) : préfixe **`/api`** pour les routeurs (auth, offres, candidatures, entreprises, dashboard, quiz, oral, abonnements). Authentification **JWT** (`SECRET_KEY`, `ALGORITHM` HS256). Persistance **SQLAlchemy 2** + sessions PostgreSQL. Fichiers statiques montés pour CV et médias oraux (`/uploads/...`).

### Base de données

**PostgreSQL** — URL construite via **`DATABASE_URL`** ou champs `POSTGRES_*` dans `app/config.py`. Le projet est testé en pratique avec des hébergeurs type **Supabase** pour la base (SSL `sslmode` géré dans la config), sans utiliser **Supabase Auth** pour l’application (auth maison JWT).

### IA

- **Groq** : modèle LLM configurable (`GROQ_MODEL`, défaut type Llama 3.1 70B dans la config), prompts pour rapports, pertinence des réponses, etc.
- **Groq Whisper** : transcription des réponses orales (`GROQ_WHISPER_MODEL`, ex. `whisper-large-v3-turbo`).
- **Heuristiques** : scores sans LLM (pertinence bandée, proctoring, quiz de secours) pour robustesse.

### Proctoring

Côté client : **MediaPipe** (`@mediapipe/tasks-vision`) et/ou **FaceDetector** du navigateur lorsque disponible ; agrégation dans `useOralProctoring.ts` (regard, posture, heartbeats).  
Côté serveur : `oral_proctoring.py` normalise les flags, calcule un **score de suspicion**, gère présence / navigation / signaux téléphone **sans modèle YOLO** — la « détection téléphone » repose sur **heuristiques de posture et cumuls d’événements**, pas sur une détection d’objets type deep learning dédiée.

---

## Stack technique

### Frontend

| Technologie | Usage |
|-------------|--------|
| **React** | UI |
| **TypeScript** | Typage |
| **Vite** | Build & dev server |
| **Tailwind CSS** | Styles |
| **Radix UI / shadcn-style** | Composants (`src/components/ui`) |
| **React Router** | Navigation |
| **TanStack Query** | État serveur |
| **Vitest** / **Playwright** | Tests (config présente) |

### Backend

| Technologie | Usage |
|-------------|--------|
| **FastAPI** | API REST |
| **SQLAlchemy** | ORM |
| **Pydantic / pydantic-settings** | Schémas & configuration |
| **python-jose** | JWT |
| **passlib** | Hachage mots de passe |
| **ReportLab** | PDF rapport oral |
| **PyMuPDF** | Lecture PDF CV |
| **groq** | Client API Groq |

### Base de données

- **PostgreSQL** (requis ; `DATABASE_URL` obligatoire au runtime pour `database.py`).

### IA & audio

- **Groq** (LLM + Whisper)
- Analyses **heuristiques** de repli (`oral_answer_analysis`, `fallback_qcm_bank`, etc.)

---

## Structure du projet

```
DigitRecNormes/
├── Frontend/                 # Application React (Vite)
│   ├── src/
│   │   ├── components/       # UI réutilisable (ui/, layout…)
│   │   ├── pages/          # Écrans (dashboard, offres, login…)
│   │   ├── oral-interview/   # Entretien oral + proctoring + hooks
│   │   ├── services/       # Appels API, auth
│   │   └── ...
│   ├── package.json
│   └── vite.config.ts
├── backend/
│   ├── app/
│   │   ├── main.py         # Point d’entrée FastAPI, CORS, montage /uploads
│   │   ├── config.py       # Variables d’environnement
│   │   ├── database.py     # Engine PostgreSQL
│   │   ├── core/           # Sécurité JWT
│   │   ├── models/         # Modèles SQLAlchemy
│   │   ├── routers/        # auth_*, offres, candidatures, entreprises, dashboard, oral_interview, subscriptions
│   │   ├── api/endpoints/  # quiz…
│   │   └── services/       # Logique métier (oral_*, quiz, cv_filtering, stripe…)
│   ├── requirements.txt
│   └── .env                # Non versionné — à créer localement
└── README.md
```

---

## Module de test écrit

- **Génération** : configuration par offre ; appels via routes quiz (`app/api/endpoints/quiz.py`) et services `quiz_service`.
- **Correction** : évaluation côté serveur, normalisation QCM (`qcm_normalization`).
- **Scoring** : résultats stockés sur `tests_ecrits` / payload de rapport (`written_quiz_report_service`).
- **Fallback questions** : banque de secours **`fallback_qcm_bank`** (ex. jeu de QCM métier) si la génération IA n’est pas disponible ; pipeline texte Maroc possible (`morocco_text_pipeline`).

---

## Module entretien oral

- **Questions** : chargement / création (`oral_questions_service`, banques `oral_question_banks`), repli d’urgence possible (`persist_emergency_fallback_questions`).
- **Enregistrement audio** : fichiers sous répertoires configurés (`ORAL_ANSWERS_DIR`, etc.), servis en statique.
- **Transcription** : **Groq Whisper** dans `oral_answer_analysis`.
- **Scoring** : pertinence, hésitation, cohérence, agrégation session (`oral_answer_analysis`, `oral_session_finalize`).
- **Rapport oral** : JSON riche + IA / fallback (`oral_report_service`), **PDF** entreprise, cache contrôlé (`enterprise_report_ai` dans `cheating_flags` avec invalidation par empreinte).

---

## Module proctoring

| Aspect | Réalité dans le code |
|--------|----------------------|
| **Caméra** | Flux vidéo analysé côté navigateur (MediaPipe / FaceDetector si présent). |
| **Présence** | Heartbeats + événements (`presence_anomaly`) ; agrégation serveur (`oral_proctoring`). |
| **Regard** | Directions discrétisées et fenêtres glissantes ; ratios stockés dans `cheating_flags.gaze`. |
| **Téléphone** | **Pas de détecteur d’objets type YOLO** ; signaux basés sur **posture**, **regard**, **cumulative evidence**, événements client — à interpréter comme **suspicion / confirmation progressive**, pas comme vision par ordinateur « téléphone en main » garantie. |
| **Onglets / plein écran** | Compteurs `tab_switch_count`, `fullscreen_exit_count`. |
| **Score de suspicion** | `compute_suspicion_score`, niveaux LOW/MEDIUM/HIGH, champs sur `TestOral` et dans les estimations JSON. |

Jeton de session oral séparé du JWT : en-tête **`X-Digitrec-Oral-Token`** (token stocké côté candidat pour la session d’entretien).

---

## Génération des rapports

| Rapport | Contenu |
|---------|---------|
| **Oral (entreprise)** | `build_enterprise_report_payload` : métriques proctoring, synthèse type IA (Groq) ou **fallback déterministe** si indisponible, analyse comportementale, exports JSON utilisés par le front et la route PDF. |
| **Écrit** | `build_written_quiz_report_payload` : détail QCM / exercice pour le dashboard (pas de générateur PDF dédié dans le même service que l’oral — le PDF principal documenté est celui de l’**entretien oral**). |
| **Export PDF** | `build_pdf_bytes` (ReportLab), téléchargement côté route oral entreprise. |
| **Synthèse intelligente** | Champs type `summary`, `strengths`, `weaknesses`, etc., avec **sanitation** et cohérence post-traitement (`_apply_ai_report_coherence`, `_sanitize_ai_synthesis_texts`). |

---

## Sécurité

- **JWT** : séparation stricte **entreprise** vs **candidat** (`get_entreprise_from_token`, `get_candidat_from_token`).
- **Tokens oraux** : accès session entretien via **`X-Digitrec-Oral-Token`** (lié au modèle `TestOral`), distinct du bearer général.
- **Validation** : dépendances FastAPI sur les routeurs ; mots de passe hachés (passlib/bcrypt).
- **CORS** : configuré dans `main.py` pour origines locales courantes (localhost / 127.0.0.1 sur plusieurs ports).
- **En-têtes** : politique anti-cache sur les réponses HTTP (`Cache-Control`).

---

## Installation

### Prérequis

- **Node.js** (LTS recommandé) et **npm**
- **Python** 3.11+ (selon environnement)
- **PostgreSQL** accessible + fichier `.env` backend

### 1. Cloner le dépôt

```bash
git clone <url-du-depot>
cd DigitRecNormes
```

### 2. Frontend

```bash
cd Frontend
npm install
npm run dev
```

Le serveur de dev écoute par défaut sur **http://localhost:8080** (voir `vite.config.ts`).

### 3. Backend

```bash
cd backend
python -m venv .venv
# Windows : .venv\Scripts\activate
# Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
```

Créer **`backend/.env`** (voir section suivante), puis :

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Documentation interactive API : **http://127.0.0.1:8000/docs**

### 4. Tests frontend (optionnel)

```bash
cd Frontend
npm run test
```

---

## Variables d’environnement

Fichier principal : **`backend/.env`** (non versionné). Exemples de clés (**ne pas commiter de secrets réels**) :

| Variable | Rôle |
|----------|------|
| `DATABASE_URL` | URI PostgreSQL complète (prioritaire) |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE`, `POSTGRES_SSL_MODE` | Construction de l’URL si `DATABASE_URL` vide |
| `SECRET_KEY` | Signature JWT (**obligatoire en production**) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée de vie des jetons |
| `GROQ_API_KEY` | Appels LLM + Whisper Groq |
| `GROQ_MODEL` | Modèle chat Groq |
| `GROQ_WHISPER_MODEL` | Modèle transcription |
| `FRONTEND_PUBLIC_URL` | URL publique du front (emails, liens) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` / `SUPABASE_KEY` | Stockage ou services compatibles Supabase si utilisés |
| `SMTP_*` | Envoi d’emails (hôte, port, auth, expéditeur) |
| `STRIPE_*` | Clés Stripe, webhook, IDs de prix |
| Répertoires uploads | `UPLOAD_DIR`, `ORAL_*_DIR` — chemins relatifs au dossier `backend/` |

---

## Workflow global

1. **L’entreprise** crée une **offre** et diffuse le lien de candidature.  
2. Le **candidat** postule et dépose son **CV**.  
3. Le backend **analyse et score** le CV (`cv_filtering`).  
4. Si le parcours le prévoit : **test écrit** (QCM / exercice), correction et rapport JSON.  
5. **Entretien oral** : questions, enregistrement, **transcription**, scoring, **proctoring**.  
6. **Rapport** oral (JSON + PDF) et vue **dashboard entreprise**.  
7. **Décision RH** appuyée sur scores, synthèses et indicateurs de suspicion (à interpréter avec discernement).

---

## Points forts du projet

- Automatisation bout-en-bout du flux recrutement sur une seule plateforme.
- **IA** intégrée (Groq) avec **repli heuristique** pour limiter les blocages.
- **Proctoring** et agrégats comportementaux pour enrichir le jugement humain.
- Architecture **moderne** (FastAPI + React/Vite), séparation claire des rôles.
- Rapports **structurés** (PDF oral, payloads JSON détaillés).

---

## Limites actuelles

- **Dépendance aux services externes** : Groq / Whisper indisponibles ⇒ transcrits ou synthèses dégradés (fallbacks prévus mais moins riches).
- **Proctoring heuristique** : sensible à la qualité **webcam**, à l’éclairage et aux navigateurs ; **pas de détection d’objets dédiée** pour le téléphone.
- **Micro / audio** : qualité d’enregistrement impactant la transcription.
- **FaceDetector** : non disponible sur tous les navigateurs ; comportements sans détection réelle documentés côté client (pas de « faux visage » garanti comme preuve biométrique).

---

## Perspectives d’amélioration

- Application **mobile** ou PWA pour candidats.
- Modèles IA plus fins ou **multimodaux** pour l’analyse comportementale.
- **Visioconférence** temps réel intégrée (hors scope actuel).
- **Détection d’objets** (ex. modèles vision dédiés) si besoin métier de preuve visuelle forte.
- **Analytics RH** avancées (tableaux de bord, funnel, A/B).

---

## Auteurs

Projet académique / équipe — à compléter :

- **Équipe DigitRec** — &lt;noms, promotion, établissement&gt;

---

*Documentation alignée sur la structure du dépôt au moment de la rédaction ; en cas d’évolution du code, adapter ce README en conséquence.*
