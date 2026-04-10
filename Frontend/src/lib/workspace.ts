import { AccountType } from "../hooks/useAccount";

export type WorkspaceNavItem = {
  label: string;
  pageTitle: string;
  subtitle: string;
  to: string;
};

export type Metric = {
  label: string;
  value: string;
  tone?: "sky" | "emerald" | "amber" | "violet";
};

export const sharedWorkspaceLinks: WorkspaceNavItem[] = [
  {
    label: "Tableau de bord",
    pageTitle: "Tableau de bord",
    subtitle: "Vue d'ensemble",
    to: "/dashboard",
  },
  {
    label: "Profil",
    pageTitle: "Profil",
    subtitle: "Informations personnelles",
    to: "/dashboard/profile",
  },
];

export const candidateWorkspaceLinks: WorkspaceNavItem[] = [
  {
    label: "Offres",
    pageTitle: "Offres",
    subtitle: "Offres disponibles",
    to: "/dashboard/offers",
  },
  {
    label: "Mes candidatures",
    pageTitle: "Mes candidatures",
    subtitle: "Suivi des candidatures",
    to: "/dashboard/applications",
  },
];

export const companyWorkspaceLinks: WorkspaceNavItem[] = [
  {
    label: "Mes offres",
    pageTitle: "Mes offres",
    subtitle: "Gestion des offres",
    to: "/dashboard/offers",
  },
];

export const candidateOffers = [
  {
    id: "offer-1",
    title: "Frontend React Engineer",
    company: "Atlas Systems",
    department: "Engineering",
    level: "Confirmé",
    examType: "Mixte",
    experience: "3 ans et plus",
    closeDate: "2026-04-11",
    status: "Active",
  },
  {
    id: "offer-2",
    title: "Data Analyst",
    company: "Northwind Labs",
    department: "Data",
    level: "Junior",
    examType: "QCM",
    experience: "1 an et plus",
    closeDate: "2026-04-08",
    status: "Active",
  },
  {
    id: "offer-3",
    title: "Product Designer",
    company: "Signal Forge",
    department: "Design",
    level: "Intermédiaire",
    examType: "Exercice",
    experience: "2 ans et plus",
    closeDate: "2026-04-18",
    status: "Clôture proche",
  },
];

export const candidateApplications = [
  {
    id: "app-1",
    offerTitle: "Frontend React Engineer",
    company: "Atlas Systems",
    stage: "Écrit",
    score: "84%",
    summary: "Votre dossier a été retenu et l'évaluation écrite constitue la prochaine étape.",
    submittedAt: "2026-03-22",
  },
  {
    id: "app-2",
    offerTitle: "Data Analyst",
    company: "Northwind Labs",
    stage: "CV_Screening",
    score: "72%",
    summary: "Votre candidature est en cours de revue par l'équipe de recrutement.",
    submittedAt: "2026-03-27",
  },
  {
    id: "app-3",
    offerTitle: "Product Designer",
    company: "Signal Forge",
    stage: "Oral",
    score: "89%",
    summary: "Votre dossier avance bien et la prochaine étape prévue est l'entretien oral.",
    submittedAt: "2026-03-18",
  },
];

export const candidateWrittenTests = [
  {
    id: "written-1",
    candidature: "Frontend React Engineer",
    score: "17 / 20",
    status: "Réussi",
    takenAt: "2026-03-24",
    details: "Le test écrit a été validé avec un bon niveau de maîtrise sur les fondamentaux demandés.",
  },
  {
    id: "written-2",
    candidature: "Data Analyst",
    score: "En attente",
    status: "Planifié",
    takenAt: "2026-04-02",
    details: "Le test écrit est programmé et apparaîtra ici dès qu'il sera disponible.",
  },
];

export const candidateOralTests = [
  {
    id: "oral-1",
    candidature: "Product Designer",
    question: "Présentez une décision importante que vous avez défendue lors d'un projet récent.",
    score: "4.4 / 5",
    sentiment: "Assuré",
    languageLevel: "Avancé",
    takenAt: "2026-03-29",
    flags: "Aucun signal particulier",
  },
  {
    id: "oral-2",
    candidature: "Frontend React Engineer",
    question: "Expliquez comment vous amélioreriez l'expérience d'un tableau de bord complexe.",
    score: "À venir",
    sentiment: "Non évalué",
    languageLevel: "En attente",
    takenAt: "2026-04-03",
    flags: "Session non commencée",
  },
];

export const companyOffers = [
  {
    id: "company-offer-1",
    title: "Frontend React Engineer",
    department: "Engineering",
    level: "Confirmé",
    candidates: 18,
    examType: "Mixte",
    status: "Active",
  },
  {
    id: "company-offer-2",
    title: "QA Automation Specialist",
    department: "Platform",
    level: "Intermédiaire",
    candidates: 11,
    examType: "QCM",
    status: "Brouillon",
  },
  {
    id: "company-offer-3",
    title: "Talent Operations Partner",
    department: "People",
    level: "Senior",
    candidates: 7,
    examType: "Oral",
    status: "Active",
  },
];

export const companyCandidates = [
  {
    id: "cand-1",
    name: "Salma Idrissi",
    title: "Frontend React Engineer",
    stage: "Entretien final",
    fit: "94%",
    note: "Le profil est bien avancé dans le processus et présente un excellent alignement avec le poste.",
  },
  {
    id: "cand-2",
    name: "Youssef Belkadi",
    title: "QA Automation Specialist",
    stage: "Écrit",
    fit: "81%",
    note: "Le candidat avance régulièrement et attend la validation de l'épreuve écrite.",
  },
  {
    id: "cand-3",
    name: "Meriem Ait Lahcen",
    title: "Talent Operations Partner",
    stage: "CV_Screening",
    fit: "76%",
    note: "Le dossier est prometteur et poursuit actuellement l'étape de présélection.",
  },
];

export function formatAccountType(value: AccountType) {
  if (value === "candidate") return "Candidat";
  if (value === "company") return "Entreprise";
  return "Compte";
}

export function getWorkspaceLinks(accountType: AccountType) {
  if (accountType === "candidate") {
    return [...sharedWorkspaceLinks, ...candidateWorkspaceLinks];
  }

  if (accountType === "company") {
    return [...sharedWorkspaceLinks, ...companyWorkspaceLinks];
  }

  return sharedWorkspaceLinks;
}

export function getPageMeta(pathname: string, accountType: AccountType) {
  const links = getWorkspaceLinks(accountType);
  const match = links.find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`));

  if (match) {
    return {
      eyebrow: match.subtitle,
      title: match.pageTitle,
    };
  }

  return {
    eyebrow: "DigitRec",
    title: "Compte",
  };
}

export function getDashboardMetrics(accountType: AccountType): Metric[] {
  if (accountType === "candidate") {
    return [
      { label: "Candidatures actives", value: String(candidateApplications.length), tone: "sky" },
      { label: "Offres ouvertes", value: String(candidateOffers.length), tone: "emerald" },
      { label: "Tests écrits", value: String(candidateWrittenTests.length), tone: "amber" },
      { label: "Tests oraux", value: String(candidateOralTests.length), tone: "violet" },
    ];
  }

  if (accountType === "company") {
    return [
      { label: "Offres ouvertes", value: String(companyOffers.length), tone: "sky" },
      { label: "Candidats suivis", value: String(companyCandidates.length), tone: "emerald" },
      { label: "Évaluations actives", value: "9", tone: "amber" },
      { label: "Étapes finales", value: "2", tone: "violet" },
    ];
  }

  return [
    { label: "Pages principales", value: "2", tone: "sky" },
    { label: "Navigation", value: "Active", tone: "emerald" },
    { label: "Accès", value: "Ouvert", tone: "amber" },
    { label: "Compte", value: "DigitRec", tone: "violet" },
  ];
}
