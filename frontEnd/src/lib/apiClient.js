export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.name = "ApiError"; this.status = status; }
}
export function createApi({ auth, baseUrl = "", fetchImpl = fetch, timeoutMs = 90000 }) {
  return async function request(path, { method = "GET", body, signal } = {}) {
    if (!path.startsWith("/api/")) throw new ApiError("Unsupported API route");
    if (!auth) throw new ApiError("Supabase is not configured. See the local setup guide.", 503);
    let { data, error } = await auth.getSession();
    if (error || !data?.session) throw new ApiError("Sign in with Google to continue.", 401);
    if (data.session.expires_at && data.session.expires_at * 1000 < Date.now() + 30000) {
      const refreshed = await auth.refreshSession();
      if (refreshed.error || !refreshed.data?.session) throw new ApiError("Your session expired. Please sign in again.", 401);
      data = refreshed.data;
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(abort, timeoutMs);
    try {
      const response = await fetchImpl(baseUrl.replace(/\/$/, "") + path, {
        method, headers: { "Authorization": "Bearer " + data.session.access_token,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: controller.signal,
      });
      let payload;
      try { payload = await response.json(); } catch {
        if (response.status === 401) throw new ApiError("Your session is no longer valid. Please sign in again.", 401);
        if ([502, 503, 504].includes(response.status)) {
          throw new ApiError(`RivalSense API is unavailable (HTTP ${response.status}). The API service may be starting or restarting. Please try again shortly.`, response.status);
        }
        throw new ApiError(response.ok
          ? "The API returned an unexpected response format. Check the API URL and Vite proxy configuration."
          : `The API request failed (HTTP ${response.status}) without a JSON error response. Please try again.`, response.status);
      }
      if (!response.ok) {
        const detail = typeof payload?.detail === "string" ? payload.detail : "The request could not be completed.";
        throw new ApiError(response.status === 401 ? "Your session is no longer valid. Please sign in again." : detail, response.status);
      }
      return payload;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (controller.signal.aborted) {
        if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
        throw new ApiError("The request timed out. Try a more focused question.", 504);
      }
      throw new ApiError("Cannot reach RivalSense API. Check that FastAPI is running and the API URL is correct.");
    } finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
  };
}
