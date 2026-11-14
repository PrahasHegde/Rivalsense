-- MANUAL STANDALONE FIXTURE ONLY. Never use against an existing Supabase project.
-- NOT auto-executed. Requires separate setup approval, a dedicated disposable
-- PostgreSQL cluster, and marker.sql already installed. Synthetic auth.uid()
-- is a database simulation, not real Supabase Auth/JWT verification.
BEGIN;
DO $$ BEGIN
 IF (SELECT count(*) FROM rivalsense_test_control.environment
     WHERE purpose='rivalsense-isolated-integration')<>1 THEN RAISE EXCEPTION 'Test marker required'; END IF;
 IF to_regnamespace('auth') IS NOT NULL OR to_regclass('public.products') IS NOT NULL
    OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('anon','authenticated','authenticator'))
 THEN RAISE EXCEPTION 'Standalone fixture requires a fresh dedicated cluster'; END IF;
END $$;
CREATE ROLE anon NOLOGIN NOBYPASSRLS;
CREATE ROLE authenticated NOLOGIN NOBYPASSRLS;
CREATE ROLE authenticator NOLOGIN NOINHERIT NOBYPASSRLS;
GRANT anon,authenticated TO authenticator;
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT coalesce(nullif(current_setting('request.jwt.claim.sub',true),''),
   nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'sub')::uuid
$$;
GRANT USAGE ON SCHEMA auth TO anon,authenticated;
GRANT EXECUTE ON FUNCTION auth.uid() TO anon,authenticated;
CREATE SCHEMA extensions;
CREATE EXTENSION pgcrypto WITH SCHEMA extensions;
CREATE TABLE public.products (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 name text NOT NULL,brand text,sku text,model_number text,
 selling_price numeric(14,2) NOT NULL CHECK(selling_price>=0),
 cost_price numeric(14,2) CHECK(cost_price>=0),currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(id,user_id)
);
CREATE TABLE public.competitor_listings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 product_id uuid NOT NULL,competitor_name text NOT NULL,
 product_url text NOT NULL CHECK(product_url ~ '^https://'),
 is_active boolean NOT NULL DEFAULT true,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,user_id),UNIQUE(user_id,product_id,product_url),
 FOREIGN KEY(product_id,user_id) REFERENCES public.products(id,user_id) ON DELETE CASCADE
);
CREATE TABLE public.price_observations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 listing_id uuid NOT NULL,price numeric(14,2) CHECK(price>=0),
 currency text CHECK(currency ~ '^[A-Z]{3}$'),availability text,
 extraction_status text NOT NULL CHECK(extraction_status IN ('success','partial','failure')),
 source_url text NOT NULL,observed_at timestamptz NOT NULL DEFAULT now(),UNIQUE(id,user_id),
 FOREIGN KEY(listing_id,user_id) REFERENCES public.competitor_listings(id,user_id) ON DELETE CASCADE
);
CREATE TABLE public.alerts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 product_id uuid NOT NULL,event_type text NOT NULL,
 severity text NOT NULL DEFAULT 'low' CHECK(severity IN ('low','medium','high','critical')),
 title text NOT NULL,description text,old_price numeric(14,2) CHECK(old_price>=0),
 new_price numeric(14,2) CHECK(new_price>=0),currency text CHECK(currency ~ '^[A-Z]{3}$'),source_url text,
 status text NOT NULL DEFAULT 'unread' CHECK(status IN ('unread','read','resolved')),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(id,user_id),
 FOREIGN KEY(product_id,user_id) REFERENCES public.products(id,user_id) ON DELETE CASCADE
);
CREATE INDEX idx_prices_listing_time ON public.price_observations(listing_id,observed_at DESC);
CREATE INDEX idx_alerts_user_time ON public.alerts(user_id,created_at DESC);
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.price_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY products_owner ON public.products TO authenticated USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY listings_owner ON public.competitor_listings TO authenticated USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY observations_read ON public.price_observations FOR SELECT TO authenticated USING(user_id=auth.uid());
CREATE POLICY observations_insert ON public.price_observations FOR INSERT TO authenticated WITH CHECK(user_id=auth.uid());
CREATE POLICY alerts_read ON public.alerts FOR SELECT TO authenticated USING(user_id=auth.uid());
CREATE POLICY alerts_insert ON public.alerts FOR INSERT TO authenticated WITH CHECK(user_id=auth.uid());
CREATE POLICY alerts_update ON public.alerts FOR UPDATE TO authenticated USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
GRANT USAGE ON SCHEMA public TO anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.products,public.competitor_listings TO authenticated;
GRANT SELECT,INSERT ON public.price_observations TO authenticated;
GRANT SELECT,INSERT,UPDATE ON public.alerts TO authenticated;
COMMIT;
-- Apply the exact proposal only after separate approval. Then privately set the
-- fixed TEST_SECRET documented in postgres-validation.md, keeping alerts false.
