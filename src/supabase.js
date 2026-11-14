import { createClient } from "@supabase/supabase-js";
const supabaseUrl = "https://ttkyqvlyulkzmbfzdzwd.supabase.co";
const supabaseKey = "sb_publishable_Woumh0tUvZY0_0CNeeDZdw_qIJSCPQj";
export const supabase = createClient(supabaseUrl, supabaseKey);
