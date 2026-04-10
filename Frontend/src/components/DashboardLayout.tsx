import { Outlet, useNavigate } from "react-router-dom";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Button } from "@/components/ui/button";
import { signOut } from "@/services/authService";
import { useLoadingBar } from "./LoadingBarProvider";

const DashboardLayout = () => {
  const navigate = useNavigate();
  const { startLoading } = useLoadingBar();

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
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-14 items-center justify-between border-b bg-card px-4">
            <div className="flex items-center">
              <SidebarTrigger className="mr-4" />
              <h1 className="text-lg font-semibold text-foreground">DigitRec</h1>
            </div>
            <Button type="button" variant="ghost" size="sm" onClick={handleSignOut}>
              Se déconnecter
            </Button>
          </header>
          <main className="flex-1 overflow-auto bg-background p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default DashboardLayout;
