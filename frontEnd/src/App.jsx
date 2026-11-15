import loadingGif from "./assets/loadingTenor.gif";
import validator from "validator";
import { useState, useEffect, useMemo, useRef } from "react";
import { supabase } from "./supabase";
import {
  CategoryScale,
  Chart,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";
import "./App.css";

Chart.register(
  CategoryScale,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
);

const BUSINESS_OWNER = "business_owner";
const REPORTER = "reporter";

function filterWatchlistForRole(items, role) {
  if (role === BUSINESS_OWNER) {
    return items.filter((item) =>
      validator.isURL(item.item_url, { require_protocol: true }),
    );
  }
  if (role === REPORTER) {
    return items.filter(
      (item) => !validator.isURL(item.item_url, { require_protocol: true }),
    );
  }
  return [];
}

function HistoryChart({
  observations,
  valueKey,
  yAxisLabel,
  seriesBy = null,
  emptyMessage,
}) {
  const canvasRef = useRef(null);

  const points = useMemo(
    () =>
      observations
        .map((observation) => ({
          observedAt: new Date(observation.observed_at),
          value:
            observation[valueKey] == null || observation[valueKey] === ""
              ? Number.NaN
              : Number(observation[valueKey]),
          series: seriesBy
            ? String(observation[seriesBy] ?? "")
                .trim()
                .toUpperCase() || "Unknown"
            : null,
        }))
        .filter(
          (point) =>
            !Number.isNaN(point.observedAt.getTime()) &&
            Number.isFinite(point.value),
        )
        .sort((a, b) => a.observedAt - b.observedAt),
    [observations, seriesBy, valueKey],
  );

  useEffect(() => {
    if (!canvasRef.current || points.length === 0) return;

    const series = seriesBy
      ? [...new Set(points.map((point) => point.series))]
      : [null];
    const colors = ["#034263", "#a73bff", "#d65a31", "#238636"];
    const chart = new Chart(canvasRef.current, {
      type: "line",
      data: {
        labels: points.map((point) => point.observedAt.toLocaleString()),
        datasets: series.map((seriesValue, index) => ({
          label: seriesValue
            ? seriesValue === "Unknown"
              ? `${yAxisLabel} (unknown ${seriesBy})`
              : `${yAxisLabel} (${seriesValue})`
            : yAxisLabel,
          data: points.map((point) =>
            seriesValue === null || point.series === seriesValue
              ? point.value
              : null,
          ),
          borderColor: colors[index % colors.length],
          backgroundColor: colors[index % colors.length],
          tension: 0.25,
          spanGaps: false,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            title: { display: true, text: "Observed at" },
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: yAxisLabel },
          },
        },
      },
    });

    return () => chart.destroy();
  }, [points, seriesBy, yAxisLabel]);

  if (points.length === 0) {
    return <p>{emptyMessage}</p>;
  }

  return (
    <div className="price-chart">
      <canvas ref={canvasRef} aria-label={`${yAxisLabel} history line chart`} />
    </div>
  );
}

function TopThreeListCard({ title, items }) {
  return (
    <div className="top-three-list-card">
      <h2>{title}</h2>
      <ul style={{ listStyleType: "none", paddingLeft: "10px" }}>
        {items.map((item, index) => (
          <li key={index}>
            {item} (title of news story) <br />
            From (source of news story) <br />
            Published on (date of news story) <br />
          </li>
        ))}
      </ul>
    </div>
  );
}

function productNameFromObservation(observation) {
  const extractedProduct = observation.extracted_product;
  return (
    observation.product_name ??
    extractedProduct?.product_name ??
    extractedProduct?.name ??
    extractedProduct?.product?.name ??
    null
  );
}

function getTopProducts(observations = []) {
  const groupedProducts = new Map();

  observations.forEach((observation) => {
    const id = observation.listing_id ?? observation.source_url;
    if (!id) return;

    const product = groupedProducts.get(id) ?? {
      id,
      name: null,
      observations: [],
    };
    product.name ??= productNameFromObservation(observation);
    product.observations.push(observation);
    groupedProducts.set(id, product);
  });

  return [...groupedProducts.values()]
    .map((product) => {
      const pricedObservations = product.observations
        .filter((observation) => {
          const price = Number(observation.price);
          const observedAt = new Date(observation.observed_at).getTime();
          return (
            observation.price != null &&
            observation.price !== "" &&
            Number.isFinite(price) &&
            price >= 0 &&
            Number.isFinite(observedAt)
          );
        })
        .sort(
          (a, b) =>
            new Date(a.observed_at).getTime() -
            new Date(b.observed_at).getTime(),
        );
      const latestObservation = pricedObservations.at(-1);
      if (!latestObservation) return null;

      const sourceUrl =
        latestObservation.source_url ??
        product.observations[0]?.source_url ??
        null;
      let name = product.name;
      if (!name && sourceUrl) {
        try {
          const productUrl = new URL(sourceUrl);
          const pathName = productUrl.pathname
            .split("/")
            .filter(Boolean)
            .at(-1);
          name = pathName
            ? decodeURIComponent(pathName).replace(/[-_]+/g, " ")
            : productUrl.hostname;
        } catch {
          name = sourceUrl;
        }
      }

      return {
        ...product,
        name: name ?? "Tracked product",
        sourceUrl,
        currentPrice: latestObservation.price,
        currency: latestObservation.currency,
      };
    })
    .filter(Boolean)
    .sort(
      (a, b) =>
        Number(a.currentPrice) - Number(b.currentPrice) ||
        a.name.localeCompare(b.name),
    )
    .slice(0, 5);
}

function formatPrice(price, currency) {
  const amount = Number(price);
  if (!Number.isFinite(amount)) return "Price unavailable";

  const currencyCode = String(currency ?? "")
    .trim()
    .toUpperCase();
  if (/^[A-Z]{3}$/.test(currencyCode)) {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currencyCode,
    }).format(amount);
  }
  return amount.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

async function fetchCompetitorObservations(competitorUrl) {
  const host = new URL(competitorUrl).hostname
    .toLowerCase()
    .replace(/^www\./, "");
  const { data, error } = await supabase
    .from("price_observations")
    .select("*")
    .ilike("source_url", `%${host}%`);

  if (error) {
    throw new Error(error.message);
  }

  return (data ?? []).filter((observation) => {
    try {
      return (
        new URL(observation.source_url).hostname
          .toLowerCase()
          .replace(/^www\./, "") === host
      );
    } catch {
      return false;
    }
  });
}

function AveragePriceCard({ products, selectedProduct, onSelectProduct }) {
  return (
    <div className="average-price-card">
      <div className="average-price-card-header">
        <h2>Competitor products</h2>
        <select
          aria-label="Choose a competitor product"
          value={selectedProduct?.id ?? ""}
          onChange={(event) => onSelectProduct(event.target.value)}
          disabled={products.length === 0}
        >
          {products.length === 0 ? (
            <option value="">No products available</option>
          ) : (
            products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))
          )}
        </select>
      </div>
      <p className="product-ranking-note">
        Showing up to five observed products ranked by latest price. Sales data
        is unavailable.
      </p>
      {!selectedProduct ? (
        <p>
          No saved product observations were found for this competitor. The
          current service records individual product pages; it does not discover
          a store catalog.
        </p>
      ) : (
        <>
          <p className="product-current-price">
            Current observed price:{" "}
            <strong>
              {formatPrice(
                selectedProduct.currentPrice,
                selectedProduct.currency,
              )}
            </strong>
          </p>
          {selectedProduct.sourceUrl && (
            <a
              href={selectedProduct.sourceUrl}
              target="_blank"
              rel="noreferrer"
            >
              View product
            </a>
          )}
        </>
      )}
    </div>
  );
}

function App() {
  const [session, setSession] = useState(null);
  const [watchItemAsString, setWatchItem] = useState("");
  const [rawMetricsData, setRawData] = useState(null);
  const [focusedProductId, setFocusedProductId] = useState("");
  const [trackedConcept, setTrackedConcept] = useState(null);
  const [askedAndLoading, setLoadingStatus] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [reporterOrOwner, setUserType] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [savingUserType, setSavingUserType] = useState(false);
  const [userItemsList, setUserItemsList] = useState([]);
  const [trackedWatchItemId, setTrackedWatchItemId] = useState(null);
  const [deletingWatchItemId, setDeletingWatchItemId] = useState(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  const userId = session?.user?.id;
  const dropdownElRef = useRef(null);
  const visibleUserItemsList = useMemo(
    () => filterWatchlistForRole(userItemsList, reporterOrOwner),
    [reporterOrOwner, userItemsList],
  );
  const topProducts = useMemo(
    () => getTopProducts(rawMetricsData ?? []),
    [rawMetricsData],
  );
  const selectedProduct =
    topProducts.find((product) => product.id === focusedProductId) ??
    topProducts[0] ??
    null;

  const ErrorType = {
    urlInvalid: "The given URL is invalid.",
    backendApiError: "Issue with recon server",
    renderingIssue: "Issue with rendering diagrams or data",
  };

  const userType = {
    businessOwner: BUSINESS_OWNER,
    reporter: REPORTER,
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
      if (!session?.user) {
        setUserItemsList([]);
        setTrackedWatchItemId(null);
        setTrackedConcept(null);
      }
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
      setUserItemsList([]);
      setTrackedWatchItemId(null);
      setTrackedConcept(null);
      setRawData(null);
      setUserType(userType);
    }
    setSavingUserType(false);
  }

  async function callWithWatchItemAsString() {
    setLoadingStatus(true);
    setError(null);
    setRawData(null);
    const urlToUse = watchItemAsString.trim();
    try {
      const competitorObservations =
        await fetchCompetitorObservations(urlToUse);
      setFocusedProductId("");
      setRawData(competitorObservations);
    } catch (requestError) {
      console.error("Error loading price observations:", requestError);
      setError(
        `${ErrorType.backendApiError}: ${
          requestError instanceof Error ? requestError.message : "Unknown error"
        }`,
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
      setUserItemsList([]);
      setTrackedWatchItemId(null);
      setTrackedConcept(null);
      setRawData(null);
      setUserType(newUserType);
    }
    setSavingUserType(false);
  }

  async function addToWatchlist() {
    if (!session?.user) {
      setError("Sign in before adding a watch item.");
      return;
    }
    if (
      ![userType.reporter, userType.businessOwner].includes(reporterOrOwner) ||
      askedAndLoading
    ) {
      return;
    }

    const preppedItem = watchItemAsString.trim();
    if (preppedItem === "") {
      setError(
        reporterOrOwner === userType.businessOwner
          ? "Enter a URL to add to your watchlist."
          : "Enter a concept to add to your watchlist.",
      );
      return;
    }
    if (
      reporterOrOwner === userType.businessOwner &&
      !validator.isURL(preppedItem, { require_protocol: true })
    ) {
      setError(ErrorType.urlInvalid);
      return;
    }

    setLoadingStatus(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const { data, error } = await supabase
        .from("watch_items")
        .insert({
          user_id: session.user.id,
          item_url: preppedItem,
        })
        .select("id")
        .single();

      if (error) {
        console.error("Error adding watch item:", error.message);
        setError(`Could not add the watch item: ${error.message}`);
        return;
      }

      setTrackedConcept(preppedItem);
      setWatchItem("");
      setSuccessMessage("Added to your watchlist.");
      setTrackedWatchItemId(data.id);
      setUserItemsList((prevList) => [
        ...prevList,
        { item_url: preppedItem, id: data.id },
      ]);
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

  async function deleteWatchItem(itemId) {
    if (!session?.user) {
      setError("Sign in before deleting a watch item.");
      return;
    }
    if (deletingWatchItemId !== null) return;

    setDeletingWatchItemId(itemId);
    setError(null);
    setSuccessMessage(null);

    try {
      const { data, error } = await supabase
        .from("watch_items")
        .delete()
        .eq("id", itemId)
        .eq("user_id", session.user.id)
        .select("id")
        .maybeSingle();

      if (error) {
        console.error("Error deleting watch item:", error.message);
        setError(`Could not delete the watch item: ${error.message}`);
        return;
      }
      if (!data) {
        setError("The watch item was not found or could not be deleted.");
        return;
      }

      const remainingItems = userItemsList.filter(
        (item) => item.id !== data.id,
      );
      setUserItemsList(remainingItems);
      if (trackedWatchItemId === data.id) {
        const nextItem = remainingItems[0] ?? null;
        setTrackedWatchItemId(nextItem?.id ?? null);
        setTrackedConcept(nextItem?.item_url ?? null);
      }
      setSuccessMessage("Removed from your watchlist.");
    } catch (requestError) {
      console.error("Error deleting watch item:", requestError);
      setError(
        `Could not delete the watch item: ${
          requestError instanceof Error ? requestError.message : "Unknown error"
        }`,
      );
    } finally {
      setDeletingWatchItemId(null);
    }
  }

  async function fetchWatchlist(userId, role) {
    const { data, error } = await supabase
      .from("watch_items")
      .select("id, item_url")
      .eq("user_id", userId);

    if (error) {
      throw new Error(error.message);
    }

    return filterWatchlistForRole(
      (data ?? []).map((item) => ({
        item_url: item.item_url,
        id: item.id,
      })),
      role,
    );
  }

  useEffect(() => {
    let isCurrent = true;

    if (!userId || ![BUSINESS_OWNER, REPORTER].includes(reporterOrOwner)) {
      return () => {
        isCurrent = false;
      };
    }

    async function loadWatchlist() {
      try {
        const items = await fetchWatchlist(userId, reporterOrOwner);
        if (isCurrent) {
          setUserItemsList(items);
          const currentItem = items[0] ?? null;
          setTrackedWatchItemId(currentItem?.id ?? null);
          setTrackedConcept(currentItem?.item_url ?? null);
        }
      } catch (requestError) {
        if (!isCurrent) return;
        console.error("Error fetching watchlist:", requestError);
        setError(
          `Could not fetch watchlist: ${
            requestError instanceof Error
              ? requestError.message
              : "Unknown error"
          }`,
        );
      }
    }

    loadWatchlist();
    return () => {
      isCurrent = false;
    };
  }, [reporterOrOwner, userId]);

  useEffect(() => {
    let isCurrent = true;
    const activeItem = visibleUserItemsList.find(
      (item) => item.id === trackedWatchItemId,
    );

    if (reporterOrOwner !== BUSINESS_OWNER || !activeItem?.item_url) {
      return () => {
        isCurrent = false;
      };
    }

    async function loadTrackedItemObservations() {
      setLoadingStatus(true);
      setError(null);
      setRawData(null);
      try {
        const observations = await fetchCompetitorObservations(
          activeItem.item_url,
        );
        if (isCurrent) {
          setFocusedProductId("");
          setRawData(observations);
        }
      } catch (requestError) {
        if (!isCurrent) return;
        console.error("Error loading tracked item observations:", requestError);
        setError(
          `Could not load tracked item price history: ${
            requestError instanceof Error
              ? requestError.message
              : "Unknown error"
          }`,
        );
      } finally {
        if (isCurrent) setLoadingStatus(false);
      }
    }

    loadTrackedItemObservations();
    return () => {
      isCurrent = false;
    };
  }, [reporterOrOwner, trackedWatchItemId, visibleUserItemsList]);

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
                  onKeyPress={(event) => {
                    if (event.key === "Enter") {
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
                    }
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
                    : "Check Price History"}
                </button>
                {reporterOrOwner === userType.businessOwner && (
                  <button onClick={addToWatchlist} disabled={askedAndLoading}>
                    Add Site to Watchlist
                  </button>
                )}
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
      <section id="watchlist">
        <>
          <h2 style={{ marginBottom: "16px", textAlign: "center" }}>
            {reporterOrOwner === userType.businessOwner
              ? "Site Watchlist"
              : "Concept Watchlist"}
          </h2>
          <div className="watchListGroup">
            {visibleUserItemsList.map((item) => (
              <div
                key={item.id}
                className={`watchlist-item${
                  trackedWatchItemId === item.id ? " is-tracked" : ""
                }`}
                onClick={() => {
                  setTrackedWatchItemId(item.id);
                  setTrackedConcept(item.item_url);
                }}
              >
                <button
                  type="button"
                  className="watchlist-select-button"
                  aria-pressed={trackedWatchItemId === item.id}
                >
                  {item.item_url}
                </button>
                {reporterOrOwner === userType.businessOwner &&
                  validator.isURL(item.item_url, {
                    require_protocol: true,
                  }) && (
                    <a href={item.item_url} target="_blank" rel="noreferrer">
                      Open URL
                    </a>
                  )}
                <button
                  type="button"
                  className="watchlist-delete-button"
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteWatchItem(item.id);
                  }}
                  aria-label={`Delete ${item.item_url} from watchlist`}
                  disabled={deletingWatchItemId !== null}
                >
                  {deletingWatchItemId === item.id ? "Deleting..." : "Delete"}
                </button>
              </div>
            ))}
          </div>
        </>
      </section>
      <section id="dashboard">
        {reporterOrOwner === userType.businessOwner &&
          rawMetricsData !== null && (
            <>
              <AveragePriceCard
                products={topProducts}
                selectedProduct={selectedProduct}
                onSelectProduct={setFocusedProductId}
              />
              <div className="price-chart-card business-price-chart-card">
                <h2>Price over time</h2>
                {selectedProduct ? (
                  <HistoryChart
                    observations={selectedProduct.observations}
                    valueKey="price"
                    yAxisLabel="Price"
                    seriesBy="currency"
                    emptyMessage="No price history is available for this product."
                  />
                ) : (
                  <p>
                    Price history will appear here when product observations are
                    available.
                  </p>
                )}
              </div>
            </>
          )}
        {reporterOrOwner === userType.reporter && trackedConcept && (
          <>
            <div className="price-chart-card">
              <h2>Prevalence over time</h2>
              <HistoryChart
                observations={[]}
                valueKey="prevalence"
                yAxisLabel="Prevalence"
                emptyMessage={`External mention history for ${trackedConcept} will appear here once its Supabase data source is connected.`}
              />
            </div>
            <TopThreeListCard
              title={`Top 3 ${trackedConcept[0].toUpperCase() + trackedConcept.slice(1)} Mentions`}
              items={["Item 1", "Item 2", "Item 3"]}
            />
          </>
        )}
      </section>
    </>
  );
}

export default App;
