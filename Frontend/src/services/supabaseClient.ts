import { createClient } from "@supabase/supabase-js";

const env = import.meta.env as unknown as Record<string, string | undefined>;

const supabaseUrl = env.VITE_SUPABASE_URL ?? env.VITE_TEST_SUPABASE_URL;
const supabaseAnonKey =
  env.VITE_SUPABASE_ANON_KEY ?? env.VITE_TEST_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error("Missing Supabase environment variables.");
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: "digitrec-supabase-auth",
  },
});
