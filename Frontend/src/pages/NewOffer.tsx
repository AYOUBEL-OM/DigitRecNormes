import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Plus, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import RolePage from "@/components/RolePage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/services/authService";

const contractTypes = ["CDI", "CDD", "Freelance", "Stage", "Alternance"];
const examTypes = ["QCM", "Exercice"];
const educationLevels = [
  "Bac",
  "Bac+2",
  "Bac+3",
  "Bac+5",
  "Master",
  "Ingénieur",
  "Doctorat",
];

const cardClass =
  "rounded-2xl border border-border bg-card p-7 shadow-sm space-y-6";
const sectionTitleClass = "text-xl font-semibold text-foreground";
const sectionTextClass = "text-sm text-muted-foreground";
const badgeClass =
  "cursor-pointer select-none rounded-full px-4 py-2 text-sm transition-all";

const NewOfferInner = () => {
  const { toast } = useToast();
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [profile, setProfile] = useState("");
  const [localisation, setLocalisation] = useState("");
  const [typeContrat, setTypeContrat] = useState("");

  const [level, setLevel] = useState("");
  const [nombreCandidatsRecherche, setNombreCandidatsRecherche] = useState("");
  const [nombreExperienceMinimun, setNombreExperienceMinimun] = useState("");
  const [niveauEtude, setNiveauEtude] = useState("");

  const [skills, setSkills] = useState<string[]>([]);
  const [skillInput, setSkillInput] = useState("");

  const [typeExamensEcrit, setTypeExamensEcrit] = useState("");
  const [nombreQuestionsOrale, setNombreQuestionsOrale] = useState("");
  const [dateFinOffres, setDateFinOffres] = useState("");

  const [descriptionPostes, setDescriptionPostes] = useState("");
  const [generatedLink, setGeneratedLink] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const addSkill = () => {
    const trimmed = skillInput.trim();
    if (!trimmed) return;
    if (skills.includes(trimmed)) return;
    setSkills([...skills, trimmed]);
    setSkillInput("");
  };

  const removeSkill = (skillToRemove: string) => {
    setSkills(skills.filter((skill) => skill !== skillToRemove));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addSkill();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title || !descriptionPostes || !level) {
      toast({
        title: "Champs requis manquants",
        description:
          "Veuillez renseigner l’intitulé du poste, le niveau requis et la description.",
        variant: "destructive",
      });
      return;
    }

    if (isSubmitting) return;
    setIsSubmitting(true);

    try {
      const token = localStorage.getItem("access_token");

      if (!token) {
        toast({
          title: "Session expirée",
          description: "Merci de vous reconnecter.",
          variant: "destructive",
        });
        return;
      }

      const payload = {
        title: title,
        profile: profile || null,
        localisation: localisation || null,
        type_contrat: typeContrat || null,
        level: level,
        nombre_candidats_recherche: nombreCandidatsRecherche
          ? Number(nombreCandidatsRecherche)
          : null,
        nombre_experience_minimun: nombreExperienceMinimun
          ? Number(nombreExperienceMinimun)
          : null,
        niveau_etude: niveauEtude || null,
        competences: skills.length > 0 ? skills.join(", ") : null,
        type_examens_ecrit: typeExamensEcrit || null,
        nombre_questions_orale: nombreQuestionsOrale
          ? Number(nombreQuestionsOrale)
          : null,
        date_fin_offres: dateFinOffres || null,
        description_postes: descriptionPostes,
      };

      const data = await apiFetch("/api/offres", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      toast({
        title: "Offre publiée avec succès 🎉",
        description: "Lien de candidature généré.",
      });

      setGeneratedLink(data.lien_candidature || "");
    } catch (err) {
      console.error(err);
      toast({
        title: "Erreur",
        description: "Impossible de créer l’offre pour le moment.",
        variant: "destructive",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 pb-10">
      <div className="flex items-start gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate("/dashboard/offers")}
          className="mt-1"
        >
          <ArrowLeft className="h-5 w-5" />
        </Button>

        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">
            Créer une nouvelle offre
          </h1>
          <p className="text-sm text-muted-foreground">
            Renseignez les informations essentielles pour publier une offre
            claire, structurée et professionnelle.
          </p>
        </div>
      </div>

      <motion.form
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        onSubmit={handleSubmit}
        className="space-y-6"
      >
        <section className={cardClass}>
          <div className="space-y-1">
            <h2 className={sectionTitleClass}>Informations générales</h2>
            <p className={sectionTextClass}>
              Présentez l’offre, le profil visé, la localisation et le type de
              contrat proposé.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="title">Intitulé du poste *</Label>
              <Input
                id="title"
                placeholder="Ex. Développeur /concepteur logiciel"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="profile">Profil recherché</Label>
              <Input
                id="profile"
                placeholder="Ex. Développeur full stack /Ingénieur logiciel"
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="localisation">Localisation</Label>
              <Input
                id="localisation"
                placeholder="Ex. Casablanca / Remote"
                value={localisation}
                onChange={(e) => setLocalisation(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label>Type de contrat</Label>
              <div className="flex flex-wrap gap-2 pt-1">
                {contractTypes.map((type) => (
                  <Badge
                    key={type}
                    variant={typeContrat === type ? "default" : "outline"}
                    className={badgeClass}
                    onClick={() => setTypeContrat(type)}
                  >
                    {type}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className={cardClass}>
          <div className="space-y-1">
            <h2 className={sectionTitleClass}>Critères du poste</h2>
            <p className={sectionTextClass}>
              Définissez les exigences liées au niveau, à l’expérience, au
              volume de recrutement et aux compétences attendues.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="level">Niveau requis *</Label>
              <Input
                id="level"
                placeholder="Ex. Junior / Confirmé / Senior"
                value={level}
                onChange={(e) => setLevel(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="nb-candidats">
                Nombre de candidats recherchés
              </Label>
              <Input
                id="nb-candidats"
                type="number"
                min="1"
                placeholder="Ex. 5"
                value={nombreCandidatsRecherche}
                onChange={(e) => setNombreCandidatsRecherche(e.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="exp-min">
                Expérience minimale requise (années)
              </Label>
              <Input
                id="exp-min"
                type="number"
                min="0"
                placeholder="Ex. 2"
                value={nombreExperienceMinimun}
                onChange={(e) => setNombreExperienceMinimun(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="niveau-etude">Niveau d’études requis</Label>
              <select
                id="niveau-etude"
                value={niveauEtude}
                onChange={(e) => setNiveauEtude(e.target.value)}
                className="flex h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none"
              >
                <option value="">Sélectionner un niveau d’études</option>
                {educationLevels.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Compétences requises</Label>
            <div className="flex gap-2">
              <Input
                placeholder="Ex. React, Node.js, PostgreSQL"
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <Button
                type="button"
                variant="secondary"
                size="icon"
                onClick={addSkill}
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>

            {skills.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {skills.map((skill) => (
                  <Badge
                    key={skill}
                    variant="secondary"
                    className="gap-1 px-3 py-1"
                  >
                    {skill}
                    <X
                      className="h-3 w-3 cursor-pointer"
                      onClick={() => removeSkill(skill)}
                    />
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Ajoutez les compétences clés attendues pour ce poste.
              </p>
            )}
          </div>
        </section>

        <section className={cardClass}>
          <div className="space-y-1">
            <h2 className={sectionTitleClass}>Modalités d’évaluation</h2>
            <p className={sectionTextClass}>
              Configurez les paramètres liés à l’épreuve écrite, à l’oral et à
              la date limite de candidature.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label>Type d’épreuve écrite</Label>
              <div className="flex flex-wrap gap-2 pt-1">
                {examTypes.map((type) => (
                  <Badge
                    key={type}
                    variant={typeExamensEcrit === type ? "default" : "outline"}
                    className={badgeClass}
                    onClick={() => setTypeExamensEcrit(type)}
                  >
                    {type}
                  </Badge>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="nb-oral">Nombre de questions à l’oral</Label>
              <Input
                id="nb-oral"
                type="number"
                min="0"
                placeholder="Ex. 5"
                value={nombreQuestionsOrale}
                onChange={(e) => setNombreQuestionsOrale(e.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="date-fin">Date limite de candidature</Label>
              <Input
                id="date-fin"
                type="date"
                value={dateFinOffres}
                onChange={(e) => setDateFinOffres(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label className="opacity-0">Espace</Label>
              <div className="h-11 rounded-md border border-dashed border-border bg-muted/20" />
            </div>
          </div>
        </section>

        <section className={cardClass}>
          <div className="space-y-1">
            <h2 className={sectionTitleClass}>Description du poste</h2>
            <p className={sectionTextClass}>
              Décrivez clairement les missions, responsabilités, objectifs et
              attentes liés au poste.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="description-poste">Description détaillée *</Label>
            <Textarea
              id="description-poste"
              placeholder="Ex. Le poste consiste à concevoir, développer et maintenir des applications web performantes, collaborer avec l’équipe produit et garantir la qualité technique des livrables."
              className="min-h-[220px]"
              value={descriptionPostes}
              onChange={(e) => setDescriptionPostes(e.target.value)}
            />
          </div>
        </section>

        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/dashboard/offers")}
          >
            Annuler
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Publication…" : "Publier l’offre"}
          </Button>
        </div>
      </motion.form>

      {generatedLink && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-5 space-y-3">
          <h3 className="text-sm font-semibold text-green-800">
            🔗 Lien de candidature généré
          </h3>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={generatedLink}
              readOnly
              className="flex-1 h-10 px-3 rounded-md border text-sm bg-white"
            />

            <Button
              type="button"
              onClick={() => {
                navigator.clipboard.writeText(generatedLink);
                toast({
                  title: "Lien copié",
                  description:
                    "Le lien a été copié dans le presse-papiers",
                });
              }}
            >
              Copier
            </Button>
          </div>

          <p className="text-xs text-muted-foreground">
            Partagez ce lien avec les candidats pour postuler.
          </p>
        </div>
      )}
    </div>
  );
};

const NewOffer = () => (
  <RolePage allow={["company"]}>
    {() => <NewOfferInner />}
  </RolePage>
);

export default NewOffer;