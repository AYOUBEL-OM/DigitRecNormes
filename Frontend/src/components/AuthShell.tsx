import { motion } from "framer-motion";
import { ReactNode, useEffect, useState } from "react";
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

          <div className="legacy-auth-hero__brand">
            <div className="legacy-auth-hero__mark">DR</div>
            <div>
              <div className="legacy-auth-hero__brand-title">DigitRec</div>
              <div className="legacy-auth-hero__brand-subtitle">Plateforme de recrutement</div>
            </div>
          </div>

            <div className="legacy-auth-hero__content">
              <p className="legacy-auth-hero__eyebrow">{eyebrow}</p>
              <h1 className={titleClassName ? `legacy-auth-hero__title ${titleClassName}` : "legacy-auth-hero__title"}>
                <span className="legacy-auth-hero__title-text">{typedTitle}</span>
                <span className="legacy-auth-hero__cursor" aria-hidden="true" />
              </h1>
              <p className="legacy-auth-hero__subtitle">{subtitle}</p>

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
