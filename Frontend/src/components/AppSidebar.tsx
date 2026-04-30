import {
  Briefcase,
  ClipboardList,
  CreditCard,
  LayoutDashboard,
  Settings,
  UserRound,
  Users,
} from "lucide-react";
import { BrandLogo } from "@/components/BrandLogo";
import { NavLink } from "@/components/NavLink";
import { useLocation } from "react-router-dom";
import { useMemo } from "react";
import { useAccount } from "@/hooks/useAccount";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";

/** Renseigner un UUID réel d’offre (table offres.id) — ex. dans Frontend/.env.local : VITE_TEST_QUIZ_OFFRE_ID=... */
const TEST_QUIZ_OFFRE_UUID =
  (import.meta.env.VITE_TEST_QUIZ_OFFRE_ID as string | undefined)?.trim() ||
  "00000000-0000-4000-8000-000000000001";

type NavItem = {
  title: string;
  url: string;
  icon: typeof LayoutDashboard;
};

const companyItems: NavItem[] = [
  { title: "Mes Offres", url: "/dashboard/offers", icon: Briefcase },
  { title: "Candidats", url: "/dashboard/candidates", icon: Users },
  { title: "Tarifs", url: "/dashboard/pricing", icon: CreditCard },
  { title: "Paramètres", url: "/dashboard/settings", icon: Settings },
];

const candidateItems: NavItem[] = [
  { title: "Profil", url: "/dashboard/profile", icon: UserRound },
  { title: "Offres", url: "/dashboard/offers", icon: Briefcase },
  { title: "Mes candidatures", url: "/dashboard/applications", icon: ClipboardList },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const location = useLocation();
  const currentPath = location.pathname;
  const { account } = useAccount();

  const items = useMemo((): NavItem[] => {
    const base: NavItem[] = [{ title: "Tableau de bord", url: "/dashboard", icon: LayoutDashboard }];
    if (account?.accountType === "candidate") {
      return [...base, ...candidateItems];
    }
    return [...base, ...companyItems];
  }, [account?.accountType]);

  const isActive = (path: string) => {
    if (path === "/dashboard") {
      return currentPath === "/dashboard" || currentPath === "/dashboard/";
    }
    return currentPath === path || currentPath.startsWith(`${path}/`);
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarContent>
        <div className="flex items-center justify-center pt-4 pb-4">
          <BrandLogo
            variant="dark"
            collapsed={collapsed}
            size="xl"
            compact
            className="w-full justify-center"
          />
        </div>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild isActive={isActive(item.url)}>
                    <NavLink to={item.url} end={item.url === "/dashboard"}>
                      <item.icon className="mr-2 h-4 w-4" />
                      {!collapsed ? <span>{item.title}</span> : null}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
