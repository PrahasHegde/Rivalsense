# RivalSense: one Render Web Service

Prepared in the isolated `feature/hackathon-demo` workspace. Nothing has been pushed, merged, or deployed. The original `feature/trusted-price-history` worktree is unchanged.

## What will run

One Docker Web Service builds the existing React/JavaScript app and runs the existing Python FastAPI app. FastAPI serves the compiled frontend at `/`, static assets at `/assets/...`, and all existing `/api/...` routes. The browser uses relative `/api` URLs; there is no public Vite server and no second service. Render supplies HTTPS and the `PORT`; Uvicorn listens on `0.0.0.0:$PORT`.

The Blueprint uses one instance and one worker with explicit local demo read limits. Recording and cloud research-history writes stay off. No migration, SQL, database creation, disk, background worker, or schema change is included. Process-local quotas reset on restart and are not shared across deployments; this is the submission demo configuration, not a distributed quota system.

## 1. Review before publishing

Review the full demo branch, including its existing uncommitted React and backend implementation plus `Dockerfile`, `.dockerignore`, `render.yaml`, and production-serving changes. Local files and credentials must remain ignored. After you approve publishing, commit/push the reviewed demo branch to the intended repository. Do not push or merge `feature/trusted-price-history` for this deployment.

Creating a Render service or Blueprint starts an initial deployment even when automatic deployments are off. Only perform the following steps after deployment approval.

## 2. Create the service

In Render choose **New ? Blueprint**, connect the approved repository and `feature/hackathon-demo` branch, and use the root `render.yaml`. It describes exactly one Docker Web Service in Frankfurt, with `/health` as its health check and automatic deploys disabled.

Alternatively choose **New ? Web Service**, select that repository/branch, choose Docker, leave Root Directory empty, set Dockerfile Path to `./Dockerfile`, Health Check Path to `/health`, and disable Auto Deploy. Do not set a custom Docker/start command; the Dockerfile supplies it. Use one instance. The supplied Blueprint selects the free plan; check availability and cold-start behavior in your Render account before submission. Open the service before judging so it has time to start.

Privately supply these environment variables in Render (never paste values into source, chat, or this document):

| Variable | Value to enter |
| --- | --- |
| `CONTEXT_DEV_API_KEY` | Existing Context.dev key; runtime only, never a frontend variable/build argument |
| `SUPABASE_URL` | Existing Supabase Project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Existing **publishable** key (`sb_publishable_...`), required by backend authentication; never a service-role or secret key |
| `VITE_SUPABASE_URL` | Same URL as `SUPABASE_URL`; public build configuration |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Same public publishable key as above; a validated legacy `anon` key also works for the frontend |

Do not set `VITE_API_BASE_URL` for production. The Docker build fixes it to empty so the browser uses the same public origin. Public `VITE_` configuration is compiled into the JavaScript bundle and requires a rebuild if changed. The build rejects secret/service-role keys. `.dockerignore` excludes local environment files, virtual environments, exports, and SQL. The Dockerfile declares only the two public build arguments and copies only application files and the compiled bundle into its runtime image.

For manual service creation, also set these values (the Blueprint already supplies them):

```text
RIVALSENSE_READ_BUDGET=local
RIVALSENSE_READS_PER_MINUTE=10
RIVALSENSE_GLOBAL_READS_PER_MINUTE=60
RIVALSENSE_READ_CONCURRENCY=2
RIVALSENSE_RECORDING_ENABLED=false
RESEARCH_HISTORY_ENABLED=false
```

Keep one worker/instance while using local read limits. Do not set `RIVALSENSE_RECORDING_SECRET`. Same-origin requests do not need a separate CORS origin. Context.dev and Supabase remain external services; no replacement database is created.

## 3. Configure Google authentication for the assigned URL

Render assigns a URL such as `https://<assigned-service-name>.onrender.com`. Use the actual assigned hostname, not this placeholder.

In **Supabase ? Authentication ? URL Configuration**:

- Add `https://<assigned-service-name>.onrender.com` to Redirect URLs (add the trailing-slash form too if used).
- For a demo-only Supabase auth project, set Site URL to that HTTPS origin. If the existing Site URL supports another application, preserve it and add the Render URL to the allowlist instead; RivalSense explicitly supplies `window.location.origin` as its redirect target.
- Preserve working local redirect entries, including `http://127.0.0.1:5173`, for continued local testing.

Keep the existing Supabase Google provider enabled. In the existing **Google Auth Platform OAuth client**:

- Add the Render HTTPS origin under Authorized JavaScript origins.
- Keep the authorized redirect URI equal to the **Supabase Google callback URL** shown in the Supabase provider page, normally `https://<project-ref>.supabase.co/auth/v1/callback`. The Render frontend URL is not the Google callback URL.
- Keep Google client secrets inside the Supabase provider configuration, never in Render frontend variables. Ensure the OAuth consent-screen audience permits the intended judges to sign in.

These are authentication settings only; no table or migration changes are needed. They have not been changed by this preparation.

## 4. Verify and submit

1. Wait for a healthy Render deploy. Open `https://<assigned-service-name>.onrender.com/health`; expect `{"status":"ok"}`.
2. Open the service root. Expect the RivalSense React sign-in page, not the API welcome JSON.
3. Sign in with Google. Confirm the browser returns to the same HTTPS hostname and loads the dashboard.
4. Ask �Who founded Microsoft and in what year?�. Confirm an answer and clickable source links appear. In Network, expect `POST /api/ai/ask` on that same domain, HTTP 200, `application/json`.
5. Submit the **service root HTTPS URL** for Junction. No separate frontend/backend URLs are needed.

An unauthenticated POST to `/api/ai/ask` correctly returns HTTP 401 JSON. Unknown `/api` routes and missing assets stay 404 instead of returning the React page. `/health` is a process health check; it does not spend provider credits or verify external credentials.

If Google rejects redirects, check the exact assigned HTTPS origin in Supabase and the Supabase callback in Google. If research returns a JSON 503, check runtime keys/account quota; never paste raw provider exceptions or tokens into issue reports.

## Local verification

Completed on this machine: Vite production build, 9 frontend tests, 112 offline backend tests, and serving the actual generated HTML/assets through FastAPI using `Backend/scripts/verify_production.py`. An isolated browser also rendered the compiled app directly from FastAPI at desktop/mobile sizes and verified same-origin API requests returned JSON authentication errors. The previously authenticated local research flow was confirmed working by the user.

Docker is not installed on this machine. The container build and Render deployment have **not** been run. On a Docker-capable machine, build from the repository root using only public frontend values:

```sh
docker build --build-arg VITE_SUPABASE_URL --build-arg VITE_SUPABASE_PUBLISHABLE_KEY -t rivalsense-demo .
docker run --rm -p 10000:10000 --env-file Backend/.env -e PORT=10000 -e RIVALSENSE_READ_BUDGET=local -e RIVALSENSE_RECORDING_ENABLED=false -e RESEARCH_HISTORY_ENABLED=false rivalsense-demo
```

Set the two public build arguments in your shell environment privately before the build. Never pass the Context.dev key as a build argument. The ignored `Backend/.env` supplies runtime values only; it is excluded from the image. Open `http://127.0.0.1:10000` for this optional container test, and allow that origin in Supabase if testing Google login there. This does not replace the working Vite development URL.

To recheck production serving without Docker: build in `frontEnd` with `npm ci` and `npm run build`, then from `Backend` run `python scripts/verify_production.py`. Set `FRONTEND_DIST` to the absolute built `frontEnd/dist` directory to serve it with Uvicorn; normal Vite development remains unchanged when this variable is absent.

References: [Render Docker builds and environment variables](https://render.com/docs/docker), [Render Blueprint fields](https://render.com/docs/blueprint-spec), [Render port binding](https://render.com/docs/web-services#port-binding), [Supabase Google OAuth configuration](https://supabase.com/docs/guides/auth/social-sign-in/auth-google), [Supabase redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls).
