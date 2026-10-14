-- ShopStore's · esquema en Supabase (Postgres)
--
-- Es la traduccion de `ESQUEMA` en `backend/basedatos.py`, con cuatro cambios a
-- proposito:
--
-- 1. **Cada fila tiene dueno (`user_id`).** Se llena solo con la sesion iniciada
--    (`auth.uid()`), y el RLS de abajo hace que cada quien vea y toque **solo lo
--    suyo**. Hoy hay una sola persona; aun asi va en todas las tablas, porque si
--    algun dia queda abierto el registro por error, quien se registre entra a
--    una tienda vacia, no a la de ella.
-- 2. **Tipos de verdad.** Montos en `numeric` (el `REAL` de SQLite redondea
--    centavos), fechas en `timestamptz`, `activo` y `en_catalogo` en `boolean`.
-- 3. **Fuera `sincronizado_en`.** Era para empujar a Neon; aca la nube es la base.
-- 4. **Las fotos siguen dentro de la base**, como `bytea`. Se penso en mandarlas a
--    Storage, pero pesan tan poco (ver `producto_fotos`) que no vale la pena el
--    viaje extra por cada imagen.
--
-- Se puede correr mas de una vez: lo que ya existe no se toca.
--
-- **Como se corre:** en Supabase, SQL Editor -> New query -> pegar todo -> Run.

-- ---------------------------------------------------------------------------
-- Tablas
-- ---------------------------------------------------------------------------

create table if not exists public.productos (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    nombre          text not null,
    descripcion     text not null default '',
    costo_usd       numeric not null default 0,
    precio_usd      numeric not null default 0,
    stock           numeric not null default 0,
    en_catalogo     boolean not null default true,
    activo          boolean not null default true,
    creado_en       timestamptz not null default now(),
    actualizado_en  timestamptz not null default now()
);

create table if not exists public.producto_fotos (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    producto_id     uuid not null references public.productos(id) on delete cascade,
    orden           integer not null,
    -- Los tres tamanos que arma `backend/fotos.py`. Pesan ~3, ~10 y ~56 KB: cien
    -- productos con tres fotos son unos 20 MB, holgado dentro de la base.
    miniatura       bytea not null,
    catalogo        bytea not null,
    completa        bytea not null,
    creado_en       timestamptz not null default now(),
    unique (producto_id, orden)
);

create table if not exists public.movimientos_inventario (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    producto_id     uuid not null references public.productos(id),
    delta           numeric not null,
    motivo          text not null,
    referencia_id   uuid,
    nota            text not null default '',
    fecha           timestamptz not null default now()
);

create table if not exists public.clientes (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    nombre          text not null,
    telefono        text not null default '',
    notas           text not null default '',
    activo          boolean not null default true,
    creado_en       timestamptz not null default now(),
    actualizado_en  timestamptz not null default now()
);

create table if not exists public.ventas (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null default auth.uid() references auth.users on delete cascade,
    correlativo         integer not null,
    cliente_id          uuid references public.clientes(id),
    fecha               timestamptz not null default now(),
    tipo                text not null,
    total_usd           numeric not null,
    tasa_usada          numeric not null,
    fecha_pago_prevista date,
    estado              text not null default 'activa',
    -- El numero de venta es correlativo **por dueno**: dos tiendas pueden tener
    -- cada una su venta 1.
    unique (user_id, correlativo)
);

create table if not exists public.venta_lineas (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null default auth.uid() references auth.users on delete cascade,
    venta_id         uuid not null references public.ventas(id),
    producto_id      uuid not null references public.productos(id),
    nombre_congelado text not null,
    cantidad         numeric not null,
    precio_unit_usd  numeric not null,
    costo_unit_usd   numeric not null
);

create table if not exists public.metodos_pago (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    nombre          text not null,
    moneda          text not null,
    orden           integer not null default 0,
    activo          boolean not null default true,
    creado_en       timestamptz not null default now(),
    actualizado_en  timestamptz not null default now()
);

create table if not exists public.venta_pagos (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    venta_id        uuid not null references public.ventas(id),
    metodo_id       uuid references public.metodos_pago(id),
    metodo_nombre   text not null,
    moneda          text not null,
    monto           numeric not null,
    monto_usd       numeric not null
);

create table if not exists public.abonos (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    cliente_id      uuid not null references public.clientes(id),
    fecha           timestamptz not null default now(),
    monto_usd       numeric not null,
    moneda_recibida text not null,
    monto_recibido  numeric not null,
    tasa_usada      numeric not null,
    metodo_id       uuid references public.metodos_pago(id),
    metodo_nombre   text not null default '',
    nota            text not null default ''
);

create table if not exists public.abono_aplicaciones (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    abono_id        uuid not null references public.abonos(id),
    venta_id        uuid not null references public.ventas(id),
    monto_usd       numeric not null
);

create table if not exists public.gastos (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    fecha           timestamptz not null default now(),
    categoria       text not null,
    descripcion     text not null default '',
    monto_usd       numeric not null,
    moneda_pagada   text not null,
    monto_pagado    numeric not null,
    tasa_usada      numeric not null,
    activo          boolean not null default true
);

-- La tasa del dia y otros valores sueltos. La clave es por dueno.
create table if not exists public.configuracion (
    user_id         uuid not null default auth.uid() references auth.users on delete cascade,
    clave           text not null,
    valor           text not null,
    primary key (user_id, clave)
);

-- ---------------------------------------------------------------------------
-- Indices: los de SQLite, con el dueno adelante (todo filtra por el)
-- ---------------------------------------------------------------------------

create index if not exists idx_productos_activos on public.productos(user_id, activo, nombre);
create index if not exists idx_fotos_producto    on public.producto_fotos(producto_id, orden);
create index if not exists idx_movimientos_prod  on public.movimientos_inventario(producto_id);
create index if not exists idx_ventas_cliente    on public.ventas(cliente_id, estado);
create index if not exists idx_ventas_fecha      on public.ventas(user_id, fecha);
create index if not exists idx_lineas_venta      on public.venta_lineas(venta_id);
create index if not exists idx_pagos_venta       on public.venta_pagos(venta_id);
create index if not exists idx_abonos_cliente    on public.abonos(cliente_id);
create index if not exists idx_aplicaciones_venta on public.abono_aplicaciones(venta_id);
create index if not exists idx_gastos_fecha      on public.gastos(user_id, fecha);

-- ---------------------------------------------------------------------------
-- Quien puede tocar que
-- ---------------------------------------------------------------------------
--
-- Al crear el proyecto se desmarco «exponer tablas nuevas»: ninguna tabla es
-- visible hasta que se diga aca. Se le da acceso **solo a `authenticated`** (con
-- sesion iniciada). `anon` —quien tiene la clave publicable y nada mas— no recibe
-- nada, y se le quita por si acaso.
--
-- Y encima, RLS: aun con sesion, cada fila se ve solo si es tuya.

do $$
declare
    t text;
begin
    foreach t in array array[
        'productos', 'producto_fotos', 'movimientos_inventario', 'clientes',
        'ventas', 'venta_lineas', 'metodos_pago', 'venta_pagos', 'abonos',
        'abono_aplicaciones', 'gastos', 'configuracion'
    ] loop
        execute format('alter table public.%I enable row level security', t);
        execute format('revoke all on public.%I from anon', t);
        execute format('grant select, insert, update, delete on public.%I to authenticated', t);
        execute format('drop policy if exists solo_lo_mio on public.%I', t);
        execute format(
            'create policy solo_lo_mio on public.%I for all to authenticated '
            'using (user_id = (select auth.uid())) '
            'with check (user_id = (select auth.uid()))', t);
    end loop;
end
$$;
