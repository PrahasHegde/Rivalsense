-- PROPOSAL ONLY. Do not execute without separate migration approval and staging validation.
-- No secrets, alert enablement, data deletion, auth.users/OAuth changes, or startup execution.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
DO $$ BEGIN
  IF to_regprocedure('extensions.hmac(bytea,bytea,text)') IS NULL THEN
    RAISE EXCEPTION 'Required pgcrypto signature missing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname='rivalsense_record_observation') THEN
    RAISE EXCEPTION 'Review obsolete recording RPC overloads before deployment';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rivalsense_recorder')
     OR to_regnamespace('rivalsense_private') IS NOT NULL THEN
    RAISE EXCEPTION 'Recorder objects already exist; reconcile before applying';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class WHERE oid IN ('public.products'::regclass,
      'public.competitor_listings'::regclass,'public.price_observations'::regclass,'public.alerts'::regclass)
      AND NOT relrowsecurity) THEN RAISE EXCEPTION 'Owner RLS must already be enabled'; END IF;
END $$;

CREATE ROLE rivalsense_recorder NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE SCHEMA rivalsense_private;
REVOKE ALL ON SCHEMA rivalsense_private FROM PUBLIC, anon, authenticated;

CREATE TABLE rivalsense_private.recording_config (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  signing_secret text, -- Provision privately only after separate approval; NULL fails closed.
  threshold_percent numeric NOT NULL DEFAULT 5
    CHECK(threshold_percent >= 0 AND threshold_percent <= 10000 AND threshold_percent <> 'NaN'::numeric),
  alerts_enabled boolean NOT NULL DEFAULT false,
  per_user_minute integer NOT NULL DEFAULT 10 CHECK(per_user_minute BETWEEN 1 AND 100000),
  per_user_day integer NOT NULL DEFAULT 200 CHECK(per_user_day BETWEEN 1 AND 10000000),
  global_minute integer NOT NULL DEFAULT 60 CHECK(global_minute BETWEEN 1 AND 1000000),
  per_user_concurrent integer NOT NULL DEFAULT 2 CHECK(per_user_concurrent BETWEEN 1 AND 1000),
  lease_seconds integer NOT NULL DEFAULT 900 CHECK(lease_seconds BETWEEN 120 AND 3600)
);
INSERT INTO rivalsense_private.recording_config(singleton) VALUES(true);

CREATE TABLE rivalsense_private.quota_reservations (
  id uuid PRIMARY KEY, user_id uuid NOT NULL, units integer NOT NULL CHECK(units > 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL, released boolean NOT NULL DEFAULT false
);
CREATE INDEX quota_user_time ON rivalsense_private.quota_reservations(user_id,created_at DESC);
CREATE INDEX quota_global_time ON rivalsense_private.quota_reservations(created_at DESC);

CREATE TABLE rivalsense_private.capture_receipts (
  user_id uuid NOT NULL, request_key uuid NOT NULL, listing_id uuid NOT NULL,
  capture_event_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  token uuid NOT NULL, state text NOT NULL CHECK(state IN ('extracting','ready','completed','indeterminate')),
  listing_snapshot jsonb NOT NULL, product_snapshot jsonb NOT NULL,
  expires_at timestamptz NOT NULL, payload text, signature text, result jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(user_id,request_key)
);
-- No FK to auth.users is added; account-retention policy is not changed here.
REVOKE ALL ON ALL TABLES IN SCHEMA rivalsense_private FROM PUBLIC,anon,authenticated;
GRANT USAGE ON SCHEMA public,auth,extensions,rivalsense_private TO rivalsense_recorder;
GRANT SELECT ON rivalsense_private.recording_config TO rivalsense_recorder;
GRANT SELECT,INSERT,UPDATE ON rivalsense_private.capture_receipts,rivalsense_private.quota_reservations TO rivalsense_recorder;
GRANT EXECUTE ON FUNCTION auth.uid(), extensions.hmac(bytea,bytea,text) TO rivalsense_recorder;

ALTER TABLE public.products ADD COLUMN is_archived boolean NOT NULL DEFAULT false;
ALTER TABLE public.price_observations
  ADD COLUMN matching_status text NOT NULL DEFAULT 'needs_review'
    CHECK(matching_status IN ('confirmed','needs_review','mismatch','unavailable')),
  ADD COLUMN extraction_error text,
  ADD COLUMN extracted_product jsonb,
  ADD COLUMN capture_event_id uuid,
  ADD COLUMN recording_payload jsonb,
  ADD CONSTRAINT observations_capture_event_unique UNIQUE(user_id,capture_event_id);
ALTER TABLE public.alerts
  ADD COLUMN source_observation_id uuid,
  ADD CONSTRAINT alerts_source_owner_fk FOREIGN KEY(source_observation_id,user_id)
    REFERENCES public.price_observations(id,user_id),
  ADD CONSTRAINT alerts_unique_observation_event UNIQUE(user_id,source_observation_id,event_type);
CREATE INDEX idx_confirmed_prices_listing_time ON public.price_observations
  (user_id,listing_id,currency,observed_at DESC,id DESC)
  WHERE matching_status='confirmed' AND extraction_status IN ('success','partial') AND price IS NOT NULL;

-- Replace ONLY inter-product/listing/history CASCADE foreign keys, preserving rows
-- and preserving every existing auth.users FK/account-deletion setting unchanged.
DO $$ DECLARE k record; definition text; BEGIN
  FOR k IN SELECT c.oid,c.conname,c.conrelid FROM pg_constraint c
    WHERE c.contype='f' AND c.confdeltype='c'
      AND c.conrelid IN ('public.competitor_listings'::regclass,'public.price_observations'::regclass,'public.alerts'::regclass)
      AND c.confrelid IN ('public.products'::regclass,'public.competitor_listings'::regclass)
  LOOP
    definition := replace(pg_get_constraintdef(k.oid),' ON DELETE CASCADE',' ON DELETE NO ACTION');
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',k.conrelid::regclass,k.conname);
    EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',k.conrelid::regclass,k.conname,definition);
  END LOOP;
END $$;

REVOKE UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON public.products,public.competitor_listings FROM PUBLIC,anon,authenticated;
GRANT UPDATE(selling_price,cost_price,is_archived) ON public.products TO authenticated;
GRANT UPDATE(competitor_name,is_active) ON public.competitor_listings TO authenticated;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON public.price_observations,public.alerts FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.price_observations,public.alerts TO authenticated;
GRANT UPDATE(status) ON public.alerts TO authenticated;
DROP POLICY IF EXISTS observations_insert ON public.price_observations;
DROP POLICY IF EXISTS alerts_insert ON public.alerts;

-- Defense in depth against identity updates, including updates outside FastAPI.
CREATE FUNCTION rivalsense_private.guard_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_TABLE_NAME='products' THEN
    IF ROW(NEW.id,NEW.user_id,NEW.name,NEW.brand,NEW.sku,NEW.model_number,NEW.currency)
       IS DISTINCT FROM ROW(OLD.id,OLD.user_id,OLD.name,OLD.brand,OLD.sku,OLD.model_number,OLD.currency)
    THEN RAISE EXCEPTION 'Create a new product for a different identity' USING ERRCODE='22023'; END IF;
  ELSE
    IF ROW(NEW.id,NEW.user_id,NEW.product_id,NEW.product_url)
       IS DISTINCT FROM ROW(OLD.id,OLD.user_id,OLD.product_id,OLD.product_url)
    THEN RAISE EXCEPTION 'Create a new listing for a different identity' USING ERRCODE='22023'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER rivalsense_product_identity BEFORE UPDATE ON public.products
  FOR EACH ROW EXECUTE FUNCTION rivalsense_private.guard_identity();
CREATE TRIGGER rivalsense_listing_identity BEFORE UPDATE ON public.competitor_listings
  FOR EACH ROW EXECUTE FUNCTION rivalsense_private.guard_identity();

GRANT SELECT ON public.products,public.competitor_listings,public.price_observations,public.alerts TO rivalsense_recorder;
-- Row locks require UPDATE privilege on at least one column.
GRANT UPDATE(is_archived) ON public.products TO rivalsense_recorder;
GRANT UPDATE(is_active) ON public.competitor_listings TO rivalsense_recorder;
GRANT INSERT ON public.price_observations,public.alerts TO rivalsense_recorder;
CREATE POLICY recorder_products ON public.products FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_products_lock ON public.products FOR UPDATE TO rivalsense_recorder USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY recorder_listings ON public.competitor_listings FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_listings_lock ON public.competitor_listings FOR UPDATE TO rivalsense_recorder USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY recorder_observations_read ON public.price_observations FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_observations_insert ON public.price_observations FOR INSERT TO rivalsense_recorder WITH CHECK(user_id=auth.uid());
CREATE POLICY recorder_alerts_read ON public.alerts FOR SELECT TO rivalsense_recorder USING(user_id=auth.uid());
CREATE POLICY recorder_alerts_insert ON public.alerts FOR INSERT TO rivalsense_recorder WITH CHECK(user_id=auth.uid());

-- Private helpers run with the narrowly scoped recorder role via public wrappers.
CREATE FUNCTION rivalsense_private.verify_command(p_payload text,p_signature text,p_action text,p_fresh boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE secret text; p jsonb; issued timestamptz;
BEGIN
  IF auth.uid() IS NULL OR p_payload IS NULL OR octet_length(p_payload)>131072 OR p_signature IS NULL
    THEN RAISE EXCEPTION 'Invalid signed command' USING ERRCODE='42501'; END IF;
  SELECT signing_secret INTO STRICT secret FROM rivalsense_private.recording_config WHERE singleton;
  IF secret IS NULL OR octet_length(secret)<32 OR p_signature !~ '^[0-9a-f]{64}$'
     OR encode(extensions.hmac(convert_to(p_payload,'UTF8'),convert_to(secret,'UTF8'),'sha256'),'hex') <> p_signature
    THEN RAISE EXCEPTION 'Backend attestation required' USING ERRCODE='42501'; END IF;
  p := p_payload::jsonb;
  IF jsonb_typeof(p) IS DISTINCT FROM 'object' OR p->>'version' IS DISTINCT FROM '1'
     OR p->>'action' IS DISTINCT FROM p_action OR (p->>'user_id')::uuid IS DISTINCT FROM auth.uid()
    THEN RAISE EXCEPTION 'Invalid command identity' USING ERRCODE='42501'; END IF;
  IF p_fresh THEN
    issued := (p->>'issued_at')::timestamptz;
    IF issued IS NULL OR NOT isfinite(issued) OR issued < clock_timestamp()-interval '60 seconds'
       OR issued > clock_timestamp()+interval '30 seconds'
      THEN RAISE EXCEPTION 'Expired command' USING ERRCODE='42501'; END IF;
  END IF;
  RETURN p;
END $$;

CREATE FUNCTION rivalsense_private.reserve_quota(p_id uuid,p_units integer)
RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE cfg rivalsense_private.recording_config%ROWTYPE; t timestamptz := clock_timestamp();
  existing rivalsense_private.quota_reservations%ROWTYPE; used_min bigint; used_day bigint; used_global bigint; active bigint;
BEGIN
  -- A shared DB lock coordinates all application workers and all quota paths.
  PERFORM pg_advisory_xact_lock(192837465);
  SELECT * INTO STRICT cfg FROM rivalsense_private.recording_config WHERE singleton;
  SELECT * INTO existing FROM rivalsense_private.quota_reservations WHERE id=p_id;
  IF FOUND THEN
    IF existing.user_id IS DISTINCT FROM auth.uid() OR existing.units IS DISTINCT FROM p_units
      THEN RAISE EXCEPTION 'Conflicting quota reservation' USING ERRCODE='23505'; END IF;
    -- Acquisition is one-shot: replay never authorizes another provider fetch.
    RETURN jsonb_build_object('allowed',false,'retry_after',60);
  END IF;
  IF p_id IS NULL OR p_units IS NULL OR p_units<1 OR p_units>100
    THEN RAISE EXCEPTION 'Invalid quota units' USING ERRCODE='22023'; END IF;
  SELECT coalesce(sum(units) FILTER(WHERE created_at>t-interval '1 minute'),0),
         coalesce(sum(units),0),
         count(*) FILTER(WHERE NOT released AND expires_at>t)
    INTO used_min,used_day,active FROM rivalsense_private.quota_reservations
    WHERE user_id=auth.uid() AND created_at>t-interval '1 day';
  SELECT coalesce(sum(units),0) INTO used_global FROM rivalsense_private.quota_reservations
    WHERE created_at>t-interval '1 minute';
  IF used_min+p_units>cfg.per_user_minute OR used_day+p_units>cfg.per_user_day
     OR used_global+p_units>cfg.global_minute OR active>=cfg.per_user_concurrent THEN
    RETURN jsonb_build_object('allowed',false,'retry_after',
      CASE WHEN used_day+p_units>cfg.per_user_day THEN 86400
           WHEN active>=cfg.per_user_concurrent THEN cfg.lease_seconds ELSE 60 END);
  END IF;
  INSERT INTO rivalsense_private.quota_reservations(id,user_id,units,expires_at)
    VALUES(p_id,auth.uid(),p_units,t+make_interval(secs=>cfg.lease_seconds));
  RETURN jsonb_build_object('allowed',true);
END $$;

CREATE FUNCTION public.rivalsense_rate_limit(p_payload text,p_signature text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p jsonb;
BEGIN
  p := rivalsense_private.verify_command(p_payload,p_signature,'quota');
  IF p->>'operation'='acquire' THEN
    RETURN rivalsense_private.reserve_quota((p->>'reservation_id')::uuid,(p->>'units')::integer);
  ELSIF p->>'operation'='release' THEN
    UPDATE rivalsense_private.quota_reservations SET released=true
      WHERE id=(p->>'reservation_id')::uuid AND user_id=auth.uid();
    RETURN jsonb_build_object('released',true);
  END IF;
  RAISE EXCEPTION 'Invalid quota operation' USING ERRCODE='22023';
END $$;

CREATE FUNCTION public.rivalsense_capture_receipt(p_payload text,p_signature text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p jsonb; r rivalsense_private.capture_receipts%ROWTYPE;
  l public.competitor_listings%ROWTYPE; prod public.products%ROWTYPE;
  cfg rivalsense_private.recording_config%ROWTYPE; event uuid; budget jsonb; signed jsonb;
BEGIN
  p := rivalsense_private.verify_command(p_payload,p_signature,'receipt');
  IF p->>'request_key' IS NULL OR p->>'listing_id' IS NULL OR p->>'token' IS NULL THEN
    RAISE EXCEPTION 'Missing receipt identity' USING ERRCODE='22023'; END IF;
  -- Serialize first creation for this owner/key even when no row exists.
  PERFORM pg_advisory_xact_lock(hashtextextended(auth.uid()::text||':'||(p->>'request_key'),0));
  SELECT * INTO r FROM rivalsense_private.capture_receipts
    WHERE user_id=auth.uid() AND request_key=(p->>'request_key')::uuid FOR UPDATE;
  IF FOUND THEN
    IF r.listing_id IS DISTINCT FROM (p->>'listing_id')::uuid
      THEN RAISE EXCEPTION 'Key already belongs to another listing' USING ERRCODE='23505'; END IF;
    IF r.state='completed' THEN
      RETURN jsonb_build_object('state','completed','result',r.result);
    END IF;
    IF r.state='ready' THEN
      IF p->>'operation'='save' AND (r.payload IS DISTINCT FROM p->>'payload' OR r.signature IS DISTINCT FROM p->>'signature') THEN
        RAISE EXCEPTION 'Conflicting immutable payload' USING ERRCODE='23505'; END IF;
      RETURN jsonb_build_object('state','ready','payload',r.payload,'signature',r.signature);
    END IF;
    IF r.state='indeterminate' OR r.expires_at<=clock_timestamp() THEN
      UPDATE rivalsense_private.capture_receipts SET state='indeterminate'
        WHERE user_id=auth.uid() AND request_key=r.request_key;
      RETURN jsonb_build_object('state','indeterminate');
    END IF;
    IF p->>'operation'='claim' THEN RETURN jsonb_build_object('state','busy'); END IF;
    IF p->>'operation' IS DISTINCT FROM 'save' OR r.token IS DISTINCT FROM (p->>'token')::uuid
      THEN RAISE EXCEPTION 'Invalid capture fence' USING ERRCODE='42501'; END IF;
    signed := rivalsense_private.verify_command(p->>'payload',p->>'signature','record',false);
    IF (signed->>'capture_event_id')::uuid IS DISTINCT FROM r.capture_event_id
       OR (signed->>'listing_id')::uuid IS DISTINCT FROM r.listing_id THEN
      RAISE EXCEPTION 'Payload does not belong to receipt' USING ERRCODE='22023'; END IF;
    UPDATE rivalsense_private.capture_receipts SET state='ready',payload=p->>'payload',signature=p->>'signature'
      WHERE user_id=auth.uid() AND request_key=r.request_key;
    UPDATE rivalsense_private.quota_reservations SET released=true WHERE id=r.capture_event_id AND user_id=auth.uid();
    RETURN jsonb_build_object('state','ready','payload',p->>'payload','signature',p->>'signature');
  END IF;
  IF p->>'operation' IS DISTINCT FROM 'claim' THEN
    RAISE EXCEPTION 'Receipt unavailable' USING ERRCODE='22023'; END IF;
  SELECT * INTO l FROM public.competitor_listings WHERE id=(p->>'listing_id')::uuid AND user_id=auth.uid() FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Listing unavailable' USING ERRCODE='42501'; END IF;
  SELECT * INTO STRICT prod FROM public.products WHERE id=l.product_id AND user_id=auth.uid() FOR SHARE;
  IF NOT l.is_active OR prod.is_archived THEN
    RAISE EXCEPTION 'Tracking is inactive' USING ERRCODE='22023'; END IF;
  event := gen_random_uuid();
  budget := rivalsense_private.reserve_quota(event,1);
  IF NOT (budget->>'allowed')::boolean THEN RETURN budget||jsonb_build_object('state','limited'); END IF;
  SELECT * INTO STRICT cfg FROM rivalsense_private.recording_config WHERE singleton;
  INSERT INTO rivalsense_private.capture_receipts(user_id,request_key,listing_id,capture_event_id,token,state,
      listing_snapshot,product_snapshot,expires_at)
    VALUES(auth.uid(),(p->>'request_key')::uuid,l.id,event,(p->>'token')::uuid,'extracting',
      to_jsonb(l),to_jsonb(prod),clock_timestamp()+make_interval(secs=>cfg.lease_seconds));
  RETURN jsonb_build_object('state','extracting','capture_event_id',event,'token',p->>'token',
    'listing',to_jsonb(l),'product',to_jsonb(prod)||jsonb_build_object('selling_price',prod.selling_price::text));
END $$;

CREATE FUNCTION public.rivalsense_record_verified_capture(p_payload text,p_signature text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p jsonb; o jsonb; evidence jsonb; change jsonb; response jsonb;
  cfg rivalsense_private.recording_config%ROWTYPE;
  r rivalsense_private.capture_receipts%ROWTYPE; l public.competitor_listings%ROWTYPE; prod public.products%ROWTYPE;
  previous public.price_observations%ROWTYPE; saved public.price_observations%ROWTYPE; generated public.alerts%ROWTYPE;
  amount numeric; stamp timestamptz; match_status text; status text := 'no_baseline';
  difference numeric; percentage numeric; exceeds boolean := false; alert_status text;
BEGIN
  p := rivalsense_private.verify_command(p_payload,p_signature,'record',false);
  SELECT * INTO r FROM rivalsense_private.capture_receipts
    WHERE user_id=auth.uid() AND capture_event_id=(p->>'capture_event_id')::uuid FOR UPDATE;
  IF NOT FOUND OR r.payload IS DISTINCT FROM p_payload OR r.signature IS DISTINCT FROM p_signature
    THEN RAISE EXCEPTION 'Durably saved capture required' USING ERRCODE='42501'; END IF;
  IF r.state='completed' THEN RETURN r.result||jsonb_build_object('replayed',true); END IF;
  IF r.state IS DISTINCT FROM 'ready' OR r.listing_id IS DISTINCT FROM (p->>'listing_id')::uuid
    THEN RAISE EXCEPTION 'Capture is not ready' USING ERRCODE='22023'; END IF;
  SELECT * INTO STRICT cfg FROM rivalsense_private.recording_config WHERE singleton;
  -- Lock order is listing then product, consistently with capture claims.
  SELECT * INTO STRICT l FROM public.competitor_listings WHERE id=r.listing_id AND user_id=auth.uid() FOR UPDATE;
  SELECT * INTO STRICT prod FROM public.products WHERE id=l.product_id AND user_id=auth.uid() FOR SHARE;
  IF NOT l.is_active OR prod.is_archived THEN RAISE EXCEPTION 'Tracking is inactive' USING ERRCODE='22023'; END IF;
  evidence := p->'evidence'; o := p->'observation';
  IF jsonb_typeof(o) IS DISTINCT FROM 'object' OR jsonb_typeof(evidence) IS DISTINCT FROM 'object'
     OR p->>'product_url' IS DISTINCT FROM l.product_url
     OR evidence->'reference' IS DISTINCT FROM jsonb_build_object('name',prod.name,'brand',prod.brand,'sku',prod.sku,'model_number',prod.model_number)
     OR evidence->>'validator' IS DISTINCT FROM 'rivalsense-identity-v1'
    THEN RAISE EXCEPTION 'Invalid or stale identity evidence' USING ERRCODE='22023'; END IF;
  match_status := evidence->>'matching_status';
  IF match_status IS NULL OR match_status NOT IN ('confirmed','needs_review','mismatch','unavailable')
     OR (match_status='confirmed' AND (evidence->>'basis' IS NULL
       OR evidence->>'basis' NOT IN ('name_and_sku','name_and_model','name_and_brand')
       OR jsonb_typeof(evidence->'extracted') IS DISTINCT FROM 'object'))
    THEN RAISE EXCEPTION 'Invalid matching evidence' USING ERRCODE='22023'; END IF;
  amount := (o->>'price')::numeric; stamp := (o->>'observed_at')::timestamptz;
  IF amount IS NOT NULL AND (amount='NaN'::numeric OR amount<0 OR amount>999999999999.99 OR amount<>round(amount,2))
    THEN RAISE EXCEPTION 'Invalid monetary precision' USING ERRCODE='22023'; END IF;
  IF stamp IS NULL OR NOT isfinite(stamp) OR stamp>clock_timestamp()+interval '1 minute'
    THEN RAISE EXCEPTION 'Invalid observation timestamp' USING ERRCODE='22023'; END IF;
  SELECT * INTO previous FROM public.price_observations
    WHERE user_id=auth.uid() AND listing_id=l.id AND matching_status='confirmed'
      AND extraction_status IN ('success','partial') AND price IS NOT NULL AND currency=o->>'currency'
    ORDER BY observed_at DESC,id DESC LIMIT 1;
  INSERT INTO public.price_observations(user_id,listing_id,price,currency,availability,extraction_status,source_url,observed_at,
      matching_status,extraction_error,extracted_product,capture_event_id,recording_payload)
    VALUES(auth.uid(),l.id,amount,o->>'currency',o->>'availability',o->>'extraction_status',o->>'source_url',stamp,
      match_status,o->>'extraction_error',evidence->'extracted',r.capture_event_id,p) RETURNING * INTO saved;
  IF saved.matching_status<>'confirmed' OR saved.extraction_status NOT IN ('success','partial')
     OR saved.price IS NULL OR saved.currency IS NULL THEN status := 'not_comparable';
  ELSIF previous.id IS NOT NULL THEN
    IF saved.observed_at<=previous.observed_at THEN status := 'out_of_order';
    ELSE
      difference := saved.price-previous.price;
      IF previous.price=0 THEN status := CASE WHEN saved.price=0 THEN 'unchanged' ELSE 'zero_baseline' END;
      ELSE
        percentage := difference*100/previous.price;
        exceeds := abs(difference)*100 > previous.price*cfg.threshold_percent;
        status := CASE WHEN difference=0 THEN 'unchanged' ELSE 'changed' END;
      END IF;
    END IF;
  END IF;
  alert_status := CASE WHEN cfg.alerts_enabled THEN 'not_triggered' ELSE 'disabled' END;
  IF cfg.alerts_enabled AND exceeds THEN
    INSERT INTO public.alerts(user_id,product_id,event_type,severity,title,old_price,new_price,currency,source_url,source_observation_id)
      VALUES(auth.uid(),l.product_id,'competitor_price_change','medium','Competitor price changed',
        previous.price,saved.price,saved.currency,saved.source_url,saved.id) RETURNING * INTO generated;
    alert_status := 'created';
  END IF;
  change := jsonb_build_object('status',status,'previous_observation_id',previous.id,
    'threshold_percent',cfg.threshold_percent::text,'price_difference',difference::text,
    'percentage_change',percentage::text,'exceeds_threshold',exceeds);
  response := jsonb_build_object('observation',to_jsonb(saved)||jsonb_build_object('price',saved.price::text),
    'change',change,'alert_status',alert_status,'replayed',false,
    'alert',CASE WHEN generated.id IS NULL THEN NULL ELSE to_jsonb(generated)||
      jsonb_build_object('old_price',generated.old_price::text,'new_price',generated.new_price::text) END);
  UPDATE rivalsense_private.capture_receipts SET state='completed',result=response
    WHERE user_id=auth.uid() AND request_key=r.request_key;
  RETURN response;
END $$;

-- Transfer ONLY these functions, not table ownership. Administrator must be able
-- to SET ROLE rivalsense_recorder. No membership is granted to API roles.
GRANT CREATE ON SCHEMA public,rivalsense_private TO rivalsense_recorder;
ALTER FUNCTION rivalsense_private.verify_command(text,text,text,boolean) OWNER TO rivalsense_recorder;
ALTER FUNCTION rivalsense_private.reserve_quota(uuid,integer) OWNER TO rivalsense_recorder;
ALTER FUNCTION rivalsense_private.guard_identity() OWNER TO rivalsense_recorder;
ALTER FUNCTION public.rivalsense_rate_limit(text,text) OWNER TO rivalsense_recorder;
ALTER FUNCTION public.rivalsense_capture_receipt(text,text) OWNER TO rivalsense_recorder;
ALTER FUNCTION public.rivalsense_record_verified_capture(text,text) OWNER TO rivalsense_recorder;
REVOKE CREATE ON SCHEMA public,rivalsense_private FROM rivalsense_recorder;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rivalsense_private FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.rivalsense_rate_limit(text,text),public.rivalsense_capture_receipt(text,text),
  public.rivalsense_record_verified_capture(text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.rivalsense_rate_limit(text,text),public.rivalsense_capture_receipt(text,text),
  public.rivalsense_record_verified_capture(text,text) TO authenticated;

-- Fail the whole transaction if unexpected inherited/column privileges remain.
DO $$ DECLARE who text; t regclass; a record; BEGIN
  FOREACH who IN ARRAY ARRAY['anon','authenticated'] LOOP
    FOREACH t IN ARRAY ARRAY['public.products'::regclass,'public.competitor_listings'::regclass,
        'public.price_observations'::regclass,'public.alerts'::regclass] LOOP
      IF has_table_privilege(who,t,'DELETE') OR has_table_privilege(who,t,'TRUNCATE')
         OR has_table_privilege(who,t,'TRIGGER') OR has_table_privilege(who,t,'REFERENCES') THEN
        RAISE EXCEPTION 'Residual destructive privileges: % %',who,t; END IF;
      FOR a IN SELECT attnum,attname FROM pg_attribute WHERE attrelid=t AND attnum>0 AND NOT attisdropped LOOP
        IF has_column_privilege(who,t,a.attnum,'UPDATE') AND NOT (who='authenticated' AND
          ((t='public.products'::regclass AND a.attname IN ('selling_price','cost_price','is_archived'))
          OR (t='public.competitor_listings'::regclass AND a.attname IN ('competitor_name','is_active'))
          OR (t='public.alerts'::regclass AND a.attname='status'))) THEN
          RAISE EXCEPTION 'Residual protected UPDATE: % % %',who,t,a.attname; END IF;
        IF t IN ('public.price_observations'::regclass,'public.alerts'::regclass)
           AND has_column_privilege(who,t,a.attnum,'INSERT') THEN
          RAISE EXCEPTION 'Residual untrusted INSERT: % %',who,t; END IF;
      END LOOP;
    END LOOP;
  END LOOP;
  IF pg_has_role('authenticated','rivalsense_recorder','MEMBER')
     OR pg_has_role('anon','rivalsense_recorder','MEMBER')
     OR pg_has_role('authenticator','rivalsense_recorder','MEMBER') THEN
    RAISE EXCEPTION 'Recorder role must not be reachable by API roles'; END IF;
END $$;
COMMIT;
-- Deliberately no secret provisioning, alert enablement, purging, or account changes.
