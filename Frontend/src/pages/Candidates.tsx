import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import RolePage from "@/components/RolePage";

const candidates = [
  { id: 1, name: "Marie Dupont", role: "Développeur Full-Stack", stage: "Entretien technique", rating: 4.5 },
  { id: 2, name: "Lucas Martin", role: "Product Designer", stage: "Screening", rating: 3.8 },
  { id: 3, name: "Sophie Bernard", role: "Data Analyst", stage: "Offre finale", rating: 4.9 },
  { id: 4, name: "Thomas Petit", role: "Chef de Projet", stage: "Réception CV", rating: 3.2 },
  { id: 5, name: "Camille Robert", role: "Développeur Full-Stack", stage: "Entretien RH", rating: 4.1 },
];

const stageColor: Record<string, string> = {
  "Réception CV": "secondary",
  Screening: "outline",
  "Entretien RH": "default",
  "Entretien technique": "default",
  "Offre finale": "default",
};

const CandidatesInner = () => {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Candidats</h1>
        <p className="text-sm text-muted-foreground">{candidates.length} candidats dans le pipeline</p>
      </div>

      <div className="grid gap-3">
        {candidates.map((c) => (
          <div
            key={c.id}
            className="flex cursor-pointer items-center gap-4 rounded-xl border bg-card p-4 card-shadow transition-all hover:card-shadow-hover"
          >
            <Avatar className="h-10 w-10">
              <AvatarFallback className="bg-accent/10 text-sm font-medium text-accent">
                {c.name
                  .split(" ")
                  .map((n) => n[0])
                  .join("")}
              </AvatarFallback>
            </Avatar>
            <div className="flex-1">
              <p className="font-medium text-foreground">{c.name}</p>
              <p className="text-sm text-muted-foreground">{c.role}</p>
            </div>
            <Badge variant={(stageColor[c.stage] as "default" | "secondary" | "outline") || "secondary"}>
              {c.stage}
            </Badge>
            <div className="text-sm font-medium text-foreground">{c.rating}/5</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const Candidates = () => (
  <RolePage allow={["company"]}>
    {() => <CandidatesInner />}
  </RolePage>
);

export default Candidates;
