import { useEffect, useState } from "react";
import { useLoadingBar } from "../components/LoadingBarProvider";

export type AccountType = "candidate" | "company" | "unknown";

export type AuthUser = {
  email?: string;
  id: string;
  type?: string;
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
        const token = localStorage.getItem("access_token");
        const userJson = localStorage.getItem("user");

        if (!active) return;

        if (!token || !userJson) {
          setState({
            account: null,
            error: "Pas de session valide",
            loading: false,
          });
          return;
        }

        let parsedUser: any;
        try {
          parsedUser = JSON.parse(userJson);
        } catch {
          setState({
            account: null,
            error: "Impossible d'analyser l'utilisateur",
            loading: false,
          });
          return;
        }

        const accountType: AccountType =
          parsedUser.type === "candidat" ? "candidate" : parsedUser.type === "entreprise" ? "company" : "unknown";

        const account: Account = {
          accountType,
          authUser: {
            id: String(parsedUser.id || ""),
            email: parsedUser.email || parsedUser.email_prof || "",
            type: parsedUser.type,
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
