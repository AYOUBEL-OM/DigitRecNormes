import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import RolePage from "@/components/RolePage";
import { useToast } from "@/hooks/use-toast";
import {
  getEnterpriseProfile,
  updateProfile,
  changePassword,
  mergeStoredEnterpriseUser,
  signOut,
} from "@/services/authService";

const SettingsInner = () => {
  const { toast } = useToast();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [nom, setNom] = useState("");
  const [description, setDescription] = useState("");
  const [email, setEmail] = useState("");

  const [savingProfile, setSavingProfile] = useState(false);
  const [ancien, setAncien] = useState("");
  const [nouveau, setNouveau] = useState("");
  const [confirm, setConfirm] = useState("");
  const [changingPwd, setChangingPwd] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const { data, error } = await getEnterpriseProfile();
      if (cancelled) return;
      if (error) {
        toast({
          variant: "destructive",
          title: "Erreur",
          description: error.message,
        });
        setLoading(false);
        return;
      }
      if (data) {
        setNom(data.nom ?? "");
        setDescription(data.description ?? "");
        setEmail(data.email_prof ?? "");
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chargement initial uniquement
  }, []);

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    const { data, error } = await updateProfile({
      nom: nom.trim(),
      description: description.trim() === "" ? null : description,
    });
    setSavingProfile(false);
    if (error) {
      toast({
        variant: "destructive",
        title: "Échec de l'enregistrement",
        description: error.message,
      });
      return;
    }
    if (data) {
      mergeStoredEnterpriseUser(data);
      toast({
        title: "Modifications enregistrées",
        description: "Les informations de l'entreprise ont été mises à jour.",
      });
    }
  };

  const handleChangePassword = async () => {
    if (nouveau.length < 8) {
      toast({
        variant: "destructive",
        title: "Mot de passe trop court",
        description: "Le nouveau mot de passe doit contenir au moins 8 caractères.",
      });
      return;
    }
    if (nouveau !== confirm) {
      toast({
        variant: "destructive",
        title: "Confirmation incorrecte",
        description: "Les deux saisies du nouveau mot de passe ne correspondent pas.",
      });
      return;
    }
    setChangingPwd(true);
    const { error } = await changePassword(ancien, nouveau);
    setChangingPwd(false);
    if (error) {
      toast({
        variant: "destructive",
        title: "Changement impossible",
        description: error.message,
      });
      return;
    }
    toast({
      title: "Mot de passe mis à jour",
      description: "Vous allez être déconnecté pour des raisons de sécurité.",
    });
    setAncien("");
    setNouveau("");
    setConfirm("");
    await signOut();
    navigate("/login", { replace: true });
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl space-y-8">
        <p className="text-sm text-muted-foreground">Chargement…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Paramètres</h1>
        <p className="text-sm text-muted-foreground">Gérez les paramètres de votre entreprise</p>
      </div>

      <div className="space-y-5 rounded-xl border bg-card p-6 card-shadow">
        <h2 className="font-semibold text-foreground">Informations de l&apos;entreprise</h2>
        <div className="space-y-2">
          <Label htmlFor="company-name">Nom de l&apos;entreprise</Label>
          <Input
            id="company-name"
            value={nom}
            onChange={(e) => setNom(e.target.value)}
            autoComplete="organization"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="company-desc">Description</Label>
          <Textarea
            id="company-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            className="resize-y"
            placeholder="Présentez votre entreprise…"
          />
        </div>
        <div className="flex justify-end pt-1">
          <Button type="button" onClick={handleSaveProfile} disabled={savingProfile}>
            {savingProfile ? "Enregistrement…" : "Enregistrer les modifications"}
          </Button>
        </div>
      </div>

      <Separator />

      <div className="space-y-5 rounded-xl border bg-card p-6 card-shadow">
        <h2 className="font-semibold text-foreground">Compte administrateur</h2>
        <div className="space-y-2">
          <Label htmlFor="admin-email">Email</Label>
          <Input id="admin-email" type="email" value={email} readOnly className="bg-muted/50" />
        </div>
        <div className="grid gap-5 md:grid-cols-2">
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="pwd-old">Mot de passe actuel</Label>
            <Input
              id="pwd-old"
              type="password"
              value={ancien}
              onChange={(e) => setAncien(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pwd-new">Nouveau mot de passe</Label>
            <Input
              id="pwd-new"
              type="password"
              value={nouveau}
              onChange={(e) => setNouveau(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pwd-confirm">Confirmer le mot de passe</Label>
            <Input
              id="pwd-confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
            />
          </div>
        </div>
        <div className="flex justify-end pt-1">
          <Button
            type="button"
            variant="secondary"
            onClick={handleChangePassword}
            disabled={changingPwd || !ancien || !nouveau || !confirm}
          >
            {changingPwd ? "Mise à jour…" : "Mettre à jour le mot de passe"}
          </Button>
        </div>
      </div>
    </div>
  );
};

const SettingsPage = () => (
  <RolePage allow={["company"]}>
    {() => <SettingsInner />}
  </RolePage>
);

export default SettingsPage;
