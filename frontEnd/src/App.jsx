import loadingGif from "./assets/loadingTenor.gif";
import validator from "validator";
import { useState, useEffect } from "react";
import { supabase } from "./supabase";
import "./App.css";

function App() {
  const [session, setSession] = useState(null);
  const [storeURL, setUrl] = useState("");
  const [rawMetricsData, setRawData] = useState(null);
  const [askedAndLoading, setLoadingStatus] = useState(false);
  const [error, setError] = useState(null);
  const [reporterOrOwner, setUserType] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [savingUserType, setSavingUserType] = useState(false);

  const ErrorType = {
    urlInvalid: "The given URL is invalid.",
    backendApiError: "Issue with recon server",
    renderingIssue: "Issue with rendering diagrams or data",
  };

  const userType = {
    businessOwner: "business_owner",
    reporter: "reporter",
  };

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    let isCurrent = true;

    async function loadProfile() {
      if (!session?.user) {
        setUserType(null);
        setProfileLoading(false);
        return;
      }

      setProfileLoading(true);
      const { data, error } = await supabase
        .from("profiles")
        .select("user_type")
        .eq("id", session.user.id)
        .maybeSingle();

      if (!isCurrent) return;

      if (error) {
        console.error("Error loading profile:", error.message);
        setUserType(null);
      } else {
        setUserType(data?.user_type ?? null);
      }
      setProfileLoading(false);
    }

    loadProfile();
    return () => {
      isCurrent = false;
    };
  }, [session]);

  async function chooseUserType(userType) {
    if (!session?.user || savingUserType) return;

    setSavingUserType(true);
    const { error } = await supabase.from("profiles").upsert(
      {
        id: session.user.id,
        email: session.user.email,
        user_type: userType,
      },
      { onConflict: "id" },
    );

    if (error) {
      console.error("Error saving profile:", error.message);
      setError(error.message);
    } else {
      setUserType(userType);
    }
    setSavingUserType(false);
  }

  async function callWithStoreUrl() {
    setLoadingStatus(true);
    setError(null);
    setRawData(null);
    const urlToUse = storeURL.trim();
    // console.log("urlToUse:", urlToUse);
    try {
      const { data, error } = await supabase
        .from("price_observations")
        .select("*")
        .eq("source_url", urlToUse);

      if (error) {
        console.error("Error loading price observations:", error.message);
        setError(`${ErrorType.backendApiError}: ${error.message}`);
        return;
      }
      console.log("Raw data received:", data);
      setRawData(data);
    } catch (requestError) {
      console.error("Error loading price observations:", requestError);
      setError(
        requestError instanceof Error
          ? requestError.message
          : ErrorType.backendApiError,
      );
    } finally {
      setLoadingStatus(false);
    }
  }

  const isValidStoreUrl = validator.isURL(storeURL.trim(), {
    require_protocol: true,
  });

  const signInWithGoogle = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: window.location.origin,
      },
    });

    if (error) {
      console.error("Error signing in with Google:", error.message);
    }
  };

  const signOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) console.error("Error signing out:", error.message);
  };

  return (
    <>
      <div className="topBar">
        {!session && (
          <button className="gsi-material-button" onClick={signInWithGoogle}>
            <div className="gsi-material-button-state"></div>
            <div className="gsi-material-button-content-wrapper">
              <div className="gsi-material-button-icon">
                <svg
                  version="1.1"
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 48 48"
                  xmlnsXlink="http://www.w3.org/1999/xlink"
                  style={{ display: "block" }}
                >
                  <path
                    fill="#EA4335"
                    d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
                  ></path>
                  <path
                    fill="#4285F4"
                    d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
                  ></path>
                  <path
                    fill="#FBBC05"
                    d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
                  ></path>
                  <path
                    fill="#34A853"
                    d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
                  ></path>
                  <path fill="none" d="M0 0h48v48H0z"></path>
                </svg>
              </div>
              <span className="gsi-material-button-contents">
                Sign in with Google
              </span>
              <span style={{ display: "none" }}>Sign in with Google</span>
            </div>
          </button>
        )}
        {session && (
          <>
            <img
              src={session.user.user_metadata.avatar_url}
              alt="Profile"
              className="profile-pic"
            />
            <button className="sign-out-button" onClick={signOut}>
              Sign Out
            </button>
          </>
        )}
      </div>

      <section id="center">
        <div>
          {savingUserType == userType.businessOwner && (
            <h1>
              Are you ready to get a sense for your rivals' strengths? <br />{" "}
              ...And
              <b> weaknesses</b>?
            </h1>
          )}

          {savingUserType == userType.reporter && (
            <h1>
              Let us keep in touch with the world, <br />
              <b>so you can keep in tough with your writing.</b>?
            </h1>
          )}
          <h1>
            Are you ready to get a sense for your rivals' strengths? <br />{" "}
            ...And
            <b> weaknesses</b>?
          </h1>
          {!session ? (
            <>
              <h2>
                And we're ready to help! Just log in with Google, and we'll
                handle the reconnaissance so you can handle rolling around in
                money.
              </h2>
            </>
          ) : profileLoading ? (
            <p role="status">Loading your profile...</p>
          ) : !reporterOrOwner ? (
            <div className="user-type-card">
              <h2>Choose the type that best describes you</h2>
              <p>This helps us tailor your storefront insights.</p>
              <div className="inputs">
                <button
                  onClick={() => chooseUserType(userType.businessOwner)}
                  disabled={savingUserType}
                >
                  Business Owner
                </button>
                <button
                  onClick={() => chooseUserType(userType.reporter)}
                  disabled={savingUserType}
                >
                  Reporter
                </button>
              </div>
              {error && <p role="alert">{error}</p>}
            </div>
          ) : (
            <>
              <p>Type your storefront's url below...</p>
              <div className="inputs">
                <input
                  type="text"
                  value={storeURL}
                  onChange={(event) => setUrl(event.target.value)}
                />
                <button
                  onClick={() => {
                    if (isValidStoreUrl) {
                      console.log(
                        "Valid URL, calling with storeURL:",
                        storeURL,
                      );
                      callWithStoreUrl(storeURL);
                    } else {
                      setError(ErrorType.urlInvalid);
                    }
                  }}
                  disabled={false}
                >
                  Add Site To Watchlist
                </button>
              </div>
              {askedAndLoading && (
                <div className="loading-container">
                  <img src={loadingGif} alt="Loading..." />
                </div>
              )}
              {error && <p role="alert">{error}</p>}
            </>
          )}
        </div>
      </section>
    </>
  );
}

export default App;
