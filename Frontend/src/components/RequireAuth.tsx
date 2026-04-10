import { ReactNode, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getSession } from "../services/authService";
import { useLoadingBar } from "./LoadingBarProvider";

type RequireAuthProps = {
  children: ReactNode;
};

const RequireAuth = ({ children }: RequireAuthProps) => {
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);
  const { startLoading } = useLoadingBar();

  const redirectIfNoToken = useCallback(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      navigate("/login", { replace: true });
      return false;
    }
    return true;
  }, [navigate]);

  useEffect(() => {
    let active = true;
    const stopLoading = startLoading();

    const checkSession = async () => {
      try {
        const sessionResult = await getSession();

        if (!active) return;

        if (sessionResult.error || !sessionResult.data) {
          navigate("/login", { replace: true });
          return;
        }

        setChecking(false);
      } finally {
        stopLoading();
      }
    };

    checkSession();

    return () => {
      active = false;
      stopLoading();
    };
  }, [navigate, startLoading]);

  // Back-button / bfcache: session may be cleared while a cached page is shown.
  useEffect(() => {
    const onPageShow = () => {
      redirectIfNoToken();
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        redirectIfNoToken();
      }
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key === "access_token" && !event.newValue) {
        navigate("/login", { replace: true });
      }
    };

    window.addEventListener("pageshow", onPageShow);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("storage", onStorage);

    return () => {
      window.removeEventListener("pageshow", onPageShow);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("storage", onStorage);
    };
  }, [navigate, redirectIfNoToken]);

  if (checking) {
    return (
      <div className="min-h-screen bg-background px-6 py-16">
        <div className="mx-auto max-w-3xl rounded-2xl border bg-card p-8 text-sm text-muted-foreground shadow-sm">
          Vérification de votre session...
        </div>
      </div>
    );
  }

  return <>{children}</>;
};

export default RequireAuth;
