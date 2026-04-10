import { ReactNode } from "react";
import { AccountType, useAccount } from "../hooks/useAccount";

type RolePageProps = {
  allow?: AccountType[];
  children: (account: NonNullable<ReturnType<typeof useAccount>["account"]>) => ReactNode;
};

const RolePage = ({ allow, children }: RolePageProps) => {
  const { account, error, loading } = useAccount();

  if (loading) {
    return <div className="legacy-dashboard-state">Chargement de votre espace...</div>;
  }

  if (error || !account) {
    return (
      <div className="legacy-dashboard-state legacy-dashboard-state--error">
        {error || "Impossible de charger cette page pour le moment."}
      </div>
    );
  }

  if (allow && !allow.includes(account.accountType)) {
    return (
      <div className="legacy-dashboard-state">
        Cette page n&apos;est pas disponible pour ce type de compte.
      </div>
    );
  }

  return <>{children(account)}</>;
};

export default RolePage;
