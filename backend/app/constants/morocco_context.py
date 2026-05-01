"""
Paramètres centralisés — recrutement et contenus pédagogiques au Maroc.
Tous les services (quiz, oral, évaluation) doivent s’y référer pour cohérence devise / fiscalité.
"""

# ISO 3166-1 alpha-2
COUNTRY = "MA"

# Affichage usuel côté contenu candidat
CURRENCY_DISPLAY = "DH"
CURRENCY_ISO = "MAD"

# Fiscalité indicative (illustration pédagogique, pas conseil juridique)
DEFAULT_TVA = 0.20
DEFAULT_IS_RANGE = (0.20, 0.30)

# Plafond de normalisation des montants exprimés en DH/MAD dans les textes générés (ordre de grandeur PME / grand groupe)
MAX_DH_AMOUNT_NORMALIZED = 50_000_000
