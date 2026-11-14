-- READ ONLY. Run manually only with separate read-only authorization.
-- Never select recording_config values, secrets, JWT settings, or application rows.
-- Export every page. Change OFFSET 0 to 100, 200, ... until exported total_rows
-- is reached. Do not trust an editor's 100-row display/export cap.
SELECT current_setting('server_version_num')::integer AS server_version_num, current_user, session_user;

-- Ownership, RLS, and schema ownership (including proposed private objects).
SELECT n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner) AS owner,
 c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(n.nspowner) AS schema_owner,
 count(*) OVER() AS total_rows
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE (n.nspname='public' AND c.relname IN ('products','competitor_listings','price_observations','alerts'))
 OR n.nspname='rivalsense_private'
ORDER BY n.nspname,c.relname LIMIT 100 OFFSET 0;

-- Raw relation ACLs include PUBLIC (grantee 0); unlike role_table_grants they
-- are not restricted to the current user's enabled grantor/grantee roles.
SELECT n.nspname,c.relname,coalesce(g.rolname,'PUBLIC') AS grantee,
 pg_get_userbyid(a.grantor) AS grantor,a.privilege_type,a.is_grantable,
 count(*) OVER() AS total_rows
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
LEFT JOIN pg_roles g ON g.oid=a.grantee
WHERE (n.nspname='public' AND c.relname IN ('products','competitor_listings','price_observations','alerts'))
 OR n.nspname='rivalsense_private'
ORDER BY n.nspname,c.relname,grantee,a.privilege_type,grantor LIMIT 100 OFFSET 0;

-- Explicit column ACLs, independently from table-derived effective privileges.
SELECT n.nspname,c.relname,col.attname,coalesce(g.rolname,'PUBLIC') AS grantee,
 pg_get_userbyid(a.grantor) AS grantor,a.privilege_type,a.is_grantable,count(*) OVER() AS total_rows
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute col ON col.attrelid=c.oid AND col.attnum>0 AND NOT col.attisdropped
CROSS JOIN LATERAL aclexplode(col.attacl) a LEFT JOIN pg_roles g ON g.oid=a.grantee
WHERE n.nspname='public' AND c.relname IN ('products','competitor_listings','price_observations','alerts')
ORDER BY c.relname,col.attnum,grantee,a.privilege_type,grantor LIMIT 100 OFFSET 0;

-- Effective column privileges capture table grants and inherited grants too.
SELECT r.rolname,c.relname,col.attname,
 has_column_privilege(r.oid,c.oid,col.attnum,'SELECT') AS can_select,
 has_column_privilege(r.oid,c.oid,col.attnum,'INSERT') AS can_insert,
 has_column_privilege(r.oid,c.oid,col.attnum,'UPDATE') AS can_update,
 has_column_privilege(r.oid,c.oid,col.attnum,'REFERENCES') AS can_reference,
 count(*) OVER() AS total_rows
FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute col ON col.attrelid=c.oid AND col.attnum>0 AND NOT col.attisdropped
WHERE r.rolname IN ('anon','authenticated','authenticator','rivalsense_recorder','service_role')
 AND n.nspname='public' AND c.relname IN ('products','competitor_listings','price_observations','alerts')
ORDER BY r.rolname,c.relname,col.attnum LIMIT 100 OFFSET 0;

SELECT r.rolname,c.relname,
 has_table_privilege(r.oid,c.oid,'DELETE') AS can_delete,
 has_table_privilege(r.oid,c.oid,'TRUNCATE') AS can_truncate,
 has_table_privilege(r.oid,c.oid,'TRIGGER') AS can_trigger,
 pg_get_userbyid(c.relowner)=r.rolname AS is_owner,count(*) OVER() AS total_rows
FROM pg_roles r CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE r.rolname IN ('anon','authenticated','authenticator','rivalsense_recorder','service_role')
 AND n.nspname='public' AND c.relname IN ('products','competitor_listings','price_observations','alerts')
ORDER BY r.rolname,c.relname LIMIT 100 OFFSET 0;

SELECT rolname,rolsuper,rolbypassrls,rolinherit,rolcanlogin,rolcreaterole,rolcreatedb
FROM pg_roles WHERE rolname IN ('anon','authenticated','authenticator','rivalsense_recorder','postgres','service_role',current_user)
ORDER BY rolname;

-- Direct membership options using to_jsonb so pre-16 catalogs remain readable.
SELECT parent.rolname AS granted_role,member.rolname AS member,m.admin_option,
 to_jsonb(m)->>'inherit_option' AS inherit_option,to_jsonb(m)->>'set_option' AS set_option,
 count(*) OVER() AS total_rows
FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid
JOIN pg_roles member ON member.oid=m.member
ORDER BY member.rolname,parent.rolname LIMIT 100 OFFSET 0;

WITH RECURSIVE memberships AS (
 SELECT r.oid AS start_oid,r.oid AS role_oid,ARRAY[r.oid] AS path
 FROM pg_roles r WHERE r.rolname IN ('anon','authenticated','authenticator','rivalsense_recorder',current_user)
 UNION ALL
 SELECT x.start_oid,m.roleid,x.path||m.roleid FROM memberships x
 JOIN pg_auth_members m ON m.member=x.role_oid WHERE NOT m.roleid=ANY(x.path)
)
SELECT DISTINCT pg_get_userbyid(start_oid) AS member,pg_get_userbyid(role_oid) AS reachable_role
FROM memberships ORDER BY member,reachable_role;
-- Membership reachability is conservative, not proof of SET/INHERIT options.
-- On PostgreSQL 16+, additionally inspect pg_has_role(member,role,'SET') and
-- pg_has_role(member,role,'USAGE') for candidate administrator/recorder paths.

SELECT n.nspname,pg_get_userbyid(n.nspowner) AS owner,coalesce(g.rolname,'PUBLIC') AS grantee,
 a.privilege_type,a.is_grantable
FROM pg_namespace n CROSS JOIN LATERAL aclexplode(coalesce(n.nspacl,acldefault('n',n.nspowner))) a
LEFT JOIN pg_roles g ON g.oid=a.grantee
WHERE n.nspname IN ('public','auth','extensions','rivalsense_private')
ORDER BY n.nspname,grantee,a.privilege_type;

SELECT pg_get_userbyid(d.defaclrole) AS creator,coalesce(n.nspname,'ALL SCHEMAS') AS schema_name,
 d.defaclobjtype,coalesce(g.rolname,'PUBLIC') AS grantee,a.privilege_type,a.is_grantable,
 count(*) OVER() AS total_rows
FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) a LEFT JOIN pg_roles g ON g.oid=a.grantee
ORDER BY creator,schema_name,d.defaclobjtype,grantee,a.privilege_type LIMIT 100 OFFSET 0;

SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) AS arguments,
 pg_get_userbyid(p.proowner) AS owner,p.prosecdef,coalesce(g.rolname,'PUBLIC') AS grantee,
 a.privilege_type,a.is_grantable,count(*) OVER() AS total_rows
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
LEFT JOIN pg_roles g ON g.oid=a.grantee
WHERE p.proname LIKE 'rivalsense_%' OR n.nspname='rivalsense_private' OR p.proname IN ('hmac','uid')
ORDER BY n.nspname,p.proname,arguments,grantee LIMIT 100 OFFSET 0;

SELECT c.conrelid::regclass AS table_name,c.conname,c.confdeltype,
 pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c
WHERE c.conrelid IN ('public.products'::regclass,'public.competitor_listings'::regclass,
 'public.price_observations'::regclass,'public.alerts'::regclass)
ORDER BY table_name,c.conname;
SELECT t.tgrelid::regclass AS table_name,t.tgname,t.tgisinternal,pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t WHERE t.tgrelid IN ('public.products'::regclass,'public.competitor_listings'::regclass,
 'public.price_observations'::regclass,'public.alerts'::regclass) ORDER BY table_name,t.tgname;
-- Also verify the private schema is NOT exposed in Data API configuration in
-- the dashboard; that application setting is not established by these ACLs.
