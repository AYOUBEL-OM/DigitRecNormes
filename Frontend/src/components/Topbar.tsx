import { Menu } from "lucide-react";
import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAccount } from "../hooks/useAccount";
import { getPageMeta } from "../lib/workspace";
import { signOut } from "../services/authService";
import { useLoadingBar } from "./LoadingBarProvider";

type TopbarProps = {
  collapsed: boolean;
  onToggleSidebar: () => void;
};

const Topbar = ({ collapsed, onToggleSidebar }: TopbarProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { account } = useAccount();
  const { startLoading } = useLoadingBar();
  const pageMeta = useMemo(
    () => getPageMeta(location.pathname, account?.accountType || "unknown"),
    [account?.accountType, location.pathname]
  );

  const handleSignOut = async () => {
    const stopLoading = startLoading();

    try {
      await signOut();
      navigate("/login", { replace: true });
    } finally {
      stopLoading();
    }
  };

  return (
    <header className="legacy-topbar">
      <div className="legacy-topbar__left">
        <button
          type="button"
          className="legacy-topbar__menu"
          onClick={onToggleSidebar}
          aria-label={collapsed ? "Ouvrir la barre laterale" : "Reduire la barre laterale"}
          aria-pressed={!collapsed}
        >
          <Menu size={18} />
        </button>

        <div>
          <div className="legacy-topbar__eyebrow">{pageMeta.eyebrow}</div>
          <div className="legacy-topbar__title">{pageMeta.title}</div>
        </div>
      </div>

      <div className="legacy-topbar__right">
        <button type="button" className="legacy-topbar__action" onClick={handleSignOut}>
          Se deconnecter
        </button>
      </div>
    </header>
  );
};

export default Topbar;
