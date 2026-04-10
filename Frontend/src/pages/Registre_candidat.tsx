import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useLoadingBar } from "../components/LoadingBarProvider";
import AuthShell from "../components/AuthShell";
import { apiFetch, clearAuthStorage } from "@/services/authService";
import {
  isValidEmail,
  isValidPassword,
  PASSWORD_MIN_LENGTH,
} from "@/lib/validation";

type PublicOffre = {
  id: string;
  title?: string;
  profile?: string;
  localisation?: string;
  type_contrat?: string;
  level?: string;
  description_postes?: string;
};

function candidatureSessionKey(token: string) {
  return `candidature_submitted_${token}`;
}

const RegisterCandidate = () => {
  const { startLoading } = useLoadingBar();
  const { token } = useParams();

  const [offre, setOffre] = useState<PublicOffre | null>(null);
  const [pageLoading, setPageLoading] = useState(true);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [cin, setCin] = useState("");
  const [title, setTitle] = useState("");
  const [profile, setProfile] = useState("");
  const [level, setLevel] = useState("");
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  /** True after success, or on load if sessionStorage says this token was already submitted (refresh). */
  const [flowCompleted, setFlowCompleted] = useState(false);
  /** Distinction: refresh revisit vs just finished in this session (wording). */
  const [completedFromSession, setCompletedFromSession] = useState(false);

  const submitGuardRef = useRef(false);

  useEffect(() => {
    if (!token) return;
    try {
      if (sessionStorage.getItem(candidatureSessionKey(token)) === "1") {
        setFlowCompleted(true);
        setCompletedFromSession(true);
      }
    } catch {
      /* sessionStorage may be unavailable */
    }
  }, [token]);

  useEffect(() => {
    let active = true;
    const stopLoading = startLoading();

    const loadOffre = async () => {
      try {
        if (!token) {
          setMessage("Lien de candidature invalide.");
          return;
        }

        const data = await apiFetch(`/api/offres/public/${token}`);

        if (!active) return;

        setOffre(data);

        setTitle((prev) => prev || data.title || "");
        setProfile((prev) => prev || data.profile || "");
        setLevel((prev) => prev || data.level || "");
      } catch {
        if (!active) return;
        setMessage("Impossible de charger les informations de l’offre.");
      } finally {
        if (active) setPageLoading(false);
        stopLoading();
      }
    };

    loadOffre();

    return () => {
      active = false;
      stopLoading();
    };
  }, [token, startLoading]);

  const resetFormState = () => {
    setFirstName("");
    setLastName("");
    setCin("");
    setTitle(offre?.title ?? "");
    setProfile(offre?.profile ?? "");
    setLevel(offre?.level ?? "");
    setCvFile(null);
    setFileInputKey((k) => k + 1);
    setEmail("");
    setPassword("");
  };

  const validateClient = (): string | null => {
    if (
      !firstName.trim() ||
      !lastName.trim() ||
      !cin.trim() ||
      !title.trim() ||
      !profile.trim() ||
      !level.trim() ||
      !email.trim() ||
      !password ||
      !cvFile
    ) {
      return "Veuillez remplir tous les champs obligatoires et joindre votre CV.";
    }
    if (!isValidEmail(email)) {
      return "Veuillez saisir une adresse e-mail valide.";
    }
    if (!isValidPassword(password)) {
      return `Le mot de passe doit contenir au moins ${PASSWORD_MIN_LENGTH} caractères.`;
    }
    return null;
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (flowCompleted) return;
    if (submitGuardRef.current) return;
    submitGuardRef.current = true;

    let didSucceed = false;

    setLoading(true);
    setMessage("");

    const stopLoading = startLoading();

    try {
      if (!token) {
        setMessage("Lien de candidature invalide.");
        toast.error("Lien de candidature invalide.");
        return;
      }

      const validationError = validateClient();
      if (validationError) {
        setMessage(validationError);
        toast.error(validationError);
        return;
      }

      const registerForm = new FormData();
      registerForm.append("email", email.trim());
      registerForm.append("nom", lastName.trim());
      registerForm.append("prenom", firstName.trim());
      registerForm.append("mot_de_passe", password);
      registerForm.append("cin", cin.trim());
      registerForm.append("title", title.trim());
      registerForm.append("profile", profile.trim());
      registerForm.append("level", level.trim());
      registerForm.append("cv", cvFile!);

      await apiFetch("/api/auth/candidat/inscription", {
        method: "POST",
        body: registerForm,
      });

      const loginData = await apiFetch("/api/auth/candidat/login", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(),
          mot_de_passe: password,
        }),
      });

      const accessToken = loginData.access_token;
      localStorage.setItem("access_token", accessToken);
      localStorage.setItem("user", JSON.stringify(loginData.user));

      const candidatureForm = new FormData();
      candidatureForm.append("cv", cvFile);

      await apiFetch(`/api/candidatures/offre/${token}`, {
        method: "POST",
        body: candidatureForm,
      });

      try {
        sessionStorage.setItem(candidatureSessionKey(token), "1");
      } catch {
        /* ignore */
      }

      clearAuthStorage();

      didSucceed = true;
      setFlowCompleted(true);
      setCompletedFromSession(false);
      setMessage("Votre candidature a été envoyée avec succès.");
      toast.success("Candidature envoyée", {
        description:
          "Votre CV est en cours d’analyse. Vous recevrez un retour prochainement.",
      });

      resetFormState();
    } catch (error: unknown) {
      const text =
        error instanceof Error ? error.message : "Une erreur est survenue.";
      const isDuplicate = /déjà soumis|déjà une candidature|already submitted/i.test(
        text
      );
      setMessage(
        isDuplicate
          ? "Vous avez déjà soumis une candidature pour cette offre."
          : "Une erreur est survenue. Merci de réessayer."
      );
      toast.error(
        isDuplicate ? "Candidature déjà enregistrée" : "Échec de l’envoi",
        {
          description: isDuplicate
            ? "Cette candidature a déjà été enregistrée pour cette offre."
            : text,
        }
      );
    } finally {
      setLoading(false);
      stopLoading();
      if (!didSucceed) {
        submitGuardRef.current = false;
      }
    }
  };

  const formDisabled = loading || flowCompleted;

  return (
    <AuthShell
      eyebrow="Candidature"
      title={offre?.title ? `Postuler à : ${offre.title}` : "Candidature"}
      subtitle={
        offre?.profile
          ? `Complétez votre inscription pour candidater à l’offre ${offre.profile}.`
          : "Créez votre compte candidat et envoyez votre CV."
      }
      highlights={[
        offre?.localisation
          ? `Localisation : ${offre.localisation}`
          : "Postulez rapidement à cette opportunité.",
        offre?.type_contrat
          ? `Type de contrat : ${offre.type_contrat}`
          : "Un parcours simple et fluide pour candidater.",
        offre?.level
          ? `Niveau recherché : ${offre.level}`
          : "Renseignez vos informations essentielles.",
      ]}
      stats={[
        { label: "Type de compte", value: "Candidat" },
        { label: "Offre", value: offre?.title || "Public" },
      ]}
      layout="card-only"
    >
      <div className="legacy-auth-card__badge">Postuler</div>
      <h2 className="legacy-auth-card__title">Créer votre accès candidat</h2>
      <p className="legacy-auth-card__subtitle">
        Renseignez vos informations, joignez votre CV et validez votre candidature.
      </p>

      {pageLoading ? (
        <div className="legacy-auth-message legacy-auth-message--info">
          Chargement de l’offre...
        </div>
      ) : null}

      {!pageLoading && !offre ? (
        <div className="legacy-auth-message legacy-auth-message--error">
          {message || "Offre introuvable."}
        </div>
      ) : null}

      {!pageLoading && offre && flowCompleted ? (
        <div className="legacy-auth-message legacy-auth-message--info space-y-2">
          <p className="font-semibold">
            {completedFromSession
              ? "Candidature déjà enregistrée"
              : "Candidature envoyée"}
          </p>
          <p className="text-sm opacity-90">
            {completedFromSession
              ? "Vous avez déjà soumis une candidature pour cette offre. Vous ne pouvez pas envoyer les mêmes données à nouveau."
              : message || "Merci — votre dossier a bien été transmis."}
          </p>
        </div>
      ) : null}

      {!pageLoading && offre && !flowCompleted ? (
        <>
          <div className="legacy-auth-message legacy-auth-message--info">
            <strong>{offre.title}</strong>
            {offre.profile ? ` • ${offre.profile}` : ""}
            {offre.localisation ? ` • ${offre.localisation}` : ""}
          </div>

          <div className="relative">
            {loading ? (
              <div
                className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-lg bg-background/80 px-4 py-8 text-center backdrop-blur-sm"
                role="status"
                aria-live="polite"
              >
                <div
                  className="h-10 w-10 animate-spin rounded-full border-2 border-muted-foreground border-t-primary"
                  aria-hidden
                />
                <p className="text-sm font-medium text-foreground">
                  Traitement de votre CV avec l’IA…
                </p>
                <p className="text-xs text-muted-foreground">
                  Merci de patienter pendant l’envoi et l’analyse en arrière-plan.
                </p>
              </div>
            ) : null}

            <form className="legacy-auth-form" onSubmit={handleSubmit}>
              <div className="legacy-auth-grid legacy-auth-grid--2">
                <div className="legacy-auth-field">
                  <label className="legacy-auth-label" htmlFor="candidate-first-name">
                    Prénom
                  </label>
                  <input
                    id="candidate-first-name"
                    className="legacy-auth-input"
                    autoComplete="given-name"
                    value={firstName}
                    onChange={(event) => setFirstName(event.target.value)}
                    placeholder="Salma"
                    disabled={formDisabled}
                    required
                  />
                </div>

                <div className="legacy-auth-field">
                  <label className="legacy-auth-label" htmlFor="candidate-last-name">
                    Nom
                  </label>
                  <input
                    id="candidate-last-name"
                    className="legacy-auth-input"
                    autoComplete="family-name"
                    value={lastName}
                    onChange={(event) => setLastName(event.target.value)}
                    placeholder="Idrissi"
                    disabled={formDisabled}
                    required
                  />
                </div>
              </div>

              <div className="legacy-auth-grid legacy-auth-grid--2">
                <div className="legacy-auth-field">
                  <label className="legacy-auth-label" htmlFor="candidate-cin">
                    CIN
                  </label>
                  <input
                    id="candidate-cin"
                    className="legacy-auth-input"
                    value={cin}
                    onChange={(event) => setCin(event.target.value)}
                    placeholder="AB123456"
                    disabled={formDisabled}
                    required
                  />
                </div>

                <div className="legacy-auth-field">
                  <label className="legacy-auth-label" htmlFor="candidate-level">
                    Niveau
                  </label>
                  <input
                    id="candidate-level"
                    className="legacy-auth-input"
                    value={level}
                    onChange={(event) => setLevel(event.target.value)}
                    placeholder="Junior, Confirmé, Senior..."
                    disabled={formDisabled}
                    required
                  />
                </div>
              </div>

              <div className="legacy-auth-field">
                <label className="legacy-auth-label" htmlFor="candidate-title">
                  Intitulé
                </label>
                <input
                  id="candidate-title"
                  className="legacy-auth-input"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="Développeur Frontend"
                  disabled={formDisabled}
                  required
                />
              </div>

              <div className="legacy-auth-field">
                <label className="legacy-auth-label" htmlFor="candidate-profile">
                  Profil
                </label>
                <input
                  id="candidate-profile"
                  className="legacy-auth-input"
                  value={profile}
                  onChange={(event) => setProfile(event.target.value)}
                  placeholder="React, design systems, tests..."
                  disabled={formDisabled}
                  required
                />
              </div>

              <div className="legacy-auth-field">
                <label className="legacy-auth-label" htmlFor="candidate-cv-file">
                  CV
                </label>
                <input
                  key={fileInputKey}
                  id="candidate-cv-file"
                  className="legacy-auth-input"
                  type="file"
                  accept=".pdf,.doc,.docx"
                  disabled={formDisabled}
                  onChange={(event) => setCvFile(event.target.files?.[0] ?? null)}
                  required
                />
                <span className="legacy-auth-helper">
                  {cvFile
                    ? `Fichier sélectionné : ${cvFile.name}`
                    : "Ajoutez un CV en PDF, DOC ou DOCX."}
                </span>
              </div>

              <div className="legacy-auth-field">
                <label className="legacy-auth-label" htmlFor="candidate-email">
                  Email
                </label>
                <input
                  id="candidate-email"
                  className="legacy-auth-input"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="vous@exemple.com"
                  disabled={formDisabled}
                  required
                />
              </div>

              <div className="legacy-auth-field">
                <label className="legacy-auth-label" htmlFor="candidate-password">
                  Mot de passe
                </label>
                <input
                  id="candidate-password"
                  className="legacy-auth-input"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={`Au moins ${PASSWORD_MIN_LENGTH} caractères`}
                  disabled={formDisabled}
                  required
                  minLength={PASSWORD_MIN_LENGTH}
                />
              </div>

              <button
                className="legacy-auth-submit"
                type="submit"
                disabled={formDisabled}
              >
                {loading ? "Envoi…" : "Créer un compte et postuler"}
              </button>
            </form>
          </div>

          {message ? (
            <div className="legacy-auth-message legacy-auth-message--error">
              {message}
            </div>
          ) : null}

          <p className="legacy-auth-footer">
            Vous avez déjà un compte ?{" "}
            <Link className="legacy-auth-link" to="/login">
              Se connecter
            </Link>
          </p>
        </>
      ) : null}
    </AuthShell>
  );
};

export default RegisterCandidate;
