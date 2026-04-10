# 🚀 DigitRec – Project Rules & Architecture Guide

---

## 🧠 1. Vision Générale

DigitRec est une plateforme SaaS de recrutement (ATS) qui automatise :

1. Création d'offres (Entreprise)
2. Génération de lien (token)
3. Candidature via lien
4. Analyse CV (AI)
5. Tests écrits + oraux
6. Évaluation finale

👉 Objectif : automatiser le funnel de recrutement.

---

## 🏗️ 2. Architecture Officielle (STRICT)

### Frontend

* React + TypeScript (Vite)
* Tailwind CSS
* Fetch API

### Backend

* FastAPI (Python)
* SQLAlchemy ORM
* JWT Authentication

### Database

* PostgreSQL (Supabase)

---

## 🔐 3. AUTHENTICATION (VERY IMPORTANT)

🚨 Supabase Auth est SUPPRIMÉ.

✔️ Authentication = FastAPI JWT uniquement

### Endpoints:

* `/api/auth/candidat/login`
* `/api/auth/entreprise/login`

### Frontend DOIT:

* appeler backend seulement
* stocker JWT dans localStorage
* envoyer Authorization: Bearer token

---

## ❌ 4. INTERDIT

Il est STRICTEMENT interdit de:

* utiliser supabase.auth
* connecter frontend directement à la DB
* bypass backend
* ajouter Redux / Next.js / autres frameworks
* changer l'architecture

---

## ✅ 5. Règles de Développement

* toujours utiliser `authService.ts`
* toujours utiliser `apiFetch`
* ne jamais dupliquer code
* respecter structure existante
* ne pas casser le design

---

## 🔄 6. Workflow de Travail

1. Pull latest code:

```bash
git pull origin main
```

2. Créer branche:

```bash
git checkout -b feature/nom-feature
```

3. Développer

4. Push:

```bash
git push origin feature/nom-feature
```

5. Merge

---

## 👥 7. Travail en équipe

* 1 seul main stable
* chacun travaille sur branch
* ne jamais push direct sur main sans test

---

## 🧩 8. Règles Frontend

* aucune logique métier côté frontend
* aucune connexion directe DB
* UI ≠ logique

---

## 🧩 9. Règles Backend

* toute logique passe par FastAPI
* validation + sécurité côté backend
* JWT obligatoire

---

## 🎯 10. Current Focus

* Auth stable ✔️
* Dashboard role-based ⏳
* Offres system ⏳
* Candidatures flow ⏳
* AI integration ⏳

---

## 📌 Conclusion

Ce projet doit rester:

✔️ cohérent
✔️ scalable
✔️ maintenable

👉 Toute modification doit respecter cette architecture.

---


hada
AI AGENT PROMPT 


You are working on a production-level SaaS project called DigitRec.

You MUST strictly follow the project architecture and rules.

* Backend: FastAPI + JWT
* Frontend: React + fetch
* Database: PostgreSQL (Supabase DB only)

CRITICAL:

* DO NOT use Supabase Auth
* DO NOT connect frontend directly to database
* ALWAYS use backend endpoints

Before writing code:

* Analyze existing files
* Identify correct place
* Do NOT break UI

When modifying:

* Return FULL file
* Keep design unchanged

Goal:
Maintain a clean, scalable, production-ready system.

You are not here to experiment.
You are here to respect architecture and assist a team project.
