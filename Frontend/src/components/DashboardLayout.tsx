import { Outlet, useNavigate } from "react-router-dom";
import { BrandLogo } from "@/components/BrandLogo";
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
            <div className="flex items-center gap-3">
              <SidebarTrigger className="mr-1" />
              <BrandLogo variant="light" size="md" className="hidden sm:flex" />
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
