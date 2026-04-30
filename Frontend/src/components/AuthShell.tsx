import { motion } from "framer-motion";
import { ReactNode, useEffect, useState } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import "../styles/auth.css";

type AuthShellProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  highlights: string[];
  stats: Array<{ label: string; value: string }>;
  layout?: "default" | "compact-form" | "card-only";
  cardClassName?: string;
  titleClassName?: string;
  children: ReactNode;
};

const panelMotion = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.55, ease: "easeOut" as const } },
};

const AuthShell = ({
  eyebrow,
  title,
  subtitle,
  highlights,
  stats,
  layout = "default",
  cardClassName = "",
  titleClassName = "",
  children,
}: AuthShellProps) => {
  const [typedTitle, setTypedTitle] = useState("");

  useEffect(() => {
    setTypedTitle("");

    let index = 0;
    const timer = window.setInterval(() => {
      index += 1;
      setTypedTitle(title.slice(0, index));

      if (index >= title.length) {
        window.clearInterval(timer);
      }
    }, 34);

    return () => {
      window.clearInterval(timer);
    };
  }, [title]);

  const shellClass =
    layout === "compact-form"
      ? "legacy-auth-shell legacy-auth-shell--compact-form"
      : layout === "card-only"
        ? "legacy-auth-shell legacy-auth-shell--card-only"
        : "legacy-auth-shell";

  return (
    <div className="legacy-auth-page">
      <div className={shellClass}>
        {layout !== "card-only" ? (
          <motion.section
            className="legacy-auth-hero"
            initial="hidden"
            animate="visible"
            variants={panelMotion}
          >
            <div className="legacy-auth-hero__glow legacy-auth-hero__glow--one" />
            <div className="legacy-auth-hero__glow legacy-auth-hero__glow--two" />

            <div className="flex flex-col justify-center h-full px-10 space-y-4">
              <div className="max-w-md mx-auto flex flex-col justify-center h-full">
                <div className="flex justify-center mb-1 overflow-visible">
                  <div className="h-24 flex items-center justify-center overflow-visible">
                    <BrandLogo variant="dark" size="hero" compact />
                  </div>
                </div>

                <div className="legacy-auth-hero__content">
                  <p className="text-xs tracking-wider text-muted-foreground uppercase">
                    {eyebrow}
                  </p>
                  <h1 className="text-4xl font-bold leading-tight">
                    <span className="legacy-auth-hero__title-text">{typedTitle}</span>
                    <span className="legacy-auth-hero__cursor" aria-hidden="true" />
                  </h1>
                  <p className="text-sm text-muted-foreground">{subtitle}</p>

                  <div className="legacy-auth-hero__list">
                    {highlights.map((item) => (
                      <div key={item} className="legacy-auth-hero__bullet">
                        <span className="legacy-auth-hero__bullet-dot" />
                        <span>{item}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="legacy-auth-hero__stats">
                  {stats.map((stat) => (
                    <div key={stat.label} className="legacy-auth-hero__stat">
                      <span className="legacy-auth-hero__stat-value">{stat.value}</span>
                      <span className="legacy-auth-hero__stat-label">{stat.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </motion.section>
        ) : null}

        <motion.section
          className={cardClassName ? `legacy-auth-card ${cardClassName}` : "legacy-auth-card"}
          initial="hidden"
          animate="visible"
          variants={panelMotion}
        >
          {children}
        </motion.section>
      </div>
    </div>
  );
};

export default AuthShell;
