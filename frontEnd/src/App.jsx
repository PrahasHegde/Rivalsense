import loadingGif from "./assets/loadingTenor.gif";
import validator from "validator";
import { useState, useEffect, useRef } from "react";
import { supabase } from "./supabase";
import "./App.css";

function App() {
  const [session, setSession] = useState(null);
  const [watchItemAsString, setWatchItem] = useState("");
  const [rawMetricsData, setRawData] = useState(null);
  const [askedAndLoading, setLoadingStatus] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [reporterOrOwner, setUserType] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [savingUserType, setSavingUserType] = useState(false);

  const [isMenuOpen, setIsMenuOpen] = useState(false);

  const dropdownElRef = useRef(null);

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
    function handleClickOutside(event) {
      if (
        isMenuOpen &&
        dropdownElRef.current &&
        !dropdownElRef.current.contains(event.target)
      ) {
        setIsMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isMenuOpen]);

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

  async function callWithWatchItemAsString() {
    setLoadingStatus(true);
    setError(null);
    setRawData(null);
    const urlToUse = watchItemAsString.trim();
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

  async function toggleUserType() {
    if (!session?.user || savingUserType) return;

    const newUserType =
      reporterOrOwner === userType.businessOwner
        ? userType.reporter
        : userType.businessOwner;

    setSavingUserType(true);
    const { error } = await supabase.from("profiles").upsert(
      {
        id: session.user.id,
        email: session.user.email,
        user_type: newUserType,
      },
      { onConflict: "id" },
    );

    if (error) {
      console.error("Error changing profile:", error.message);
      setError(error.message);
    } else {
      setUserType(newUserType);
    }
    setSavingUserType(false);
  }

  async function addToWatchlist() {
    if (!session?.user) {
      setError("Sign in before adding a watch item.");
      return;
    }
    if (reporterOrOwner !== userType.reporter || askedAndLoading) {
      return;
    }

    const preppedItem = watchItemAsString.trim();
    if (preppedItem === "") {
      setError("Enter a concept to add to your watchlist.");
      return;
    }

    setLoadingStatus(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const { error } = await supabase.from("watch_items").insert({
        user_id: session.user.id,
        item_url: preppedItem,
      });

      if (error) {
        console.error("Error adding watch item:", error.message);
        setError(`Could not add the watch item: ${error.message}`);
        return;
      }

      setWatchItem("");
      setSuccessMessage("Added to your watchlist.");
    } catch (requestError) {
      console.error("Error adding watch item:", requestError);
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not add the watch item.",
      );
    } finally {
      setLoadingStatus(false);
    }
  }

  const valInputValidURL = validator.isURL(watchItemAsString.trim(), {
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

  const avatarUrl = session?.user?.user_metadata?.avatar_url;

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
            {avatarUrl && (
              <div className="profilePhotoWrapper" ref={dropdownElRef}>
                <button
                  type="button"
                  className="profile-menu-trigger"
                  aria-label="Open profile menu"
                  aria-expanded={isMenuOpen}
                  aria-controls="profile-menu"
                  onClick={() => setIsMenuOpen((open) => !open)}
                >
                  <img src={avatarUrl} alt="" className="profile-pic" />
                </button>
                {isMenuOpen && (
                  <nav
                    className="dropdown-menu"
                    id="profile-menu"
                    aria-label="Profile"
                  >
                    <a href="#dashboard" onClick={() => setIsMenuOpen(false)}>
                      Dashboard
                    </a>
                    <a href="#watchlist" onClick={() => toggleUserType()}>
                      Toggle Role:
                      {reporterOrOwner === userType.businessOwner
                        ? " Business Owner"
                        : " Reporter"}
                    </a>
                    <a href="#account" onClick={() => setIsMenuOpen(false)}>
                      Account settings
                    </a>
                  </nav>
                )}
              </div>
            )}
            <button className="sign-out-button" onClick={signOut}>
              Sign Out
            </button>
          </>
        )}
      </div>

      <section id="center">
        <div>
          {reporterOrOwner == userType.businessOwner && (
            <h1>
              Are you ready to get a sense for your rivals' strengths? <br />{" "}
              ...And
              <b> weaknesses</b>?
            </h1>
          )}

          {reporterOrOwner == userType.reporter && (
            <h1>
              Let us keep in touch with the world, <br />
              <b>so you can keep in touch with your writing.</b>
            </h1>
          )}

          {reporterOrOwner == null && (
            <h1>
              We help you track current events, products, competitors, buzz, and
              more.
            </h1>
          )}

          {!session ? (
            <>
              <h2>
                And we're ready to help! Just log in with Google, and we'll
                handle the reconnaissance so you can handle rolling around in
                success.
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
              {reporterOrOwner === userType.businessOwner && (
                <p>Type your storefront's url below...</p>
              )}
              {reporterOrOwner === userType.reporter && (
                <p>What concept do you want to track?</p>
              )}

              <div className="inputs">
                <input
                  type="text"
                  value={watchItemAsString}
                  placeholder={
                    reporterOrOwner === userType.reporter
                      ? "Enter a concept"
                      : "Enter a storefront URL"
                  }
                  onChange={(event) => {
                    setWatchItem(event.target.value);
                    setError(null);
                    setSuccessMessage(null);
                  }}
                />
                <button
                  onClick={() => {
                    setError(null);
                    setSuccessMessage(null);
                    if (reporterOrOwner === userType.businessOwner) {
                      if (valInputValidURL) {
                        callWithWatchItemAsString();
                      } else {
                        setError(ErrorType.urlInvalid);
                      }
                    } else if (reporterOrOwner === userType.reporter) {
                      addToWatchlist();
                    }
                  }}
                  disabled={askedAndLoading}
                >
                  {reporterOrOwner === userType.reporter
                    ? "Add Concept to Watchlist"
                    : "Add Site to Watchlist"}
                </button>
              </div>
              {askedAndLoading && (
                <div className="loading-container">
                  <img src={loadingGif} alt="Loading..." />
                </div>
              )}
              {error && <p role="alert">{error}</p>}
              {successMessage && <p role="status">{successMessage}</p>}
            </>
          )}
        </div>
      </section>
    </>
  );
}

export default App;
