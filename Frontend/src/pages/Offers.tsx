import { useEffect, useState } from "react";
import RolePage from "../components/RolePage";
import "../styles/workspace.css";
import { apiFetch } from "@/services/authService";

interface Offre {
  id: string;
  title?: string;
  profile?: string;
  localisation?: string;
  type_contrat?: string;
  level?: string;
  nombre_candidats_recherche?: number;
  nombre_experience_minimun?: number;
  niveau_etude?: string;
  competences?: string;
  type_examens_ecrit?: string;
  nombre_questions_orale?: number;
  date_fin_offres?: string;
  description_postes?: string;
  status?: string;
  token_liens?: string;
}

const actionButtonBase: React.CSSProperties = {
  borderRadius: "10px",
  padding: "10px 16px",
  fontSize: "14px",
  fontWeight: 600,
  cursor: "pointer",
  transition: "all 0.2s ease",
  border: "1px solid transparent",
  background: "transparent",
};

const Offers = () => {
  const [offres, setOffres] = useState<Offre[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchOffres = async () => {
      try {
        const data = await apiFetch("/api/offres");
        setOffres(data);
      } catch (err) {
        console.error("Erreur chargement offres:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchOffres();
  }, []);

  return (
    <RolePage allow={["company"]}>
      {() => (
        <div className="legacy-workspace">
          <section className="legacy-workspace__hero">
            <div>
              <div className="legacy-workspace__eyebrow">Espace entreprise</div>
              <h1 className="legacy-workspace__title">Mes offres</h1>
              <p className="legacy-workspace__subtitle">
                Retrouvez ici vos offres publiées, leur état et leurs informations essentielles.
              </p>
            </div>
          </section>

          <section className="legacy-workspace__stack">
            {loading ? (
              <p>Chargement...</p>
            ) : offres.length === 0 ? (
              <p>Aucune offre trouvée.</p>
            ) : (
              offres.map((offer) => (
                <article
                  key={offer.id}
                  className="legacy-workspace__panel"
                  style={{
                    borderRadius: "28px",
                    padding: "30px 30px 24px",
                    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
                  }}
                >
                  <div
                    className="legacy-workspace__panel-header"
                    style={{ alignItems: "flex-start", marginBottom: "24px" }}
                  >
                    <div>
                      <h2
                        style={{
                          fontSize: "24px",
                          lineHeight: 1.2,
                          marginBottom: "8px",
                        }}
                      >
                        {offer.title || "Sans titre"}
                      </h2>
                      <span
                        style={{
                          fontSize: "15px",
                          color: "#64748B",
                          display: "inline-block",
                        }}
                      >
                        {offer.profile || "Profil non renseigné"}
                      </span>
                    </div>

                    <div
                      className="legacy-workspace__badges"
                      style={{ gap: "10px", flexWrap: "wrap" }}
                    >
                      <span
                        className="legacy-workspace__badge legacy-workspace__badge--emerald"
                        style={{
                          borderRadius: "999px",
                          padding: "10px 18px",
                          fontWeight: 600,
                        }}
                      >
                        {offer.status || "active"}
                      </span>

                      {offer.type_contrat ? (
                        <span
                          className="legacy-workspace__badge"
                          style={{
                            borderRadius: "999px",
                            padding: "10px 18px",
                            fontWeight: 600,
                          }}
                        >
                          {offer.type_contrat}
                        </span>
                      ) : null}
                    </div>
                  </div>

                  <div
                    className="legacy-workspace__meta-grid"
                    style={{ marginBottom: "20px" }}
                  >
                    <div>
                      <div className="legacy-workspace__label">Niveau requis</div>
                      <div className="legacy-workspace__value">
                        {offer.level || "-"}
                      </div>
                    </div>

                    <div>
                      <div className="legacy-workspace__label">Candidats recherchés</div>
                      <div className="legacy-workspace__value">
                        {offer.nombre_candidats_recherche ?? "-"}
                      </div>
                    </div>

                    <div>
                      <div className="legacy-workspace__label">Localisation</div>
                      <div className="legacy-workspace__value">
                        {offer.localisation || "-"}
                      </div>
                    </div>

                    <div>
                      <div className="legacy-workspace__label">Niveau d’études</div>
                      <div className="legacy-workspace__value">
                        {offer.niveau_etude || "-"}
                      </div>
                    </div>
                  </div>

                  {offer.competences && (
                    <div style={{ marginTop: "8px", marginBottom: "22px" }}>
                      <div
                        className="legacy-workspace__label"
                        style={{ marginBottom: "10px" }}
                      >
                        Compétences requises
                      </div>

                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "8px",
                        }}
                      >
                        {offer.competences.split(",").map((c, i) => (
                          <span
                            key={i}
                            style={{
                              background: "#EEF2FF",
                              color: "#3730A3",
                              padding: "7px 12px",
                              borderRadius: "999px",
                              fontSize: "13px",
                              fontWeight: 500,
                            }}
                          >
                            {c.trim()}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: "16px",
                      flexWrap: "wrap",
                      borderTop: "1px solid #E2E8F0",
                      paddingTop: "18px",
                      marginTop: "8px",
                    }}
                  >
                    <div
                      style={{
                        fontSize: "13px",
                        color: "#64748B",
                      }}
                    >
                      Gestion de l’offre
                    </div>

                    <div
                      style={{
                        display: "flex",
                        gap: "10px",
                        flexWrap: "wrap",
                      }}
                    >
                      <button
                        style={{
                          ...actionButtonBase,
                          background: "#F8FAFC",
                          border: "1px solid #E2E8F0",
                          color: "#0F172A",
                        }}
                      >
                        Voir détail
                      </button>

                      <button
                        style={{
                          ...actionButtonBase,
                          background: "#EFF6FF",
                          border: "1px solid #BFDBFE",
                          color: "#1D4ED8",
                        }}
                      >
                        Modifier
                      </button>

                      <button
                        style={{
                          ...actionButtonBase,
                          background: "#FEF2F2",
                          border: "1px solid #FECACA",
                          color: "#DC2626",
                        }}
                      >
                        Supprimer
                      </button>
                    </div>
                  </div>
                </article>
              ))
            )}
          </section>
        </div>
      )}
    </RolePage>
  );
};

export default Offers;