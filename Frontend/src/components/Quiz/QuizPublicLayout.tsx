import { Outlet } from "react-router-dom";

/**
 * Enveloppe plein écran pour /quiz/:offreId — sans sidebar, topbar ni RequireAuth.
 */
export function QuizPublicLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      <Outlet />
    </div>
  );
}

export default QuizPublicLayout;
