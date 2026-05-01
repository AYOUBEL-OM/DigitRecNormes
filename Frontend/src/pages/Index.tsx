import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { BrandLogo } from "@/components/BrandLogo";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Clock,
  Shield,
  Zap,
} from "lucide-react";

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.15, duration: 0.6, ease: "easeOut" as const },
  }),
};

const features = [
  {
    icon: Zap,
    title: "Automatisation intelligente",
    desc: "Cadrez vos flux de recrutement dans un espace plus clair et plus rapide a piloter.",
  },
  {
    icon: BarChart3,
    title: "Analyses en temps reel",
    desc: "Suivez vos indicateurs et vos etapes depuis un tableau de bord unifie.",
  },
  {
    icon: Clock,
    title: "Gain de temps",
    desc: "Accedez plus vite aux offres, candidatures et evaluations utiles a chaque role.",
  },
  {
    icon: Shield,
    title: "Architecture recentree",
    desc: "Le flux principal repose maintenant sur Supabase pour l'authentification et les donnees.",
  },
];

const Index = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-background">
      <nav className="fixed top-0 z-50 w-full border-b bg-card/80 backdrop-blur-md">
        <div className="container mx-auto flex h-16 items-center justify-between px-6">
          <BrandLogo variant="light" size="md" />
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => document.getElementById("about")?.scrollIntoView({ behavior: "smooth" })}
            >
              A propos
            </Button>
            <Button variant="ghost" size="sm" onClick={() => navigate("/register")}>
              Inscription
            </Button>
            <Button size="sm" onClick={() => navigate("/login")}>
              Connexion
            </Button>
          </div>
        </div>
      </nav>

      <section className="hero-gradient relative overflow-hidden pt-16">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_50%,hsl(210_100%_52%/0.15),transparent_50%)]" />
        <div className="container relative mx-auto flex min-h-[85vh] flex-col items-center justify-center px-6 text-center">
          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            custom={0}
            className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary-foreground/20 bg-primary-foreground/5 px-4 py-2 text-sm text-primary-foreground/80"
          >
            <Zap className="h-4 w-4" />
            Plateforme de recrutement nouvelle generation
          </motion.div>

          <motion.h1
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            custom={1}
            className="mb-6 max-w-4xl text-5xl font-extrabold leading-tight tracking-tight text-primary-foreground md:text-7xl"
          >
            Recrutez les{" "}
            <span className="bg-gradient-to-r from-accent to-accent/70 bg-clip-text text-transparent">
              meilleurs talents
            </span>
            , simplement.
          </motion.h1>

          <motion.p
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            custom={2}
            className="mb-10 max-w-2xl text-lg text-primary-foreground/70"
          >
            DigitRec recentre maintenant son experience principale autour du flux Supabase:
            connexion, inscription et dashboard deviennent le coeur du produit.
          </motion.p>

          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            custom={3}
            className="flex flex-wrap items-center justify-center gap-4"
          >
            <Button variant="hero" size="lg" className="text-base" onClick={() => navigate("/register")}>
              Demarrer maintenant
              <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
            <Button variant="hero-outline" size="lg" className="text-base" onClick={() => navigate("/dashboard")}>
              Ouvrir mon espace
            </Button>
          </motion.div>

          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            custom={4}
            className="mt-12 flex flex-wrap items-center justify-center gap-8 text-sm text-primary-foreground/50"
          >
            {["Connexion principale", "Dashboard unifie", "Supabase en reference"].map((stat) => (
              <div key={stat} className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-accent" />
                {stat}
              </div>
            ))}
          </motion.div>
        </div>

        <div className="absolute bottom-0 left-0 w-full">
          <svg viewBox="0 0 1440 80" fill="none" className="w-full">
            <path
              d="M0 40C240 80 480 0 720 40C960 80 1200 0 1440 40V80H0V40Z"
              fill="hsl(var(--background))"
            />
          </svg>
        </div>
      </section>

      <section id="about" className="py-24">
        <div className="container mx-auto px-6">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-100px" }}
            variants={fadeUp}
            custom={0}
            className="mb-16 text-center"
          >
            <h2 className="mb-4 text-3xl font-bold text-foreground md:text-4xl">
              Pourquoi choisir DigitRec ?
            </h2>
            <p className="mx-auto max-w-2xl text-muted-foreground">
              Une plateforme qui garde l'interface marketing en entree et fait passer le vrai produit
              en priorite dans les routes principales.
            </p>
          </motion.div>

          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {features.map((feature, index) => (
              <motion.div
                key={feature.title}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, margin: "-50px" }}
                variants={fadeUp}
                custom={index}
                className="group rounded-xl border bg-card p-6 card-shadow transition-all duration-300 hover:card-shadow-hover hover:-translate-y-1"
              >
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-accent/10 text-accent transition-colors group-hover:bg-accent group-hover:text-accent-foreground">
                  <feature.icon className="h-6 w-6" />
                </div>
                <h3 className="mb-2 font-semibold text-foreground">{feature.title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{feature.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t py-8">
        <div className="container mx-auto flex items-center justify-between px-6 text-sm text-muted-foreground">
          <BrandLogo variant="light" size="sm" className="opacity-90" />
          <p>© 2026 DigitRec. Tous droits reserves.</p>
        </div>
      </footer>
    </div>
  );
};

export default Index;
