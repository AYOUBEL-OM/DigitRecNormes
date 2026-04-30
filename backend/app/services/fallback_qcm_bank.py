"""
Banque QCM de repli (comptabilité / fiscalité marocaine) lorsque la génération IA échoue.
Retourne toujours 35 questions distinctes, format identique au flux IA (question, options, answer).
"""
from __future__ import annotations

import copy
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

# Banque ≥ 40 questions, textes uniques (pas de doublons).
_FALLBACK_QCM_BANK: list[dict[str, Any]] = [
    {
        "question": "Au Maroc, le taux normal de TVA le plus courant pour les biens et services est :",
        "options": ["10 %", "14 %", "20 %", "7 %"],
        "answer": "20 %",
    },
    {
        "question": "La TVA collectée sur les ventes est enregistrée au compte :",
        "options": [
            "4455 État — TVA due",
            "4456 TVA déductible",
            "4457 TVA collectée",
            "658 Charges diverses",
        ],
        "answer": "4457 TVA collectée",
    },
    {
        "question": "La TVA déductible sur achats est en principe :",
        "options": [
            "Une charge immédiate du résultat",
            "Une créance ou un compte d’actif récupérable sur la TVA due",
            "Un produit d’exploitation",
            "Un dividende",
        ],
        "answer": "Une créance ou un compte d’actif récupérable sur la TVA due",
    },
    {
        "question": "L’impôt sur les sociétés (IS) au Maroc concerne principalement :",
        "options": [
            "Les salariés uniquement",
            "Les bénéfices réalisés par les sociétés soumises à l’IS",
            "Uniquement la TVA",
            "Les ventes à l’exportation seulement",
        ],
        "answer": "Les bénéfices réalisés par les sociétés soumises à l’IS",
    },
    {
        "question": "Un journal comptable sert à :",
        "options": [
            "Enregistrer chronologiquement les opérations par nature (achats, ventes, OD, etc.)",
            "Remplacer le bilan",
            "Calculer uniquement la paie",
            "Archiver uniquement les contrats commerciaux",
        ],
        "answer": "Enregistrer chronologiquement les opérations par nature (achats, ventes, OD, etc.)",
    },
    {
        "question": "Le grand livre permet de :",
        "options": [
            "Regrouper tous les mouvements par compte",
            "Lister uniquement les clients",
            "Remplacer la déclaration de TVA",
            "Gérer le stock physique des marchandises",
        ],
        "answer": "Regrouper tous les mouvements par compte",
    },
    {
        "question": "Le bilan présente :",
        "options": [
            "Le détail des ventes du mois uniquement",
            "La situation patrimoniale (actif, passif) à une date donnée",
            "Uniquement la trésorerie de fin de journée",
            "Les salaires bruts de l’exercice",
        ],
        "answer": "La situation patrimoniale (actif, passif) à une date donnée",
    },
    {
        "question": "Le compte de résultat synthétise :",
        "options": [
            "Charges et produits sur une période",
            "Uniquement l’actif immobilisé",
            "Les flux de trésorerie détaillés jour par jour",
            "Le registre des factures fournisseurs uniquement",
        ],
        "answer": "Charges et produits sur une période",
    },
    {
        "question": "Une facture client doit en principe mentionner :",
        "options": [
            "Uniquement le montant TTC sans détail TVA",
            "Les mentions légales usuelles, montants HT/TVA/TTC selon le cas",
            "Le salaire du vendeur",
            "Le numéro de chèque du client",
        ],
        "answer": "Les mentions légales usuelles, montants HT/TVA/TTC selon le cas",
    },
    {
        "question": "Le rapprochement bancaire consiste à :",
        "options": [
            "Comparer les écritures comptables de banque avec le relevé bancaire",
            "Annuler toutes les écritures du mois",
            "Payer uniquement les fournisseurs étrangers",
            "Clôturer l’exercice sans contrôle",
        ],
        "answer": "Comparer les écritures comptables de banque avec le relevé bancaire",
    },
    {
        "question": "Une charge comptable :",
        "options": [
            "Augmente le résultat",
            "Diminue le résultat",
            "Est toujours une dette fournisseur",
            "Ne s’enregistre jamais au journal",
        ],
        "answer": "Diminue le résultat",
    },
    {
        "question": "Un produit comptable :",
        "options": [
            "Diminue le résultat",
            "Augmente le résultat",
            "Est toujours une immobilisation",
            "Correspond uniquement à un emprunt",
        ],
        "answer": "Augmente le résultat",
    },
    {
        "question": "La trésorerie d’une entreprise reflète surtout :",
        "options": [
            "Le stock de marchandises évalué au coût standard",
            "Les disponibilités et flux de liquidités (banque, caisse)",
            "Uniquement les créances douteuses",
            "Les provisions pour risques sans paiement",
        ],
        "answer": "Les disponibilités et flux de liquidités (banque, caisse)",
    },
    {
        "question": "Un avoir (note de crédit) client sert souvent à :",
        "options": [
            "Augmenter la créance client",
            "Corriger ou annuler partiellement une facture de vente",
            "Enregistrer un dividende",
            "Constater une immobilisation",
        ],
        "answer": "Corriger ou annuler partiellement une facture de vente",
    },
    {
        "question": "Les écritures d’inventaire en fin d’exercice visent notamment à :",
        "options": [
            "Ajuster stocks, provisions, régularisations",
            "Supprimer le journal des ventes",
            "Payer l’IS sans déclaration",
            "Éliminer la tenue de livres",
        ],
        "answer": "Ajuster stocks, provisions, régularisations",
    },
    {
        "question": "Le compte « fournisseurs » est en général :",
        "options": [
            "Un compte de charges",
            "Un compte de passif (dettes)",
            "Un compte de produits",
            "Un compte d’immobilisation incorporelle",
        ],
        "answer": "Un compte de passif (dettes)",
    },
    {
        "question": "Le compte « clients » est en général :",
        "options": [
            "Un compte d’actif (créances)",
            "Un compte de TVA collectée",
            "Un compte de capitaux propres uniquement",
            "Un compte de trésorerie négative",
        ],
        "answer": "Un compte d’actif (créances)",
    },
    {
        "question": "Une immobilisation est :",
        "options": [
            "Une charge consommée immédiatement",
            "Un actif durable utilisé sur plusieurs exercices",
            "Une dette fournisseur à 30 jours",
            "Un produit financier exceptionnel",
        ],
        "answer": "Un actif durable utilisé sur plusieurs exercices",
    },
    {
        "question": "Les dotations aux amortissements :",
        "options": [
            "Augmentent la valeur brute de l’immobilisation",
            "Répartissent le coût d’une immobilisation sur sa durée d’utilité",
            "Sont enregistrées uniquement à la clôture sans impact résultat",
            "Remplacent la TVA",
        ],
        "answer": "Répartissent le coût d’une immobilisation sur sa durée d’utilité",
    },
    {
        "question": "Une écriture équilibrée respecte :",
        "options": [
            "Total débit = total crédit",
            "Total débit = 0 uniquement",
            "Un seul compte par ligne",
            "Aucune pièce justificative",
        ],
        "answer": "Total débit = total crédit",
    },
    {
        "question": "Le livre-journal des achats enregistre :",
        "options": [
            "Les opérations d’achat (factures fournisseurs, etc.)",
            "Uniquement les ventes au comptant",
            "Les bulletins de paie",
            "Les statuts de la société",
        ],
        "answer": "Les opérations d’achat (factures fournisseurs, etc.)",
    },
    {
        "question": "Le décalage entre résultat comptable et trésorerie peut s’expliquer par :",
        "options": [
            "Les ventes à crédit et les décalages de paiement",
            "L’absence de journal",
            "La TVA toujours nulle",
            "L’interdiction des provisions",
        ],
        "answer": "Les ventes à crédit et les décalages de paiement",
    },
    {
        "question": "Une provision pour risques et charges :",
        "options": [
            "Réduit le résultat et enregistre une dette/provision",
            "Augmente toujours la trésorerie",
            "Est une recette",
            "Ne nécessite aucune justification",
        ],
        "answer": "Réduit le résultat et enregistre une dette/provision",
    },
    {
        "question": "Les stocks en fin de période sont en général :",
        "options": [
            "Évalués et comparés aux sorties pour déterminer le coût des ventes",
            "Ignorés en comptabilité analytique",
            "Réservés aux grandes entreprises cotées uniquement",
            "Identiques au chiffre d’affaires",
        ],
        "answer": "Évalués et comparés aux sorties pour déterminer le coût des ventes",
    },
    {
        "question": "Un état des ventes permet surtout de :",
        "options": [
            "Contrôler CA, TVA collectée et créances clients",
            "Remplacer le plan comptable",
            "Calculer uniquement l’IS sans compta",
            "Archiver les CV des candidats",
        ],
        "answer": "Contrôler CA, TVA collectée et créances clients",
    },
    {
        "question": "La marge commerciale sur marchandises se rapproche conceptuellement de :",
        "options": [
            "CA ventes de marchandises − coût d’achat des marchandises vendues",
            "Salaires + charges sociales",
            "Capitaux propres − dettes",
            "TVA collectée + TVA déductible",
        ],
        "answer": "CA ventes de marchandises − coût d’achat des marchandises vendues",
    },
    {
        "question": "Un lettrage de compte permet :",
        "options": [
            "Rapprocher les règlements et les factures pour soldes cohérents",
            "Supprimer les écritures validées",
            "Éviter la déclaration fiscale",
            "Convertir les DH en devise sans cours",
        ],
        "answer": "Rapprocher les règlements et les factures pour soldes cohérents",
    },
    {
        "question": "Une opération diverse (OD) sert souvent à :",
        "options": [
            "Enregistrer des régularisations sans passer par achats/ventes",
            "Remplacer la facture",
            "Payer uniquement en espèces",
            "Annuler la comptabilité",
        ],
        "answer": "Enregistrer des régularisations sans passer par achats/ventes",
    },
    {
        "question": "Le tableau de flux de trésorerie vise à expliquer :",
        "options": [
            "Les variations de trésorerie sur une période",
            "Uniquement le stock final",
            "Les immobilisations brutes sans amortissement",
            "Les salaires nets sans charges",
        ],
        "answer": "Les variations de trésorerie sur une période",
    },
    {
        "question": "Une créance client douteuse peut conduire à :",
        "options": [
            "Constater une dépréciation ou une perte sur créance",
            "Augmenter mécaniquement le CA",
            "Supprimer la facture sans trace",
            "Éliminer la TVA due",
        ],
        "answer": "Constater une dépréciation ou une perte sur créance",
    },
    {
        "question": "Les capitaux propres au bilan regroupent notamment :",
        "options": [
            "Capital, réserves, résultat reporté / résultat de l’exercice",
            "Uniquement les dettes fournisseurs",
            "La TVA déductible",
            "Les ventes TTC du mois",
        ],
        "answer": "Capital, réserves, résultat reporté / résultat de l’exercice",
    },
    {
        "question": "Une dette fournisseur à payer dans moins d’un an est classée en général :",
        "options": [
            "Au passif courant",
            "En immobilisation incorporelle",
            "En produit exceptionnel",
            "En capitaux propres",
        ],
        "answer": "Au passif courant",
    },
    {
        "question": "Le compte de résultat « par nature » ou « par fonction » reste :",
        "options": [
            "Un document de synthèse des performances de l’exercice",
            "Un relevé bancaire",
            "Un registre des immobilisations uniquement",
            "Une liasse fiscale sans lien comptable",
        ],
        "answer": "Un document de synthèse des performances de l’exercice",
    },
    {
        "question": "En gestion des factures fournisseurs, la bonne pratique inclut :",
        "options": [
            "Numérotation, contrôle TVA, rapprochement avec commandes et paiements",
            "Destruction des pièces après saisie",
            "Paiement sans validation interne systématique",
            "Ignorer les avoirs",
        ],
        "answer": "Numérotation, contrôle TVA, rapprochement avec commandes et paiements",
    },
    {
        "question": "Le seuil de signification d’une erreur en révision interne dépend souvent :",
        "options": [
            "Du contexte, du matérialité et du risque",
            "Uniquement du montant rond en milliers de DH",
            "Du nombre de lignes du journal sans analyse",
            "De la couleur du logiciel comptable",
        ],
        "answer": "Du contexte, du matérialité et du risque",
    },
    {
        "question": "Une subvention d’investissement peut être :",
        "options": [
            "Étalée au résultat selon les règles applicables à la subvention",
            "Comptabilisée uniquement en charge",
            "Ignorée si reçue en espèces",
            "Rattachée uniquement à la TVA",
        ],
        "answer": "Étalée au résultat selon les règles applicables à la subvention",
    },
    {
        "question": "Le cycle d’exploitation relie typiquement :",
        "options": [
            "Achats/stocks → ventes → encaissements clients / décaissements fournisseurs",
            "Uniquement les dividendes",
            "Les immobilisations sans amortissement",
            "La paie sans charges sociales",
        ],
        "answer": "Achats/stocks → ventes → encaissements clients / décaissements fournisseurs",
    },
    {
        "question": "Un report à nouveau créditeur peut provenir de :",
        "options": [
            "Bénéfice non distribué reporté",
            "TVA déductible uniquement",
            "Une erreur de pointage bancaire seule",
            "Une vente annulée sans écriture",
        ],
        "answer": "Bénéfice non distribué reporté",
    },
    {
        "question": "La comptabilité d’engagement enregistre les opérations :",
        "options": [
            "Lorsqu’elles sont réalisées, indépendamment des encaissements",
            "Uniquement au moment du paiement bancaire",
            "Sans pièces justificatives",
            "Seulement en fin de siècle",
        ],
        "answer": "Lorsqu’elles sont réalisées, indépendamment des encaissements",
    },
    {
        "question": "Un écart de conversion sur créance en devises peut nécessiter :",
        "options": [
            "Une évaluation à la clôture et une perte ou un gain de change",
            "L’annulation de la vente",
            "Une immobilisation supplémentaire",
            "Une augmentation de capital obligatoire",
        ],
        "answer": "Une évaluation à la clôture et une perte ou un gain de change",
    },
    {
        "question": "Les honoraires d’expert-comptable sont en général :",
        "options": [
            "Une charge de services extérieurs",
            "Un produit financier",
            "Une immobilisation financière",
            "Une dette fiscale spécifique IS",
        ],
        "answer": "Une charge de services extérieurs",
    },
    {
        "question": "La clôture d’exercice comptable permet :",
        "options": [
            "Arrêter les comptes, constater le résultat et préparer les états financiers",
            "Supprimer l’historique des écritures",
            "Éviter la conservation des pièces",
            "Remplacer la déclaration TVA",
        ],
        "answer": "Arrêter les comptes, constater le résultat et préparer les états financiers",
    },
    {
        "question": "Un bilan fonctionnel réorganise souvent l’information en :",
        "options": [
            "Fonds de roulement, besoin en fonds de roulement, trésorerie nette",
            "Uniquement TVA et IS",
            "Liste des clients sans montants",
            "Journal des ventes uniquement",
        ],
        "answer": "Fonds de roulement, besoin en fonds de roulement, trésorerie nette",
    },
    {
        "question": "La marge sur coût variable est utile pour :",
        "options": [
            "Analyser la couverture des charges fixes et le seuil de rentabilité",
            "Calculer uniquement l’IS",
            "Rédiger le contrat de travail",
            "Déterminer le capital social minimum",
        ],
        "answer": "Analyser la couverture des charges fixes et le seuil de rentabilité",
    },
    {
        "question": "Une participation des salariés aux résultats peut être :",
        "options": [
            "Une charge rémunérant le personnel selon les dispositifs applicables",
            "Une immobilisation corporelle",
            "Un produit d’exploitation brut",
            "Une dette fournisseur fournie par la banque centrale",
        ],
        "answer": "Une charge rémunérant le personnel selon les dispositifs applicables",
    },
    {
        "question": "Le principe de prudence conduit souvent à :",
        "options": [
            "Constater les pertes probables et éviter d’anticiper les profits incertains",
            "Surévaluer systématiquement les stocks",
            "Ignorer les provisions",
            "Comptabiliser tous les gains futurs hypothétiques",
        ],
        "answer": "Constater les pertes probables et éviter d’anticiper les profits incertains",
    },
    {
        "question": "Un état des retenues sur paiements fournisseurs vise à :",
        "options": [
            "Tracer les retenues à la source et leur régularisation",
            "Remplacer la balance générale",
            "Calculer la marge brute sans achats",
            "Supprimer la comptabilité fournisseurs",
        ],
        "answer": "Tracer les retenues à la source et leur régularisation",
    },
    {
        "question": "La distinction charges/produits exceptionnels sert à :",
        "options": [
            "Isoler des éléments non récurrents du résultat courant",
            "Fusionner TVA et IS",
            "Ignorer le résultat d’exploitation",
            "Annuler les amortissements",
        ],
        "answer": "Isoler des éléments non récurrents du résultat courant",
    },
    {
        "question": "Un compte d’attente doit être :",
        "options": [
            "Soldé rapidement après identification de la nature réelle de l’opération",
            "Laissé ouvert indéfiniment sans contrôle",
            "Utilisé uniquement pour les dividendes",
            "Réservé aux immobilisations en cours sans suivi",
        ],
        "answer": "Soldé rapidement après identification de la nature réelle de l’opération",
    },
    {
        "question": "La balance générale est :",
        "options": [
            "La liste des comptes avec totaux débit/crédit et soldes",
            "Uniquement le relevé bancaire du dernier jour",
            "Le registre des immobilisations sans montants",
            "Une déclaration TVA simplifiée obligatoire",
        ],
        "answer": "La liste des comptes avec totaux débit/crédit et soldes",
    },
    {
        "question": "Une ristourne commerciale accordée après facturation peut être :",
        "options": [
            "Enregistrée comme réduction du chiffre d’affaires ou via avoir",
            "Ignorée si le client paie en retard",
            "Comptabilisée uniquement en immobilisation",
            "Traitée comme produit financier",
        ],
        "answer": "Enregistrée comme réduction du chiffre d’affaires ou via avoir",
    },
    {
        "question": "Le coût d’achat des marchandises vendues inclut typiquement :",
        "options": [
            "Stock initial + achats − stock final (simplifié)",
            "Uniquement les salaires",
            "Uniquement la TVA collectée",
            "Les capitaux propres",
        ],
        "answer": "Stock initial + achats − stock final (simplifié)",
    },
]


def _validate_bank() -> None:
    keys: set[str] = set()
    for i, item in enumerate(_FALLBACK_QCM_BANK):
        q = str(item.get("question") or "").strip()
        opts = item.get("options")
        ans = item.get("answer")
        if not q or not isinstance(opts, list) or len(opts) != 4 or ans not in opts:
            raise ValueError(f"fallback QCM bank invalid at index {i}")
        k = q.lower()
        if k in keys:
            raise ValueError(f"duplicate question in fallback bank: {q[:60]}")
        keys.add(k)


_validate_bank()

FALLBACK_QCM_BANK_SIZE = len(_FALLBACK_QCM_BANK)


def _dedupe_bank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        q = str(it.get("question") or "").strip()
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(copy.deepcopy(it))
    return out


def _extend_with_variations(base: list[dict[str, Any]], need: int) -> list[dict[str, Any]]:
    """Si la banque est trop petite, duplique avec variation de libellé (texte jamais identique)."""
    out = list(base)
    n = 0
    wave = 1
    while len(out) < need:
        src = base[n % len(base)]
        n += 1
        dup = copy.deepcopy(src)
        dup["question"] = f"{src['question']} (variante contexte {wave})"
        # Varier légèrement une option incorrecte pour garder 4 choix distincts et answer valide
        opts = list(dup["options"])
        ans = dup["answer"]
        for i, o in enumerate(opts):
            if o != ans and i < len(opts):
                opts[i] = f"{o} — cas PME {wave}"
                break
        dup["options"] = opts
        dup["answer"] = ans
        key = dup["question"].strip().lower()
        if key not in {x["question"].strip().lower() for x in out}:
            out.append(dup)
        wave += 1
        if wave > 5000:
            raise RuntimeError("fallback QCM: impossible to extend bank")
    return out


def generate_fallback_questions(count: int = 35) -> list[dict[str, Any]]:
    """
    Mélange la banque, garantit des questions uniques, retourne exactement ``count`` items.
    """
    pool = _dedupe_bank(list(_FALLBACK_QCM_BANK))
    if len(pool) < count:
        pool = _extend_with_variations(pool, count)
    rng = random.Random()
    rng.shuffle(pool)
    chosen: list[dict[str, Any]] = []
    seen_q: set[str] = set()
    for it in pool:
        qk = str(it.get("question") or "").strip().lower()
        if qk in seen_q:
            continue
        seen_q.add(qk)
        chosen.append(copy.deepcopy(it))
        if len(chosen) >= count:
            break
    if len(chosen) < count:
        pool2 = _extend_with_variations(chosen, count)
        rng.shuffle(pool2)
        seen_q = {str(x.get("question") or "").strip().lower() for x in chosen}
        for it in pool2:
            qk = str(it.get("question") or "").strip().lower()
            if qk in seen_q:
                continue
            seen_q.add(qk)
            chosen.append(copy.deepcopy(it))
            if len(chosen) >= count:
                break
    if len(chosen) != count:
        raise RuntimeError(f"fallback QCM: expected {count} questions, got {len(chosen)}")
    return chosen


def build_qcm_fallback_payload(quiz_type: str, title: str) -> dict[str, Any]:
    """Payload GET /generate en cas d’échec IA (QCM uniquement)."""
    questions = generate_fallback_questions(35)
    print("FALLBACK USED — GENERATED 35 QUESTIONS", flush=True)
    logger.warning("FALLBACK USED — GENERATED 35 QUESTIONS (count=%s, bank_size=%s)", len(questions), FALLBACK_QCM_BANK_SIZE)
    return {
        "quiz_type": quiz_type,
        "title": title,
        "questions": questions,
    }


# Repli exercice (même endpoint) — format JSON attendu par le frontend, distinct du QCM.
_EXERCICE_FALLBACK_BODY: dict[str, Any] = {
    "title": "Exercice — comptabilité de base (repli)",
    "description": (
        "Une PME marocaine achète des marchandises pour 120 000 DH HT (TVA 20 %). "
        "50 % est payé par virement bancaire, le solde est dû à 60 jours. "
        "Rédigez les écritures comptables d’achat et de paiement partiel au journal, "
        "en précisant les comptes usuels (fournisseurs, banque, TVA déductible, charges/marchandises). "
        "Montants en DH."
    ),
    "initial_code": "// Votre réponse (écritures ou pseudo-code) ici",
}


def build_exercice_fallback_payload(quiz_type: str, title: str) -> dict[str, Any]:
    print("FALLBACK USED — GENERATED EXERCICE (static)", flush=True)
    logger.warning("FALLBACK USED — GENERATED EXERCICE (static) title=%s", title)
    return {
        "quiz_type": quiz_type,
        "title": title,
        "EXERCICE": copy.deepcopy(_EXERCICE_FALLBACK_BODY),
    }
