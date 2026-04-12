import { FormEvent, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useLoadingBar } from "../components/LoadingBarProvider";
import AuthShell from "../components/AuthShell";
import { signInWithPassword } from "../services/authService";
import { isValidEmail } from "@/lib/validation";

const LoginCompany = () => {
  const navigate = useNavigate();
  const { startLoading } = useLoadingBar();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const submitGuardRef = useRef(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitGuardRef.current) return;
    submitGuardRef.current = true;

    setLoading(true);
    setMessage("");
    const stopLoading = startLoading();

    // Valeurs lues sur le formulaire au moment du submit (évite décalage React / gestionnaire de mots de passe).
    const form = event.currentTarget;
    const fd = new FormData(form);
    const emailTrim = String(fd.get("email") ?? "").trim();
    const passwordFromForm = String(fd.get("password") ?? "");

    if (!emailTrim || !passwordFromForm) {
      const err = "Veuillez saisir votre e-mail et votre mot de passe.";
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

    try {
      const result = await signInWithPassword(emailTrim, passwordFromForm, "entreprise");

      if (result.error) {
        setMessage(result.error.message);
        toast.error("Connexion impossible", { description: result.error.message });
        return;
      }

      if (!result.data) {
        const err = "Réponse de connexion inattendue.";
        setMessage(err);
        toast.error(err);
        return;
      }

      toast.success("Connexion réussie");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      console.error(err);
      const errMsg = "Une erreur inattendue s’est produite.";
      setMessage(errMsg);
      toast.error(errMsg);
    } finally {
      setLoading(false);
      stopLoading();
      submitGuardRef.current = false;
    }
  };

  return (
    <AuthShell
      eyebrow="Connexion entreprise"
      title="Accédez à votre espace entreprise."
      subtitle="Retrouvez vos offres, vos candidatures et votre suivi recrutement dans un espace clair et fluide."
      highlights={[
        "Centralisez vos offres et vos candidatures.",
        "Gardez une vue simple sur votre activité de recrutement.",
        "Travaillez dans une interface sobre et professionnelle.",
      ]}
      stats={[
        { label: "Expérience", value: "Fluide" },
        { label: "Compte", value: "Entreprise" },
      ]}
      titleClassName="legacy-auth-hero__title--login"
    >
      <div className="legacy-auth-card__badge">Connexion</div>
      <h2 className="legacy-auth-card__title">Espace Entreprise</h2>
      <p className="legacy-auth-card__subtitle">
        Connectez-vous pour retrouver votre espace entreprise.
      </p>

      <form className="legacy-auth-form" onSubmit={handleSubmit}>
        <div className="legacy-auth-field">
          <label className="legacy-auth-label" htmlFor="test-login-email">
            Email professionnel
          </label>
          <input
            id="test-login-email"
            name="email"
            className="legacy-auth-input"
            type="email"
            autoComplete="email"
            placeholder="vous@entreprise.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="legacy-auth-field">
          <label className="legacy-auth-label" htmlFor="test-login-password">
            Mot de passe
          </label>
          <input
            id="test-login-password"
            name="password"
            className="legacy-auth-input"
            type="password"
            autoComplete="current-password"
            placeholder="Entrez votre mot de passe"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <button className="legacy-auth-submit" type="submit" disabled={loading}>
          {loading ? "Connexion..." : "Se connecter"}
        </button>
      </form>

      {message ? (
        <div className="legacy-auth-message legacy-auth-message--error">
          {message}
        </div>
      ) : null}

      <p className="legacy-auth-footer">
        Pas encore de compte ?{" "}
        <Link className="legacy-auth-link" to="/register">
          Créer un compte entreprise
        </Link>
      </p>
    </AuthShell>
  );
};

export default LoginCompany;