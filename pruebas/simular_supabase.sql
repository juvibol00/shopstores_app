-- Lo que Supabase trae de fabrica y un Postgres comun no. SOLO PARA PRUEBAS.
--
-- Con esto, `supabase/01_esquema.sql` y `02_funciones.sql` corren aca **sin tocar
-- una letra**: las pruebas ejercitan los mismos archivos que se pegan en el panel.
--
-- Lo unico simulado es quien llama. En Supabase, `auth.uid()` sale del token de la
-- sesion; aca, de una variable que la prueba fija al conectarse. Es la misma
-- definicion que usa Supabase, que lee las dos formas del dato.

-- Los roles son de todo el servidor, no de cada base: la segunda suite ya los
-- encuentra creados.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin;
    end if;
end
$$;
grant usage on schema public to anon, authenticated;

create schema auth;
grant usage on schema auth to anon, authenticated;

create table auth.users (id uuid primary key);

create function auth.uid() returns uuid language sql stable as $$
    select coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    )::uuid
$$;
grant execute on function auth.uid() to anon, authenticated;
