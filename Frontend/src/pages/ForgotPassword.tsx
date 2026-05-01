import { FormEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import AuthShell from "../components/AuthShell";
import { isValidEmail } from "@/lib/validation";
import { requestEntreprisePasswordReset } from "../services/authService";

const ForgotPassword = () => {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const submitGuardRef = useRef(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitGuardRef.current) return;
    submitGuardRef.current = true;

    setLoading(true);
    setDone(false);

    const emailTrim = email.trim();
    if (!emailTrim || !isValidEmail(emailTrim)) {
      toast.error("Veuillez saisir une adresse e-mail valide.");
      setLoading(false);
      submitGuardRef.current = false;
      return;
    }

    try {
      await requestEntreprisePasswordReset(emailTrim);
    } catch (err) {
      // Ne pas révéler l’existence du compte ; message générique.
      console.error(err);
    } finally {
      setDone(true);
      setLoading(false);
      submitGuardRef.current = false;
    }
  };

  return (
    <AuthShell
      eyebrow="Mot de passe oublié"
      title="Réinitialisez l’accès à votre compte entreprise."
      subtitle="Saisissez votre email professionnel. Si un compte existe, vous recevrez un lien de réinitialisation."
      highlights={[
        "Email envoyé uniquement si un compte existe.",
        "Lien valable 30 minutes.",
        "Process sécurisé et à usage unique.",
      ]}
      stats={[
        { label: "Compte", value: "Entreprise" },
        { label: "Délai", value: "30 min" },
      ]}
    >
      <div className="legacy-auth-card__badge">Réinitialisation</div>
      <h2 className="legacy-auth-card__title">Demander un lien</h2>
      <p className="legacy-auth-card__subtitle">
        Nous vous enverrons un lien pour définir un nouveau mot de passe.
      </p>

      <form className="legacy-auth-form" onSubmit={handleSubmit}>
        <div className="legacy-auth-field">
          <label className="legacy-auth-label" htmlFor="forgot-email">
            Email professionnel
          </label>
          <input
            id="forgot-email"
            name="email"
            className="legacy-auth-input"
            type="email"
            autoComplete="email"
            placeholder="vous@entreprise.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <button className="legacy-auth-submit" type="submit" disabled={loading}>
          {loading ? "Envoi..." : "Envoyer le lien de réinitialisation"}
        </button>
      </form>

      {done ? (
        <div className="legacy-auth-message">
          Si un compte existe avec cet email, un lien de réinitialisation a été envoyé.
        </div>
      ) : null}

      <p className="legacy-auth-footer">
        <Link className="legacy-auth-link" to="/login">
          Retour à la connexion
        </Link>
      </p>
    </AuthShell>
  );
};

export default ForgotPassword;

