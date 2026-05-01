import { FormEvent, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import AuthShell from "../components/AuthShell";
import { resetEntreprisePassword } from "../services/authService";

const ResetPassword = () => {
  const [params] = useSearchParams();
  const token = useMemo(() => String(params.get("token") ?? "").trim(), [params]);

  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const submitGuardRef = useRef(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitGuardRef.current) return;
    submitGuardRef.current = true;

    if (!token) {
      toast.error("Lien invalide : token manquant.");
      submitGuardRef.current = false;
      return;
    }

    if (newPassword.length < 8) {
      toast.error("Le mot de passe doit contenir au moins 8 caractères.");
      submitGuardRef.current = false;
      return;
    }
    if (newPassword !== confirm) {
      toast.error("La confirmation ne correspond pas.");
      submitGuardRef.current = false;
      return;
    }

    setLoading(true);
    try {
      await resetEntreprisePassword(token, newPassword);
      setDone(true);
      toast.success("Mot de passe réinitialisé.");
    } catch (err: any) {
      console.error(err);
      toast.error("Réinitialisation impossible", {
        description: err?.message || "Le lien est peut-être expiré.",
      });
    } finally {
      setLoading(false);
      submitGuardRef.current = false;
    }
  };

  return (
    <AuthShell
      eyebrow="Nouveau mot de passe"
      title="Définissez un nouveau mot de passe."
      subtitle="Choisissez un mot de passe robuste pour sécuriser votre compte entreprise."
      highlights={[
        "Minimum 8 caractères.",
        "Lien à usage unique.",
        "Expiration automatique (30 min).",
      ]}
      stats={[
        { label: "Compte", value: "Entreprise" },
        { label: "Sécurité", value: "One-time" },
      ]}
    >
      <div className="legacy-auth-card__badge">Sécurité</div>
      <h2 className="legacy-auth-card__title">Réinitialiser le mot de passe</h2>
      <p className="legacy-auth-card__subtitle">
        Saisissez et confirmez votre nouveau mot de passe.
      </p>

      {done ? (
        <>
          <div className="legacy-auth-message">
            Votre mot de passe a été réinitialisé avec succès.
          </div>
          <p className="legacy-auth-footer">
            <Link className="legacy-auth-link" to="/login">
              Aller à la connexion entreprise
            </Link>
          </p>
        </>
      ) : (
        <>
          <form className="legacy-auth-form" onSubmit={handleSubmit}>
            <div className="legacy-auth-field">
              <label className="legacy-auth-label" htmlFor="new-password">
                Nouveau mot de passe
              </label>
              <input
                id="new-password"
                name="new_password"
                className="legacy-auth-input"
                type="password"
                autoComplete="new-password"
                placeholder="Au moins 8 caractères"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>

            <div className="legacy-auth-field">
              <label className="legacy-auth-label" htmlFor="confirm-password">
                Confirmation
              </label>
              <input
                id="confirm-password"
                name="confirm_password"
                className="legacy-auth-input"
                type="password"
                autoComplete="new-password"
                placeholder="Répétez le mot de passe"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>

            <button className="legacy-auth-submit" type="submit" disabled={loading}>
              {loading ? "Réinitialisation..." : "Réinitialiser le mot de passe"}
            </button>
          </form>

          <p className="legacy-auth-footer">
            <Link className="legacy-auth-link" to="/forgot-password">
              Renvoyer un lien
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  );
};

export default ResetPassword;

