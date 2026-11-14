-- READ ONLY. Review these outputs in the Supabase SQL editor before any migration.
-- Supplement with inspect_security_readonly.sql. Export all ordered pages and
-- reconcile total_rows; a 100-row export is not a complete permission audit.
-- Share schema results only. Never SELECT signing secrets, JWT settings, or user rows.
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale,
       is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('products','competitor_listings','price_observations','alerts')
ORDER BY table_name, ordinal_position;

SELECT tablename, policyname, roles, cmd, qual, with_check
FROM pg_policies WHERE schemaname = 'public'
  AND tablename IN ('products','competitor_listings','price_observations','alerts');

SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'
  AND tablename IN ('products','competitor_listings','price_observations','alerts');

SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants
WHERE table_schema = 'public' AND grantee IN ('anon','authenticated')
  AND table_name IN ('products','competitor_listings','price_observations','alerts');

SELECT c.relname, c.relrowsecurity, pg_get_constraintdef(k.oid) AS constraint_definition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_constraint k ON k.conrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relname IN ('products','competitor_listings','price_observations','alerts');

SELECT table_name,column_name,grantee,privilege_type
FROM information_schema.column_privileges
WHERE table_schema='public' AND table_name IN ('price_observations','alerts');

SELECT r.rolname,r.rolsuper,r.rolbypassrls,r.rolinherit
FROM pg_roles r WHERE r.rolname IN ('anon','authenticated','authenticator','rivalsense_recorder');
SELECT parent.rolname AS granted_role,
       member.rolname AS member
FROM pg_auth_members m
JOIN pg_roles parent ON parent.oid = m.roleid
JOIN pg_roles member ON member.oid = m.member
WHERE parent.rolname IN (
    'anon',
    'authenticated',
    'authenticator',
    'rivalsense_recorder'
)
OR member.rolname IN (
    'anon',
    'authenticated',
    'authenticator',
    'rivalsense_recorder'
);
SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.prosecdef,
       pg_get_userbyid(p.proowner) AS owner,p.proacl
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE p.proname LIKE 'rivalsense_%' OR p.proname='hmac';
SELECT e.extname,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace;
SELECT event_object_table,trigger_name,action_statement FROM information_schema.triggers
WHERE event_object_schema='public' AND event_object_table IN ('products','competitor_listings','price_observations','alerts');
