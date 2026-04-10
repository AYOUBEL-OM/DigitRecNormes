import { motion } from "framer-motion";
import { Users, Briefcase, CalendarCheck, TrendingUp } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";
import { useAccount } from "@/hooks/useAccount";

const stats = [
  { label: "Total Candidats", value: 1284, icon: Users, change: "+12%", color: "text-accent" },
  { label: "Offres Actives", value: 18, icon: Briefcase, change: "+3", color: "text-success" },
  { label: "Entretiens prévus", value: 42, icon: CalendarCheck, change: "Cette semaine", color: "text-warning" },
  { label: "Taux de conversion", value: "23%", icon: TrendingUp, change: "+2.4%", color: "text-accent" },
];

const pipelines = [
  { title: "Développeur Full-Stack", progress: 75, candidates: 34, stage: "Entretien technique" },
  { title: "Product Designer", progress: 45, candidates: 18, stage: "Screening" },
  { title: "Data Analyst", progress: 90, candidates: 12, stage: "Offre finale" },
  { title: "Chef de Projet", progress: 20, candidates: 28, stage: "Réception CV" },
];

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.5, ease: "easeOut" as const },
  }),
};

const Dashboard = () => {
  const navigate = useNavigate();
  const { account } = useAccount();

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Tableau de bord</h1>
          <p className="text-sm text-muted-foreground">Vue d&apos;ensemble de votre activité de recrutement</p>
        </div>
        {account?.accountType === "company" ? (
          <Button onClick={() => navigate("/dashboard/offers/new")}>+ Nouvelle offre</Button>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            custom={i}
            className="rounded-xl border bg-card p-5 card-shadow transition-all hover:card-shadow-hover"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm text-muted-foreground">{stat.label}</p>
                <p className="mt-1 text-3xl font-bold text-foreground">{stat.value}</p>
              </div>
              <div className={`rounded-lg bg-secondary p-2.5 ${stat.color}`}>
                <stat.icon className="h-5 w-5" />
              </div>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              <span className="font-medium text-success">{stat.change}</span>{" "}
              {typeof stat.value === "number" ? "vs. mois dernier" : ""}
            </p>
          </motion.div>
        ))}
      </div>

      <motion.div initial="hidden" animate="visible" variants={fadeUp} custom={4}>
        <h2 className="mb-4 text-lg font-semibold text-foreground">Recrutements en cours</h2>
        <div className="grid gap-4 md:grid-cols-2">
          {pipelines.map((p, i) => (
            <motion.div
              key={p.title}
              initial="hidden"
              animate="visible"
              variants={fadeUp}
              custom={5 + i}
              className="rounded-xl border bg-card p-5 card-shadow"
            >
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-medium text-foreground">{p.title}</h3>
                <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                  {p.candidates} candidats
                </span>
              </div>
              <Progress value={p.progress} className="mb-2 h-2" />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{p.stage}</span>
                <span className="font-medium">{p.progress}%</span>
              </div>
            </motion.div>
          ))}
        </div>
      </motion.div>
    </div>
  );
};

export default Dashboard;
