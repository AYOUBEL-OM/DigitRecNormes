import { useEffect, useState } from "react";
import { useLoadingBar } from "../components/LoadingBarProvider";
import { getAccessToken, getStoredUser } from "@/services/authService";

export type AccountType = "candidate" | "company" | "unknown";

export type AuthUser = {
  email?: string;
  id: string;
  type?: string;
  /** Métadonnées optionnelles (ex. JWT / session) si présentes dans le stockage. */
  last_sign_in_at?: string | null;
  created_at?: string | null;
  email_confirmed_at?: string | null;
};

export type Account = {
  accountType: AccountType;
  authUser: AuthUser;
  displayName: string;
  profile: Record<string, unknown> | null;
  source: string | null;
};

type AccountState = {
  account: Account | null;
  error: string;
  loading: boolean;
};

export function useAccount() {
  const { startLoading } = useLoadingBar();
  const [state, setState] = useState<AccountState>({
    account: null,
    error: "",
    loading: true,
  });

  useEffect(() => {
    let active = true;

    const loadAccount = () => {
      const stopLoading = startLoading();
      try {
        // Priorité affichage : entreprise si session active, sinon candidat.
        const entrepriseToken = getAccessToken("entreprise");
        const candidatToken = getAccessToken("candidat");
        const entrepriseUser = getStoredUser("entreprise");
        const candidatUser = getStoredUser("candidat");

        if (!active) return;

        const hasEntrepriseSession = !!entrepriseToken && !!entrepriseUser;
        const hasCandidatSession = !!candidatToken && !!candidatUser;
        const selectedUser = hasEntrepriseSession ? entrepriseUser : hasCandidatSession ? candidatUser : null;

        if (!selectedUser) {
          setState({
            account: null,
            error: "Pas de session valide",
            loading: false,
          });
          return;
        }

        const parsedUser: any = selectedUser;

        const accountType: AccountType =
          parsedUser.type === "candidat" ? "candidate" : parsedUser.type === "entreprise" ? "company" : "unknown";

        const account: Account = {
          accountType,
          authUser: {
            id: String(parsedUser.id || ""),
            email: parsedUser.email || parsedUser.email_prof || "",
            type: parsedUser.type,
            last_sign_in_at: parsedUser.last_sign_in_at ?? null,
            created_at: parsedUser.created_at ?? null,
            email_confirmed_at: parsedUser.email_confirmed_at ?? null,
          },
          displayName: (parsedUser.nom || parsedUser.prenom || parsedUser.email || "Compte DigitRec") as string,
          profile: null,
          source: "localStorage",
        };

        setState({ account, error: "", loading: false });
      } finally {
        stopLoading();
      }
    };

    loadAccount();
    const onSessionUpdate = () => loadAccount();
    window.addEventListener("digitrec:session-update", onSessionUpdate);

    return () => {
      active = false;
      window.removeEventListener("digitrec:session-update", onSessionUpdate);
    };
  }, [startLoading]);

  return state;
}
