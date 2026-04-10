import RolePage from "../components/RolePage";
import { formatAccountType } from "../lib/workspace";
import "../styles/workspace.css";

function formatDate(value: unknown) {
  if (typeof value !== "string" || !value) return "Non disponible";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Non disponible";

  return date.toLocaleString();
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "Non disponible";
  }

  return String(value);
}

const Profile = () => {
  return (
    <RolePage>
      {(account) => {
        const authFields = [
          { label: "id", value: account.authUser.id },
          { label: "Type de compte", value: formatAccountType(account.accountType) },
          { label: "Email", value: account.authUser.email },
          { label: "Derniere connexion", value: formatDate(account.authUser.last_sign_in_at) },
          { label: "Date de creation", value: formatDate(account.authUser.created_at) },
          { label: "Email confirme le", value: formatDate(account.authUser.email_confirmed_at) },
        ];

        const profileFields =
          account.accountType === "candidate"
            ? [
                { label: "Prenom", value: account.profile?.prenom },
                { label: "Nom", value: account.profile?.nom },
                { label: "CIN", value: account.profile?.cin },
                { label: "Intitule", value: account.profile?.title },
                { label: "Profil", value: account.profile?.profile },
                { label: "Niveau", value: account.profile?.level },
                { label: "CV", value: account.profile?.cv_url },
              ]
            : [
                { label: "Nom de l'entreprise", value: account.profile?.nom },
                { label: "Email professionnel", value: account.profile?.email_prof || account.authUser.email },
                { label: "Logo", value: account.profile?.logo_url },
              ];

        return (
          <div className="legacy-workspace">
            <section className="legacy-workspace__hero">
              <div>
                <div className="legacy-workspace__eyebrow">Mon profil</div>
                <h1 className="legacy-workspace__title">Profil</h1>
                <p className="legacy-workspace__subtitle">
                  Retrouvez ici vos informations principales, vos coordonnees et les elements
                  associes a votre profil.
                </p>
              </div>
              <div className="legacy-workspace__hero-pill">{formatAccountType(account.accountType)}</div>
            </section>

            <section className="legacy-workspace__split">
              <article className="legacy-workspace__panel">
                <div className="legacy-workspace__panel-header">
                  <h2>Informations du compte</h2>
                  <span>Resume</span>
                </div>
                <div className="legacy-workspace__list">
                  {authFields.map((field) => (
                    <div key={field.label} className="legacy-workspace__list-row">
                      <div className="legacy-workspace__label">{field.label}</div>
                      <div className="legacy-workspace__value">
                        {field.label === "id" ? `id : ${formatValue(field.value)}` : formatValue(field.value)}
                      </div>
                    </div>
                  ))}
                </div>
              </article>

              <article className="legacy-workspace__panel">
                <div className="legacy-workspace__panel-header">
                  <h2>Informations du profil</h2>
                  <span>Coordonnees</span>
                </div>
                <div className="legacy-workspace__list">
                  {profileFields.map((field) => (
                    <div key={field.label} className="legacy-workspace__list-row">
                      <div className="legacy-workspace__label">{field.label}</div>
                      <div className="legacy-workspace__value">{formatValue(field.value)}</div>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          </div>
        );
      }}
    </RolePage>
  );
};

export default Profile;
