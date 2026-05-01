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
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import NewOffer from "./pages/NewOffer";
import NotFound from "./pages/NotFound";
import Offers from "./pages/Offers";
import Profile from "./pages/Profile";
import Register from "./pages/Register";
import SettingsPage from "./pages/Settings";
import Pricing from "./pages/Pricing";
import RegisterCandidate from "./pages/Registre_candidat";
import { QuizModule } from "./components/Quiz/QuizModule";
import { QuizPublicLayout } from "./components/Quiz/QuizPublicLayout";
import OralInterviewGate from "./oral-interview/OralInterviewGate";
import OralInterviewPage from "./oral-interview/InterviewPage";


const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <LoadingBarProvider>
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true,
          }}
        >
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
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
              <Route path="new-offer" element={<NewOffer />} />
              <Route path="applications" element={<Applications />} />
              <Route path="candidates" element={<Candidates />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="pricing" element={<Pricing />} />
            </Route>
            <Route path="/quiz/:offreId" element={<QuizPublicLayout />}>
              <Route index element={<QuizModule />} />
            </Route>
            <Route path="/interview/start" element={<OralInterviewPage />} />
            <Route path="/interview/:token/start" element={<OralInterviewPage />} />
            <Route path="/interview/:token" element={<OralInterviewGate />} />
            <Route path="/interview" element={<OralInterviewGate />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </LoadingBarProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
