import { Link, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import "../styles/not-found.css";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error("Test 404 Error: User attempted to access non-existent route:", location.pathname);
  }, [location.pathname]);

  return (
    <div className="legacy-test-not-found">
      <div className="legacy-test-not-found__card">
        <div className="legacy-test-not-found__eyebrow">
          <BrandLogo variant="light" size="sm" />
        </div>
        <h1 className="legacy-test-not-found__code">404</h1>
        <h2 className="legacy-test-not-found__title">Cette page n&apos;existe pas.</h2>
        <p className="legacy-test-not-found__subtitle">
          L&apos;adresse demandée ne correspond à aucune page disponible. Vous pouvez revenir à
          l&apos;accueil ou accéder directement à l&apos;inscription.
        </p>
        <div className="legacy-test-not-found__actions">
          <Link className="legacy-test-not-found__link legacy-test-not-found__link--primary" to="/">
            Retour à l&apos;accueil
          </Link>
          <Link className="legacy-test-not-found__link" to="/register">
            Ouvrir l&apos;inscription
          </Link>
        </div>
      </div>
    </div>
  );
};

export default NotFound;
