import { useState } from "react";
import { Loader2, Lock, Mic } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, loginCandidatForOral } from "@/services/authService";

type OralCandidateLoginProps = {
  /** Après connexion API réussie et contrôle d’accès oral côté serveur. */
  onSessionReady: () => Promise<void>;
};

/**
 * Formulaire email / mot de passe pour l’entretien oral (aligné visuellement sur le test écrit).
 */
const OralCandidateLogin = ({ onSessionReady }: OralCandidateLoginProps) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await loginCandidatForOral(email, password);
      await onSessionReady();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Connexion impossible.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-background to-primary/5 py-10 px-4 text-foreground">
      <div className="mx-auto max-w-md">
        <div className="mb-8 text-center">
          <div className="mb-4 inline-flex rounded-2xl bg-primary p-3 shadow-lg">
            <Mic className="h-8 w-8 text-primary-foreground" aria-hidden />
          </div>
          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">Accès à l&apos;entretien oral</h1>
          <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
            Veuillez vous connecter avec votre email et votre mot de passe pour commencer votre entretien.
          </p>
        </div>

        <div className="rounded-xl border border-primary/20 bg-card p-6 shadow-lg card-shadow">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Lock className="h-4 w-4 shrink-0" aria-hidden />
            Connexion candidat requise
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="oral-login-email">Email</Label>
              <Input
                id="oral-login-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(ev) => setEmail(ev.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="oral-login-password">Mot de passe</Label>
              <Input
                id="oral-login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(ev) => setPassword(ev.target.value)}
                required
                disabled={loading}
              />
            </div>
            {error ? (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            ) : null}
            <Button type="submit" className="w-full rounded-xl" size="lg" disabled={loading}>
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> : null}
              Accéder à l&apos;entretien
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default OralCandidateLogin;
