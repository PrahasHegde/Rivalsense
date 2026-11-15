import { useEffect, useState } from "react";
import { supabase } from "../supabase";

export function useRivalSession() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(Boolean(supabase));
  const [error, setError] = useState("");
  const [profile, setProfile] = useState(null);
  const userId = session?.user?.id;
  useEffect(() => {
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(({ data, error }) => {
      if (!active) return;
      setSession(data?.session || null); setLoading(false);
      if (error) setError("Could not restore your session. Please sign in again.");
    }).catch(() => { if (active) { setError("Could not connect to sign-in."); setLoading(false); } });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, value) => {
      if (active) { setSession(value); setLoading(false); }
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, []);
  useEffect(() => {
    let active = true;
    if (userId && supabase) {
      // Reuse Rebecca's optional profile preference; a missing profile never blocks research.
      supabase.from("profiles").select("user_type").eq("id", userId).maybeSingle()
        .then(({ data }) => { if (active) setProfile({ owner: userId, type: data?.user_type || null }); })
        .catch(() => {});
    }
    return () => { active = false; };
  }, [userId]);
  const signIn = async () => {
    setError("");
    if (!supabase) { setError("Add the Supabase public URL and publishable key to frontEnd/.env.local."); return; }
    try {
      const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
      if (error) setError("Google sign-in could not start. Check Supabase's allowed redirect URLs.");
    } catch { setError("Could not connect to Google sign-in."); }
  };
  const signOut = async () => {
    try { const { error } = await supabase.auth.signOut(); if (error) setError("Sign-out failed. Please try again."); }
    catch { setError("Sign-out failed. Please try again."); }
  };
  return { session, loading, error, audience: profile && profile.owner === userId ? profile.type : null, signIn, signOut };
}
