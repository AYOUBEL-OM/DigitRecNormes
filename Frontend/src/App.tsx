import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import DashboardLayout from "./components/DashboardLayout";
import LoadingBarProvider from "./components/LoadingBarProvider";
import RequireAuth from "./components/RequireAuth";
import Applications from "./pages/Applications";
import Candidates from "./pages/Candidates";
import Dashboard from "./pages/Dashboard";
import Index from "./pages/Index";
import Login from "./pages/Login";
import NewOffer from "./pages/NewOffer";
import NotFound from "./pages/NotFound";
import Offers from "./pages/Offers";
import Profile from "./pages/Profile";
import Register from "./pages/Register";
import SettingsPage from "./pages/Settings";
import RegisterCandidate from "./pages/Registre_candidat";


const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <LoadingBarProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/register/company" element={<Register />} />
            <Route path="/apply/:token" element={<RegisterCandidate />} />
            <Route
              path="/dashboard"
              element={
                <RequireAuth>
                  <DashboardLayout />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="profile" element={<Profile />} />
              <Route path="offers" element={<Offers />} />
              <Route path="offers/new" element={<NewOffer />} />
              <Route path="applications" element={<Applications />} />
              <Route path="candidates" element={<Candidates />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </LoadingBarProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
