import loadingGif from "./assets/loadingTenor.gif";
import validator from "validator";
import mockPriceObservations from "./data/mockPriceObservations.json";
import mockReporterMentions from "./data/mockReporterMentions.json";
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
const DEMO_WATCH_URL = "https://www.prisma.fi/";
const DEMO_REPORTER_CONCEPT = "climate change";

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
      {items.length === 0 ? (
        <p>No mention data is available for this concept yet.</p>
      ) : (
        <ul style={{ listStyleType: "none", paddingLeft: "10px" }}>
          {items.map((item) => (
            <li key={item.id}>
              <a href={item.source_url} target="_blank" rel="noreferrer">
                {item.title}
              </a>
              <br />
              From {item.source_name}
              <br />
              Published on {new Date(item.published_at).toLocaleDateString()}
              <br />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function getDailyMentionHistory(mentions) {
  const mentionsByDay = new Map();
  mentions.forEach((mention) => {
    const publishedAt = new Date(mention.published_at);
    if (Number.isNaN(publishedAt.getTime())) return;

    const day = publishedAt.toISOString().slice(0, 10);
    mentionsByDay.set(day, (mentionsByDay.get(day) ?? 0) + 1);
  });

  return [...mentionsByDay.entries()]
    .map(([day, prevalence]) => ({
      observed_at: `${day}T12:00:00.000Z`,
      prevalence,
    }))
    .sort(
      (a, b) =>
        new Date(a.observed_at).getTime() -
        new Date(b.observed_at).getTime(),
    );
}

function productNameFromObservation(observation) {
  const extractedProduct = observation.extracted_product;
  const extracted = extractedProduct?.extracted ?? extractedProduct;
  return (
    observation.product_name ??
    extracted?.product_name ??
    extracted?.name ??
    extracted?.product?.name ??
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

function getAveragePriceHistory(observations = []) {
  const latestProductPricesByDay = new Map();

  observations.forEach((observation) => {
    const productId = observation.listing_id ?? observation.source_url;
    const price = Number(observation.price);
    const observedAt = new Date(observation.observed_at);
    if (
      !productId ||
      observation.price == null ||
      observation.price === "" ||
      !Number.isFinite(price) ||
      price < 0 ||
      Number.isNaN(observedAt.getTime())
    ) {
      return;
    }

    const date = observedAt.toISOString().slice(0, 10);
    const currency =
      String(observation.currency ?? "")
        .trim()
        .toUpperCase() || "Unknown";
    const key = `${date}:${currency}:${productId}`;
    const existing = latestProductPricesByDay.get(key);
    if (!existing || observedAt > existing.observedAt) {
      latestProductPricesByDay.set(key, {
        date,
        currency,
        price,
        observedAt,
      });
    }
  });

  const dailyAverages = new Map();
  latestProductPricesByDay.forEach(({ date, currency, price }) => {
    const key = `${date}:${currency}`;
    const average = dailyAverages.get(key) ?? {
      date,
      currency,
      total: 0,
      count: 0,
    };
    average.total += price;
    average.count += 1;
    dailyAverages.set(key, average);
  });

  return [...dailyAverages.values()]
    .map(({ date, currency, total, count }) => ({
      observed_at: `${date}T12:00:00.000Z`,
      price: total / count,
      currency,
    }))
    .sort(
      (a, b) =>
        new Date(a.observed_at).getTime() - new Date(b.observed_at).getTime(),
    );
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
  const mockMode =
    import.meta.env.DEV &&
    new URLSearchParams(window.location.search).get("mockData") === "true";

  if (mockMode) {
    return mockPriceObservations.observations.filter((observation) => {
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

function AveragePriceCard({
  products,
  selectedProduct,
  onSelectProduct,
  isMockModeEnabled,
}) {
  return (
    <div className="average-price-card">
      <div className="average-price-card-header">
        <h2>Average Price</h2>
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
          {selectedProduct.sourceUrl && !isMockModeEnabled && (
            <a
              href={selectedProduct.sourceUrl}
              target="_blank"
              rel="noreferrer"
            >
              View product
            </a>
          )}
          <h3>Selected product price history</h3>
          <HistoryChart
            observations={selectedProduct.observations}
            valueKey="price"
            yAxisLabel="Price"
            seriesBy="currency"
            emptyMessage="No price history is available for this product."
          />
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
  const [isDeleteDataConfirmationOpen, setIsDeleteDataConfirmationOpen] =
    useState(false);
  const [isDeletingUserData, setIsDeletingUserData] = useState(false);
  const [isMockModeEnabled, setIsMockModeEnabled] = useState(
    () =>
      import.meta.env.DEV &&
      new URLSearchParams(window.location.search).get("mockData") === "true",
  );

  const userId = session?.user?.id;
  const dropdownElRef = useRef(null);
  const deleteDataCancelButtonRef = useRef(null);
  const visibleUserItemsList = useMemo(
    () => filterWatchlistForRole(userItemsList, reporterOrOwner),
    [reporterOrOwner, userItemsList],
  );
  const topProducts = useMemo(
    () => getTopProducts(rawMetricsData ?? []),
    [rawMetricsData],
  );
  const averagePriceHistory = useMemo(
    () => getAveragePriceHistory(rawMetricsData ?? []),
    [rawMetricsData],
  );
  const reporterMentions = useMemo(() => {
    if (
      !isMockModeEnabled ||
      reporterOrOwner !== REPORTER ||
      !trackedConcept
    ) {
      return [];
    }

    const concept = trackedConcept.trim().toLowerCase();
    return mockReporterMentions.mentions
      .filter((mention) => mention.concept.trim().toLowerCase() === concept)
      .sort(
        (a, b) =>
          new Date(b.published_at).getTime() -
          new Date(a.published_at).getTime(),
      );
  }, [isMockModeEnabled, reporterOrOwner, trackedConcept]);
  const reporterMentionHistory = useMemo(
    () => getDailyMentionHistory(reporterMentions),
    [reporterMentions],
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
    if (!isDeleteDataConfirmationOpen) return;

    deleteDataCancelButtonRef.current?.focus();
    function handleKeyDown(event) {
      if (event.key === "Escape" && !isDeletingUserData) {
        setIsDeleteDataConfirmationOpen(false);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isDeleteDataConfirmationOpen, isDeletingUserData]);

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
        setRawData(null);
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
    setError(null);
    setSuccessMessage(null);
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
      setWatchItem("");
      setUserType(userType);
    }
    setSavingUserType(false);
  }

  async function callWithWatchItemAsString() {
    setLoadingStatus(true);
    setError(null);
    setSuccessMessage(null);
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
    setError(null);
    setSuccessMessage(null);
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
      setWatchItem("");
      setUserType(newUserType);
    }
    setSavingUserType(false);
  }

  async function addToWatchlist() {
    setSuccessMessage(null);
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

      const deletedItem = userItemsList.find((item) => item.id === data.id);
      const demoItemUrl =
        reporterOrOwner === BUSINESS_OWNER
          ? DEMO_WATCH_URL
          : DEMO_REPORTER_CONCEPT;
      const isDemoItem = deletedItem?.item_url === demoItemUrl;
      const remainingItems = userItemsList.filter(
        (item) => item.id !== data.id,
      );
      setUserItemsList(remainingItems);
      if (trackedWatchItemId === data.id) {
        const nextItem = remainingItems[0] ?? null;
        setTrackedWatchItemId(nextItem?.id ?? null);
        setTrackedConcept(nextItem?.item_url ?? null);
      }
      if (trackedWatchItemId === data.id || isDemoItem) {
        setRawData(null);
        setFocusedProductId("");
      }
      if (isDemoItem) {
        const currentUrl = new URL(window.location.href);
        currentUrl.searchParams.delete("mockData");
        window.history.replaceState(window.history.state, "", currentUrl);
        setIsMockModeEnabled(false);
      }
      setSuccessMessage(
        isDemoItem
          ? "Demo item removed. Test mode has been turned off."
          : "Removed from your watchlist.",
      );
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

  async function deleteAllWatchlistItems() {
    if (!session?.user) {
      setError("Sign in before deleting your watchlist data.");
      return;
    }

    setIsDeletingUserData(true);
    setError(null);
    setSuccessMessage(null);
    let watchlistDeleted = false;

    try {
      const { error } = await supabase
        .from("watch_items")
        .delete()
        .eq("user_id", session.user.id);

      if (error) {
        console.error("Error deleting all watchlist items:", error.message);
        setError(`Could not delete watchlist data: ${error.message}`);
        return;
      }

      watchlistDeleted = true;
      setUserItemsList([]);
      setTrackedWatchItemId(null);
      setTrackedConcept(null);
      setRawData(null);
      setFocusedProductId("");
      setIsDeleteDataConfirmationOpen(false);

      const { error: signOutError } = await supabase.auth.signOut();
      if (signOutError) {
        console.error(
          "Error signing out after watchlist deletion:",
          signOutError.message,
        );
        setError(
          `Watchlist data was deleted, but sign out failed: ${signOutError.message}`,
        );
        return;
      }

      setSuccessMessage(
        "All watchlist items were deleted and you were signed out. Your Supabase account still exists.",
      );
      // TODO: Delete the Supabase Auth user through a server-side flow.
    } catch (requestError) {
      console.error("Error deleting all watchlist items:", requestError);
      setError(
        `${
          watchlistDeleted
            ? "Watchlist data was deleted, but sign out failed"
            : "Could not delete watchlist data"
        }: ${
          requestError instanceof Error ? requestError.message : "Unknown error"
        }`,
      );
    } finally {
      setIsDeletingUserData(false);
    }
  }

  async function enableTestMode() {
    if (!session?.user) {
      setError("Sign in before enabling test mode.");
      return;
    }
    if (![BUSINESS_OWNER, REPORTER].includes(reporterOrOwner)) {
      setError("Choose a user role before enabling test mode.");
      return;
    }
    if (askedAndLoading) return;

    const demoItemUrl =
      reporterOrOwner === BUSINESS_OWNER
        ? DEMO_WATCH_URL
        : DEMO_REPORTER_CONCEPT;

    setIsMenuOpen(false);
    setLoadingStatus(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const { data: existingItem, error: lookupError } = await supabase
        .from("watch_items")
        .select("id, item_url")
        .eq("user_id", session.user.id)
        .eq("item_url", demoItemUrl)
        .maybeSingle();

      if (lookupError) {
        throw new Error(lookupError.message);
      }

      let demoItem = existingItem;
      if (!demoItem) {
        const { data, error } = await supabase
          .from("watch_items")
          .insert({
            user_id: session.user.id,
            item_url: demoItemUrl,
          })
          .select("id, item_url")
          .single();

        if (error) {
          throw new Error(error.message);
        }
        if (!data) {
          throw new Error("Database returned no demo watchlist item.");
        }
        demoItem = data;
      }

      if (!demoItem) {
        throw new Error("Could not load the demo watchlist item.");
      }

      const currentUrl = new URL(window.location.href);
      currentUrl.searchParams.set("mockData", "true");
      window.history.replaceState(window.history.state, "", currentUrl);
      setIsMockModeEnabled(true);
      setUserItemsList((items) =>
        items.some((item) => item.id === demoItem.id)
          ? items
          : [...items, demoItem],
      );
      setTrackedWatchItemId(demoItem.id);
      setTrackedConcept(demoItemUrl);
      setSuccessMessage(
        reporterOrOwner === BUSINESS_OWNER
          ? "Test mode enabled with demo Prisma sample data."
          : "Test mode enabled with sample reporter mentions.",
      );
    } catch (requestError) {
      console.error("Could not enable test mode:", requestError);
      setError(
        `Could not enable test mode: ${
          requestError instanceof Error ? requestError.message : "Unknown error"
        }`,
      );
    } finally {
      setLoadingStatus(false);
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
  }, [
    isMockModeEnabled,
    reporterOrOwner,
    trackedWatchItemId,
    visibleUserItemsList,
  ]);

  const valInputValidURL = validator.isURL(watchItemAsString.trim(), {
    require_protocol: true,
  });

  const signInWithGoogle = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: window.location.origin,
        queryParams: { prompt: "select_account" },
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
                    {import.meta.env.DEV &&
                      [userType.businessOwner, userType.reporter].includes(
                        reporterOrOwner,
                      ) && (
                        <button
                          type="button"
                          onClick={enableTestMode}
                          disabled={askedAndLoading}
                          title={
                            reporterOrOwner === userType.businessOwner
                              ? "Adds a sample Prisma URL and uses fictional prices for layout testing."
                              : "Adds a sample concept and uses fictional mention data for layout testing."
                          }
                        >
                          {reporterOrOwner === userType.businessOwner
                            ? isMockModeEnabled
                              ? "Add Demo URL to Watchlist"
                              : "Test Mode: Add Demo URL"
                            : isMockModeEnabled
                              ? "Add Demo Concept to Watchlist"
                              : "Test Mode: Add Demo Concept"}
                        </button>
                      )}
                    <button
                      type="button"
                      onClick={() => {
                        setIsMenuOpen(false);
                        setError(null);
                        setIsDeleteDataConfirmationOpen(true);
                      }}
                    >
                      Delete My Data
                    </button>
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
          {!session && successMessage && (
            <p className="account-status-message" role="status">
              {successMessage}
            </p>
          )}
          {!session && error && (
            <p className="account-status-message" role="alert">
              {error}
            </p>
          )}
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
          {session && (
            <h2 style={{ marginBottom: "16px", textAlign: "center" }}>
              {reporterOrOwner === userType.businessOwner
                ? "Site Watchlist"
                : "Concept Watchlist"}
            </h2>
          )}

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
                  setError(null);
                  setSuccessMessage(null);
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
              {isMockModeEnabled && (
                <p className="mock-data-banner" role="status">
                  {reporterOrOwner === userType.businessOwner
                    ? "Demo data only — generated sample prices, not live Prisma listings."
                    : "Demo data only — fictional article mentions and sources for layout testing."}
                </p>
              )}
              <AveragePriceCard
                products={topProducts}
                selectedProduct={selectedProduct}
                onSelectProduct={setFocusedProductId}
                isMockModeEnabled={isMockModeEnabled}
              />
              <div className="price-chart-card business-price-chart-card">
                <h2>Average price over time</h2>
                <HistoryChart
                  observations={averagePriceHistory}
                  valueKey="price"
                  yAxisLabel="Average price"
                  seriesBy="currency"
                  emptyMessage="Average price history will appear when products have observations."
                />
              </div>
            </>
          )}
        {reporterOrOwner === userType.reporter && trackedConcept && (
          <>
            {isMockModeEnabled && (
              <p className="mock-data-banner" role="status">
                Demo data only — fictional article mentions and sources for
                layout testing.
              </p>
            )}
            <div className="price-chart-card">
              <h2>Mentions over time</h2>
              <HistoryChart
                observations={reporterMentionHistory}
                valueKey="prevalence"
                yAxisLabel="Stories published"
                emptyMessage={
                  isMockModeEnabled
                    ? `No demo mentions are available for ${trackedConcept}.`
                    : `External mention history for ${trackedConcept} will appear here once its Supabase data source is connected.`
                }
              />
            </div>
            <TopThreeListCard
              title={`Top 3 Mentions of ${trackedConcept[0].toUpperCase() + trackedConcept.slice(1)}`}
              items={reporterMentions.slice(0, 3)}
            />
          </>
        )}
      </section>
      {isDeleteDataConfirmationOpen && (
        <div
          className="delete-data-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget && !isDeletingUserData) {
              setIsDeleteDataConfirmationOpen(false);
            }
          }}
        >
          <section
            className="delete-data-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-data-title"
            aria-describedby="delete-data-description"
          >
            <h2 id="delete-data-title">Delete My Data?</h2>
            <p id="delete-data-description">
              This permanently deletes all of your saved watchlist items,
              including concepts and URLs from every role. Your Supabase account
              will remain active, and you will be signed out afterward.
            </p>
            <div className="delete-data-actions">
              <button
                type="button"
                className="delete-data-cancel"
                ref={deleteDataCancelButtonRef}
                onClick={() => {
                  setIsDeleteDataConfirmationOpen(false);
                }}
                disabled={isDeletingUserData}
              >
                Cancel
              </button>
              <button
                type="button"
                className="delete-data-confirm"
                onClick={deleteAllWatchlistItems}
                disabled={isDeletingUserData}
              >
                {isDeletingUserData ? "Deleting..." : "Delete watchlist data"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

export default App;
