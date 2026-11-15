# Intended demo staging manifest

These files are proposed for staging on `feature/hackathon-demo`. No commit, push, or merge is authorized yet. The list excludes copied trusted-history changes, all pending SQL proposals/fixtures, environment values, generated builds, and test output. The Windows-compatible offline test runner is included as test source. The saved verified example is an intentional application asset labeled NOT LIVE, not a generated test output. Only placeholder `.env.example` templates are included.

- `.dockerignore`
- `Backend/.env.example`
- `Backend/README.md`
- `Backend/app/api/prices.py`
- `Backend/app/api/research.py`
- `Backend/app/api/routes.py`
- `Backend/app/core/config.py`
- `Backend/app/core/frontend.py`
- `Backend/app/main.py`
- `Backend/app/schemas/research.py`
- `Backend/app/services/context_client.py`
- `Backend/app/services/read_budget.py`
- `Backend/app/services/research.py`
- `Backend/scripts/configure_demo.py`
- `Backend/scripts/diagnose_context.py`
- `Backend/scripts/test_offline.py`
- `Backend/scripts/verify_production.py`
- `Backend/tests/test_frontend.py`
- `Backend/tests/test_research.py`
- `DEMO-FILES.md`
- `DEMO.md`
- `DEPLOYMENT.md`
- `Dockerfile`
- `frontEnd/.env.example`
- `frontEnd/package-lock.json`
- `frontEnd/package.json`
- `frontEnd/public/verified-example.json`
- `frontEnd/scripts/render-layout.mjs`
- `frontEnd/scripts/validate-public-config.mjs`
- `frontEnd/scripts/verify-layout.mjs`
- `frontEnd/scripts/verify-production-browser.mjs`
- `frontEnd/scripts/verify-research-render.mjs`
- `frontEnd/src/App.css`
- `frontEnd/src/App.jsx`
- `frontEnd/src/DashBoard.jsx`
- `frontEnd/src/components/PriceChart.jsx`
- `frontEnd/src/hooks/useRivalSession.js`
- `frontEnd/src/index.css`
- `frontEnd/src/lib/api.js`
- `frontEnd/src/lib/apiClient.js`
- `frontEnd/src/lib/presentation.js`
- `frontEnd/src/supabase.js`
- `frontEnd/tests/api.test.js`
- `frontEnd/tests/publicConfig.test.js`
- `frontEnd/vite.config.js`
- `render.yaml`

## Left unstaged

- `Backend/app/services/capture_receipts.py`
- `Backend/app/services/rate_limit.py`
- `Backend/docs/recording-migration-review.md`
- `Backend/docs/supabase-api.md`
- `Backend/migrations/PROPOSED_ai_responses.sql`
- `Backend/migrations/PROPOSED_price_history.sql`
- `Backend/migrations/inspect_security_readonly.sql`
- `Backend/tests/integration/fixtures/supabase_app_baseline.sql`
- `Backend/tests/test_capture_attestation.py`
- `Backend/tests/test_capture_receipts.py`
- `Backend/tests/test_migration_contract.py`
- `Backend/tests/test_rate_limit.py`
