import RolePage from "../components/RolePage";
import { candidateApplications } from "../lib/workspace";
import "../styles/workspace.css";

const Applications = () => {
  return (
    <RolePage allow={["candidate"]}>
      {() => (
        <div className="legacy-workspace">
          <section className="legacy-workspace__hero">
            <div>
              <div className="legacy-workspace__eyebrow">Espace candidat</div>
              <h1 className="legacy-workspace__title">Mes candidatures</h1>
              <p className="legacy-workspace__subtitle">
                Suivez ici l'état de vos candidatures, les étapes en cours et les dernières
                actions enregistrées sur vos dossiers.
              </p>
            </div>
            <div className="legacy-workspace__hero-pill">{candidateApplications.length} en cours</div>
          </section>

          <section className="legacy-workspace__stack">
            {candidateApplications.map((application) => (
              <article key={application.id} className="legacy-workspace__panel">
                <div className="legacy-workspace__panel-header">
                  <div>
                    <h2>{application.offerTitle}</h2>
                    <span>{application.company}</span>
                  </div>
                  <div className="legacy-workspace__badges">
                    <span className="legacy-workspace__badge legacy-workspace__badge--violet">{application.stage}</span>
                    <span className="legacy-workspace__badge">{application.score}</span>
                  </div>
                </div>
                <p className="legacy-workspace__description">{application.summary}</p>
                <div className="legacy-workspace__meta-grid">
                  <div>
                    <div className="legacy-workspace__label">Date de candidature</div>
                    <div className="legacy-workspace__value">{application.submittedAt}</div>
                  </div>
                </div>
              </article>
            ))}
          </section>
        </div>
      )}
    </RolePage>
  );
};

export default Applications;
