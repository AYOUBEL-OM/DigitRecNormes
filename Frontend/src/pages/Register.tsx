import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useLoadingBar } from "../components/LoadingBarProvider";
import AuthShell from "../components/AuthShell";
import { getSession, registerCompany } from "../services/authService";
import { isValidEmail, isValidPassword, PASSWORD_MIN_LENGTH } from "@/lib/validation";

const RegisterCompany = () => {
  const navigate = useNavigate();
  const { startLoading } = useLoadingBar();

  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const submitGuardRef = useRef(false);

  useEffect(() => {
    let active = true;
    const stopLoading = startLoading();

    const checkSession = async () => {
      try {
        const sessionResult = await getSession();

        if (!active) return;

        if (sessionResult.data) {
          navigate("/dashboard", { replace: true });
        }
      } finally {
        stopLoading();
      }
    };

    checkSession();

    return () => {
      active = false;
      stopLoading();
    };
  }, [navigate, startLoading]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitGuardRef.current) return;
    submitGuardRef.current = true;

    setLoading(true);
    setMessage("");
    const stopLoading = startLoading();

    const nameTrim = companyName.trim();
    const emailTrim = email.trim();

    if (!nameTrim) {
      const err = "Veuillez indiquer le nom de l’entreprise.";
      setMessage(err);
      toast.error(err);
      setLoading(false);
      stopLoading();
      submitGuardRef.current = false;
      return;
    }
    if (!emailTrim) {
      const err = "Veuillez indiquer votre e-mail professionnel.";
      setMessage(err);
      toast.error(err);
      setLoading(false);
      stopLoading();
      submitGuardRef.current = false;
      return;
    }
    if (!isValidEmail(emailTrim)) {
      const err = "Veuillez saisir une adresse e-mail valide.";
      setMessage(err);
      toast.error(err);
      setLoading(false);
      stopLoading();
      submitGuardRef.current = false;
      return;
    }
    if (!isValidPassword(password)) {
      const err = `Le mot de passe doit contenir au moins ${PASSWORD_MIN_LENGTH} caractères.`;
      setMessage(err);
      toast.error(err);
      setLoading(false);
      stopLoading();
      submitGuardRef.current = false;
      return;
    }

    try {
      const result = await registerCompany({
        companyName: nameTrim,
        email: emailTrim,
        password,
      });

      if (result.error) {
        setMessage(result.error.message);
        toast.error("Inscription impossible", {
          description: result.error.message,
        });
        return;
      }

      toast.success("Compte créé", {
        description: "Vous pouvez maintenant vous connecter.",
      });
      navigate("/login", { replace: true });
    } catch {
      const err = "Une erreur inattendue s’est produite.";
      setMessage(err);
      toast.error(err);
    } finally {
      setLoading(false);
      stopLoading();
      submitGuardRef.current = false;
    }
  };

  return (
    <AuthShell
      eyebrow="Inscription entreprise"
      title="Créez votre accès entreprise."
      subtitle="Configurez votre espace entreprise et commencez à piloter votre recrutement."
      highlights={[
        "Créez rapidement un espace entreprise.",
        "Gérez vos offres et vos candidatures au même endroit.",
        "Commencez avec une interface claire et orientée recrutement.",
      ]}
      stats={[
        { label: "Type de compte", value: "Entreprise" },
        { label: "Expérience", value: "Simple" },
      ]}
      layout="card-only"
    >
      <div className="legacy-auth-card__badge">Inscription</div>
      <h2 className="legacy-auth-card__title">Créer votre accès entreprise</h2>
      <p className="legacy-auth-card__subtitle">
        Configurez votre compte entreprise et préparez votre espace de recrutement.
      </p>

      <form className="legacy-auth-form" onSubmit={handleSubmit}>
        <div className="legacy-auth-field">
          <label className="legacy-auth-label" htmlFor="test-register-company-name">
            Nom de l'entreprise
          </label>
          <input
            id="test-register-company-name"
            className="legacy-auth-input"
            autoComplete="organization"
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            placeholder="Atlas Recruitment"
          />
        </div>

        <div className="legacy-auth-field">
          <label className="legacy-auth-label" htmlFor="test-register-email">
            Email professionnel
          </label>
          <input
            id="test-register-email"
            className="legacy-auth-input"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="vous@exemple.com"
          />
        </div>

        <div className="legacy-auth-field">
          <label className="legacy-auth-label" htmlFor="test-register-password">
            Mot de passe
          </label>
          <input
            id="test-register-password"
            className="legacy-auth-input"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder={`Au moins ${PASSWORD_MIN_LENGTH} caractères`}
            minLength={PASSWORD_MIN_LENGTH}
          />
        </div>

        <button className="legacy-auth-submit" type="submit" disabled={loading}>
          {loading ? "Création..." : "Créer un compte entreprise"}
        </button>
      </form>

      {message ? (
        <div
          className={
            message.startsWith("Compte créé")
              ? "legacy-auth-message legacy-auth-message--info"
              : "legacy-auth-message legacy-auth-message--error"
          }
        >
          {message}
        </div>
      ) : null}

      <p className="legacy-auth-footer">
        Vous avez déjà un compte ?{" "}
        <Link className="legacy-auth-link" to="/login">
          Se connecter
        </Link>
      </p>
    </AuthShell>
  );
};

export default RegisterCompany;