import { supabase } from "../supabase";
import { createApi } from "./apiClient";
export const api = createApi({ auth: supabase?.auth, baseUrl: import.meta.env.VITE_API_BASE_URL || "" });
