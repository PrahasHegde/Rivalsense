-- REVISED PROPOSAL ONLY: never auto-run. Requires approval AND live inspection.
-- Requires pgcrypto in extensions (verify with inspect_schema.sql first).
-- Backend deployment must adopt the signed capture-event contract before use.
BEGIN;
DO $$ BEGIN
  IF to_regprocedure('extensions.hmac(bytea,bytea,text)') IS NULL THEN
    RAISE EXCEPTION 'Inspect pgcrypto installation before applying this proposal';
  END IF;
  IF to_regprocedure('public.rivalsense_record_observation(uuid,jsonb,uuid,jsonb)') IS NOT NULL THEN
    RAISE EXCEPTION 'Obsolete recording RPC exists: review and revoke it in a separately approved migration';
  END IF;
END $$;
CREATE ROLE rivalsense_recorder NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE SCHEMA rivalsense_private;
REVOKE ALL ON SCHEMA rivalsense_private FROM PUBLIC, anon, authenticated;
CREATE TABLE rivalsense_private.recording_config (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  signing_secret text, -- Provision privately AFTER approval; never commit a value.
  threshold_percent numeric NOT NULL DEFAULT 5 CHECK (threshold_percent BETWEEN 0 AND 10000)
);
INSERT INTO rivalsense_private.recording_config(singleton) VALUES (true);
REVOKE ALL ON rivalsense_private.recording_config FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA public, auth, extensions, rivalsense_private TO rivalsense_recorder;
GRANT SELECT ON rivalsense_private.recording_config TO rivalsense_recorder;
GRANT EXECUTE ON FUNCTION auth.uid() TO rivalsense_recorder;
GRANT EXECUTE ON FUNCTION extensions.hmac(bytea, bytea, text) TO rivalsense_recorder;

ALTER TABLE public.price_observations
  ADD COLUMN matching_status text NOT NULL DEFAULT 'needs_review'
    CHECK (matching_status IN ('confirmed','needs_review','mismatch','unavailable')),
  ADD COLUMN extraction_error text,
  ADD COLUMN extracted_product jsonb,
  ADD COLUMN capture_event_id uuid,
  ADD COLUMN recording_payload jsonb,
  ADD CONSTRAINT observations_capture_event_unique UNIQUE(user_id, capture_event_id);
ALTER TABLE public.alerts
  ADD COLUMN source_observation_id uuid,
  ADD CONSTRAINT alerts_source_owner_fk FOREIGN KEY(source_observation_id,user_id)
    REFERENCES public.price_observations(id,user_id),
  ADD CONSTRAINT alerts_unique_observation_event UNIQUE(user_id,source_observation_id,event_type);
CREATE INDEX idx_confirmed_prices_listing_time ON public.price_observations
  (user_id,listing_id,currency,observed_at DESC,id DESC)
  WHERE matching_status='confirmed' AND extraction_status IN ('success','partial') AND price IS NOT NULL;

-- Protect immutable observations and alert content. Status-only updates remain possible.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.price_observations FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.alerts FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.price_observations, public.alerts TO authenticated;
GRANT UPDATE(status) ON public.alerts TO authenticated;
DO $$ BEGIN
  IF has_any_column_privilege('authenticated','public.price_observations','INSERT')
     OR has_any_column_privilege('authenticated','public.price_observations','UPDATE')
     OR has_any_column_privilege('authenticated','public.alerts','INSERT')
     OR has_column_privilege('authenticated','public.alerts','old_price','UPDATE')
     OR has_column_privilege('authenticated','public.alerts','new_price','UPDATE') THEN
    RAISE EXCEPTION 'Inherited or column-level write grants remain: inspect and revise before deployment';
  END IF;
  IF has_any_column_privilege('anon','public.price_observations','INSERT')
     OR has_any_column_privilege('anon','public.alerts','INSERT')
     OR EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid='public.alerts'::regclass
       AND a.attnum>0 AND NOT a.attisdropped AND a.attname<>'status'
       AND has_column_privilege('authenticated',a.attrelid,a.attnum,'UPDATE')) THEN
    RAISE EXCEPTION 'Residual client write grants remain; inspect before deployment';
  END IF;
END $$;
GRANT SELECT ON public.products TO rivalsense_recorder;
GRANT SELECT, UPDATE ON public.competitor_listings TO rivalsense_recorder;
GRANT SELECT, INSERT ON public.price_observations, public.alerts TO rivalsense_recorder;
-- Explicit policies for the dedicated non-owner, NOBYPASSRLS role.
CREATE POLICY recorder_products ON public.products FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_listings ON public.competitor_listings FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_listing_lock ON public.competitor_listings FOR UPDATE TO rivalsense_recorder USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY recorder_observations_read ON public.price_observations FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_observations_insert ON public.price_observations FOR INSERT TO rivalsense_recorder WITH CHECK(user_id=auth.uid());
CREATE POLICY recorder_alerts_read ON public.alerts FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_alerts_insert ON public.alerts FOR INSERT TO rivalsense_recorder WITH CHECK(user_id=auth.uid());

-- Exact UTF-8 p_payload bytes are HMAC-SHA256 signed by the backend.
-- No caller-controlled threshold, alert flag, observation UUID, or baseline.
CREATE FUNCTION public.rivalsense_record_verified_capture(p_payload text,p_signature text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
  p jsonb; o jsonb; evidence jsonb;
  cfg rivalsense_private.recording_config%ROWTYPE;
  listing public.competitor_listings%ROWTYPE;
  product public.products%ROWTYPE;
  existing public.price_observations%ROWTYPE;
  previous public.price_observations%ROWTYPE;
  saved public.price_observations%ROWTYPE;
  generated public.alerts%ROWTYPE;
  amount numeric; stamp timestamptz; match_status text;
BEGIN
  IF auth.uid() IS NULL THEN RAISE EXCEPTION 'Authentication required' USING ERRCODE='42501'; END IF;
  IF octet_length(p_payload)>65536 THEN RAISE EXCEPTION 'Payload too large' USING ERRCODE='22023'; END IF;
  SELECT * INTO STRICT cfg FROM rivalsense_private.recording_config WHERE singleton;
  IF cfg.signing_secret IS NULL OR length(cfg.signing_secret)<32 OR p_signature IS NULL
     OR encode(extensions.hmac(convert_to(p_payload,'UTF8'),convert_to(cfg.signing_secret,'UTF8'),'sha256'),'hex') <> p_signature
  THEN RAISE EXCEPTION 'Backend attestation required' USING ERRCODE='42501'; END IF;
  p:=p_payload::jsonb; o:=p->'observation'; evidence:=p->'evidence';
  IF (p->>'user_id')::uuid IS DISTINCT FROM auth.uid() OR p->>'version' IS DISTINCT FROM '1'
     OR p->>'capture_event_id' IS NULL OR p->>'listing_id' IS NULL OR o IS NULL
  THEN RAISE EXCEPTION 'Invalid capture identity' USING ERRCODE='42501'; END IF;
  -- Listing lock serializes concurrent requests, even with different row UUIDs.
  SELECT * INTO listing FROM public.competitor_listings WHERE id=(p->>'listing_id')::uuid AND user_id=auth.uid() FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Listing unavailable' USING ERRCODE='42501'; END IF;
  SELECT * INTO existing FROM public.price_observations
    WHERE user_id=auth.uid() AND capture_event_id=(p->>'capture_event_id')::uuid;
  IF FOUND THEN
    IF existing.recording_payload IS DISTINCT FROM p THEN
      RAISE EXCEPTION 'Conflicting capture replay' USING ERRCODE='23505';
    END IF;
    SELECT * INTO generated FROM public.alerts WHERE user_id=auth.uid() AND source_observation_id=existing.id AND event_type='competitor_price_change';
    RETURN jsonb_build_object('observation',to_jsonb(existing),'alert',CASE WHEN generated.id IS NULL THEN NULL ELSE to_jsonb(generated) END,'replayed',true);
  END IF;
  IF NOT listing.is_active THEN RAISE EXCEPTION 'Inactive listing' USING ERRCODE='42501'; END IF;
  SELECT * INTO STRICT product FROM public.products WHERE id=listing.product_id AND user_id=auth.uid();
  -- Bind the signed validation to the actual product and listing, rejecting stale evidence.
  IF p->>'product_url' IS DISTINCT FROM listing.product_url
     OR evidence->'reference' IS DISTINCT FROM jsonb_build_object('name',product.name,'brand',product.brand,'sku',product.sku,'model_number',product.model_number)
     OR evidence->>'validator' IS DISTINCT FROM 'rivalsense-identity-v1'
  THEN RAISE EXCEPTION 'Invalid or stale identity evidence' USING ERRCODE='22023'; END IF;
  match_status:=evidence->>'matching_status';
  IF match_status NOT IN ('confirmed','needs_review','mismatch','unavailable') OR match_status IS NULL THEN
    RAISE EXCEPTION 'Invalid matching status' USING ERRCODE='22023'; END IF;
  -- Backend must actually run identity(); unsigned client assertions never qualify.
  IF match_status='confirmed' AND
    (evidence->>'basis' NOT IN ('name_and_sku','name_and_model','name_and_brand') OR evidence->>'basis' IS NULL
      OR jsonb_typeof(evidence->'extracted') IS DISTINCT FROM 'object') THEN
    RAISE EXCEPTION 'Confirmation requires backend evidence' USING ERRCODE='22023'; END IF;
  amount:=(o->>'price')::numeric; stamp:=(o->>'observed_at')::timestamptz;
  IF amount IS NOT NULL AND (amount<0 OR amount>999999999999.99 OR amount<>round(amount,2)) THEN
    RAISE EXCEPTION 'Invalid monetary precision' USING ERRCODE='22023'; END IF;
  IF stamp IS NULL OR stamp>clock_timestamp()+interval '1 minute' THEN
    RAISE EXCEPTION 'Invalid observation timestamp' USING ERRCODE='22023'; END IF;
  SELECT * INTO previous FROM public.price_observations
    WHERE user_id=auth.uid() AND listing_id=listing.id AND matching_status='confirmed'
      AND extraction_status IN ('success','partial') AND price IS NOT NULL AND currency=o->>'currency'
    ORDER BY observed_at DESC,id DESC LIMIT 1;
  INSERT INTO public.price_observations(user_id,listing_id,price,currency,availability,extraction_status,source_url,observed_at,
      matching_status,extraction_error,extracted_product,capture_event_id,recording_payload)
    VALUES(auth.uid(),listing.id,amount,o->>'currency',o->>'availability',o->>'extraction_status',o->>'source_url',stamp,
      match_status,o->>'extraction_error',evidence,(p->>'capture_event_id')::uuid,p)
    RETURNING * INTO saved;
  -- Exact PostgreSQL NUMERIC arithmetic: strict greater-than, both directions.
  -- Direct RPC callers cannot lower the configured threshold or request an alert.
  IF saved.matching_status='confirmed' AND saved.extraction_status IN ('success','partial')
      AND saved.price IS NOT NULL AND previous.id IS NOT NULL AND previous.price>0
      AND saved.observed_at>previous.observed_at
      AND abs(saved.price-previous.price)*100 > previous.price*cfg.threshold_percent THEN
    INSERT INTO public.alerts(user_id,product_id,event_type,severity,title,old_price,new_price,currency,source_url,source_observation_id)
      VALUES(auth.uid(),listing.product_id,'competitor_price_change','medium','Competitor price changed',
        previous.price,saved.price,saved.currency,saved.source_url,saved.id) RETURNING * INTO generated;
  END IF;
  RETURN jsonb_build_object('observation',to_jsonb(saved),'alert',CASE WHEN generated.id IS NULL THEN NULL ELSE to_jsonb(generated) END,'replayed',false);
END;
$$;
-- Admin must have authority to assign this role; verify before execution.
GRANT CREATE ON SCHEMA public TO rivalsense_recorder;
ALTER FUNCTION public.rivalsense_record_verified_capture(text,text) OWNER TO rivalsense_recorder;
REVOKE CREATE ON SCHEMA public FROM rivalsense_recorder;
REVOKE ALL ON FUNCTION public.rivalsense_record_verified_capture(text,text) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.rivalsense_record_verified_capture(text,text) TO authenticated;
COMMIT;
-- No secret is provisioned, no RPC flag is enabled, no auth.users/OAuth changes.
-- Never deploy this alongside the older insecure recording RPC: inspect first.

-- Deployment notes: the role must never be granted to authenticated, anon, or
-- authenticator. Do not expose rivalsense_private through the Data API.
