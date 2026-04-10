# Backend ATS Recrutement (FastAPI)

## Structure du projet

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py           # Point d'entrée FastAPI
│   ├── config.py         # Configuration (Pydantic Settings)
│   ├── database.py       # Connexion SQLAlchemy + get_db
│   ├── core/
│   │   ├── security.py   # Hash mot de passe, JWT
│   │   └── auth.py       # Dépendances get_entreprise_from_token, get_candidat_from_token
│   ├── models/           # Modèles SQLAlchemy (ORM)
│   │   ├── entreprise.py
│   │   ├── offre.py
│   │   ├── candidat.py
│   │   └── candidature.py
│   ├── schemas/          # Schémas Pydantic (validation)
│   │   ├── entreprise.py
│   │   ├── offre.py
│   │   ├── candidat.py
│   │   └── candidature.py
│   └── routers/
│       ├── auth_entreprise.py   # POST /api/auth/entreprise/inscription, /login
│       ├── auth_candidat.py    # POST /api/auth/candidat/inscription, /login
│       ├── offres.py           # CRUD offres + GET /api/offres/lien/{uuid}
│       └── candidatures.py     # POST candidature (upload CV), GET liste
├── requirements.txt
├── .env.example
└── README.md
```

## Installation

1. Créer la base MySQL et exécuter le schéma :
   ```bash
   mysql -u root -p < ../database/schema.sql
   ```

2. Créer un environnement virtuel et installer les dépendances :
   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```

3. Copier `.env.example` en `.env` et renseigner les variables (MySQL, SECRET_KEY).

4. Lancer l'API :
   ```bash
   uvicorn app.main:app --reload --app-dir .
   ```
   Depuis la racine du repo : `uvicorn app.main:app --reload --app-dir backend`

## Endpoints principaux

| Méthode | URL | Description |
|--------|-----|-------------|
| POST | `/api/auth/entreprise/inscription` | Inscription entreprise |
| POST | `/api/auth/entreprise/login` | Connexion entreprise |
| POST | `/api/auth/candidat/inscription` | Inscription candidat |
| POST | `/api/auth/candidat/login` | Connexion candidat |
| POST | `/api/offres` | Créer une offre (auth entreprise) → retourne `lien_uuid` |
| GET | `/api/offres` | Liste des offres de l'entreprise |
| GET | `/api/offres/dashboard/stats` | Stats (nombre de CV par offre) |
| GET | `/api/offres/lien/{lien_uuid}` | Infos offre pour le portail candidat (public) |
| POST | `/api/candidatures/offre/{lien_uuid}` | Soumettre candidature + CV (auth candidat) |
| GET | `/api/candidatures` | Liste des candidatures (auth entreprise) |

Documentation interactive : **http://localhost:8000/docs**
