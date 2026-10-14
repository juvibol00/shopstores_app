-- ShopStore's · las operaciones de la app, dentro de Supabase
--
-- Cada funcion de `backend/basedatos.py` que lee o escribe tiene aca su gemela con
-- **el mismo nombre**. La app las llama por la red (`/rest/v1/rpc/<nombre>`) con
-- un solo argumento, `p`, que trae todos los datos en un objeto JSON, y recibe JSON.
--
-- Por que funciones y no consultas sueltas a las tablas:
--
-- 1. **Una ida y vuelta por operacion.** Cada viaje a Supabase tarda de 0,2 a 0,5
--    segundos. Una venta en SQLite eran quince consultas; hechas una por una por la
--    red, el boton «Cobrar» tardaria varios segundos.
-- 2. **Todo o nada.** Una funcion corre entera dentro de una transaccion. Si se
--    corta el internet o algo falla a mitad de una venta, no queda una venta sin
--    descuento de stock ni un abono repartido a medias.
-- 3. **La misma regla en todos lados.** El reparto de un abono o el cuadre de los
--    pagos viven en un solo lugar, no copiados en cada telefono.
--
-- Todas corren como **quien llama** (`security invoker`): el RLS del esquema
-- sigue mandando, y cada dueno solo ve y toca lo suyo aunque llame a la funcion
-- con datos ajenos.
--
-- Los errores que se le muestran a la vendedora salen con `privado.fallar`: el
-- texto va tal cual a la pantalla, y la pista (`hint`) le dice a la app que
-- excepcion levantar (`SinExistencia`, `PagoNoCuadra` o `ValueError`).
--
-- Se puede correr mas de una vez: cada funcion se reemplaza entera.
--
-- **Como se corre:** igual que el esquema. SQL Editor -> New query -> pegar -> Run.

-- ---------------------------------------------------------------------------
-- Cambio de las fotos (la tabla esta vacia: se puede rehacer sin perder nada)
-- ---------------------------------------------------------------------------
-- La primera version del esquema guardaba rutas a Storage. Se decidio guardarlas
-- dentro de la base (ver `01_esquema.sql`). Esto solo hace algo en un proyecto
-- creado con aquella version; en uno nuevo, las columnas ya estan bien.

do $$
begin
    if exists (select 1 from information_schema.columns
               where table_schema = 'public' and table_name = 'producto_fotos'
                 and column_name = 'ruta_miniatura') then
        delete from public.producto_fotos;
        alter table public.producto_fotos
            drop column ruta_miniatura,
            drop column ruta_catalogo,
            drop column ruta_completa,
            add column miniatura bytea not null,
            add column catalogo  bytea not null,
            add column completa  bytea not null;
    end if;
end
$$;

-- ---------------------------------------------------------------------------
-- Piezas internas: no se ven desde la red
-- ---------------------------------------------------------------------------
-- El esquema `privado` no esta publicado en la API: solo se puede usar desde
-- adentro de las funciones de abajo.

create schema if not exists privado;
revoke all on schema privado from public;
grant usage on schema privado to authenticated;

-- Corta la operacion con un mensaje para la pantalla.
create or replace function privado.fallar(mensaje text, tipo text default 'ValueError')
returns void language plpgsql as $$
begin
    raise exception using message = mensaje, errcode = 'P0001', hint = tipo;
end
$$;

-- Un id escrito como texto, o `null` si no es un id valido. Asi un id inventado
-- se comporta como uno que no existe ("esa venta no existe"), en vez de cortar
-- con un error de formato que la pantalla no sabe explicar.
create or replace function privado.id(texto text) returns uuid
language plpgsql immutable set search_path = '' as $$
begin
    return texto::uuid;
exception when invalid_text_representation then
    return null;
end
$$;

-- `3.000` -> `3`, `2.50` -> `2.5`: lo mismo que `{x:g}` en Python.
create or replace function privado.g(x numeric) returns text
language sql immutable set search_path = '' as $$
    select trim_scale(x)::text
$$;

-- `1234.5` -> `1,234.50`: lo mismo que `{x:,.2f}` en Python.
create or replace function privado.dinero(x numeric) returns text
language sql immutable set search_path = '' as $$
    select to_char(round(x, 2), 'FM999,999,999,990.00')
$$;

-- El buscador: vacio coincide con todo; si no, busca en cualquiera de los dos.
create or replace function privado.coincide(busqueda text, a text, b text)
returns boolean language sql immutable set search_path = '' as $$
    select coalesce(trim(busqueda), '') = ''
        or a ilike '%' || trim(busqueda) || '%'
        or b ilike '%' || trim(busqueda) || '%'
$$;

-- Escribe el movimiento y actualiza el resumen. Siempre juntos.
--
-- `productos.stock` es un resumen: existe para que las listas no tengan que sumar
-- movimientos en cada consulta. La verdad esta en los movimientos, y
-- `recalcular_stock` lo reconstruye desde ahi.
--
-- `clock_timestamp()` y no `now()`: dentro de una venta se escriben varios
-- movimientos en la misma transaccion, y con `now()` empatarian todos.
create or replace function privado.mover(producto uuid, delta numeric, motivo text,
                                         referencia uuid default null,
                                         nota text default '')
returns void language plpgsql security invoker set search_path = '' as $$
begin
    insert into public.movimientos_inventario
        (producto_id, delta, motivo, referencia_id, nota, fecha)
    values (producto, delta, motivo, referencia, coalesce(nota, ''), clock_timestamp());
    update public.productos
       set stock = stock + delta, actualizado_en = now()
     where id = producto;
end
$$;

-- Las facturas a credito con algo por cobrar, **de la mas vieja a la mas nueva**:
-- ese es el orden en que se reparte un abono. `correlativo` desempata dos del
-- mismo instante.
--
-- Por debajo de medio centavo se considera saldada: dividir bolivares entre la
-- tasa deja restos minusculos que nadie puede terminar de pagar.
create or replace function privado.pendientes(cliente uuid default null)
returns table (cliente_id uuid, id uuid, correlativo integer, fecha timestamptz,
               fecha_pago_prevista date, total_usd numeric, abonado numeric,
               restante numeric)
language sql stable security invoker set search_path = '' as $$
    select v.cliente_id, v.id, v.correlativo, v.fecha, v.fecha_pago_prevista,
           v.total_usd,
           coalesce(sum(a.monto_usd), 0),
           v.total_usd - coalesce(sum(a.monto_usd), 0)
      from public.ventas v
      left join public.abono_aplicaciones a on a.venta_id = v.id
     where v.tipo = 'credito' and v.estado = 'activa'
       and (cliente is null or v.cliente_id = cliente)
     group by v.id
    having v.total_usd - coalesce(sum(a.monto_usd), 0) > 0.005
     order by v.fecha, v.correlativo
$$;

-- Pasa cada pago a dolares y comprueba que el reparto cuadre con el total.
--
-- **La regla es estricta: si no cuadra, la venta no se registra.** Es la leccion
-- de SELL-B, donde un reparto que no cerraba se guardaba igual y despues nadie
-- sabia cual de los dos numeros creer.
--
-- El ultimo pago absorbe el resto del redondeo: dividir bolivares entre la tasa da
-- fracciones de centavo, y sin este ajuste la suma de los pagos y el total
-- diferirian en un centavo cada tanto.
create or replace function privado.preparar_pagos(pagos jsonb, total numeric,
                                                  tasa numeric)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare
    pago jsonb;
    metodo record;
    monto numeric;
    en_usd numeric;
    suma numeric := 0;
    listos jsonb := '[]'::jsonb;
    cuantos integer := 0;
    falta numeric;
    resto numeric;
    ultimo integer;
begin
    if pagos is null or jsonb_typeof(pagos) <> 'array'
       or jsonb_array_length(pagos) = 0 then
        return '[]'::jsonb;
    end if;

    for pago in select * from jsonb_array_elements(pagos) loop
        monto := (pago ->> 'monto')::numeric;
        if monto is null or monto <= 0 then
            perform privado.fallar('Cada pago tiene que ser mayor que cero.',
                                   'PagoNoCuadra');
        end if;
        select * into metodo from public.metodos_pago
         where id = privado.id(pago ->> 'metodo_id');
        if not found then
            perform privado.fallar('Uno de los métodos de pago ya no existe.',
                                   'PagoNoCuadra');
        end if;
        en_usd := case when metodo.moneda = 'USD' then monto else monto / tasa end;
        suma := suma + en_usd;
        cuantos := cuantos + 1;
        listos := listos || jsonb_build_array(jsonb_build_object(
            'metodo_id', metodo.id,
            'metodo_nombre', metodo.nombre,
            'moneda', metodo.moneda,
            'monto', monto,
            'monto_usd', round(en_usd, 2)));
    end loop;

    if abs(suma - total) > 0.01 * greatest(1, cuantos) then
        falta := total - suma;
        if falta > 0 then
            perform privado.fallar(format('Faltan $ %s por repartir.',
                                          privado.dinero(falta)), 'PagoNoCuadra');
        end if;
        perform privado.fallar(format('El pago se pasa por $ %s.',
                                      privado.dinero(-falta)), 'PagoNoCuadra');
    end if;

    select round(total - sum((x ->> 'monto_usd')::numeric), 2) into resto
      from jsonb_array_elements(listos) x;
    if resto <> 0 then
        ultimo := cuantos - 1;
        listos := jsonb_set(listos, array[ultimo::text, 'monto_usd'],
            to_jsonb(round((listos -> ultimo ->> 'monto_usd')::numeric + resto, 2)));
    end if;
    return listos;
end
$$;

-- ---------------------------------------------------------------------------
-- Cuenta
-- ---------------------------------------------------------------------------

-- Lo que hacia `conexion()` la primera vez: dejar la cuenta lista para vender.
-- Hoy es solo sembrar los metodos de pago, y **solo si no tiene ninguno**: si ella
-- borro alguno, no vuelve a aparecer.
create or replace function public.preparar_cuenta(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
begin
    if not exists (select 1 from public.metodos_pago) then
        insert into public.metodos_pago (nombre, moneda, orden) values
            ('Efectivo en dólares', 'USD', 0),
            ('Efectivo en bolívares', 'Bs', 1),
            ('Pago móvil', 'Bs', 2),
            ('Transferencia', 'Bs', 3),
            ('Zelle', 'USD', 4);
    end if;
    return to_jsonb(true);
end
$$;

-- ---------------------------------------------------------------------------
-- Configuracion
-- ---------------------------------------------------------------------------

create or replace function public.leer_config(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(valor) from public.configuracion where clave = p ->> 'clave'
$$;

create or replace function public.escribir_config(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    insert into public.configuracion (clave, valor)
    values (p ->> 'clave', p ->> 'valor')
    on conflict (user_id, clave) do update set valor = excluded.valor
    returning to_jsonb(true)
$$;

-- ---------------------------------------------------------------------------
-- Productos
-- ---------------------------------------------------------------------------

-- Los activos, por nombre, con la miniatura de su foto principal en base64.
create or replace function public.listar_productos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(fila order by orden), '[]'::jsonb) from (
        select to_jsonb(pr) || jsonb_build_object(
                   'miniatura', encode(f.miniatura, 'base64')) as fila,
               lower(pr.nombre) as orden
          from public.productos pr
          left join public.producto_fotos f
                 on f.producto_id = pr.id and f.orden = 1
         where pr.activo
           and privado.coincide(p ->> 'busqueda', pr.nombre, pr.descripcion)
         order by lower(pr.nombre)
         limit (p ->> 'limite')::integer
    ) x
$$;

create or replace function public.contar_productos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(count(*)) from public.productos
     where activo and privado.coincide(p ->> 'busqueda', nombre, descripcion)
$$;

create or replace function public.obtener_producto(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(pr) from public.productos pr where id = privado.id(p ->> 'id')
$$;

create or replace function public.crear_producto(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    nuevo uuid;
begin
    insert into public.productos (nombre, descripcion, costo_usd, precio_usd,
                                  en_catalogo)
    values (trim(p ->> 'nombre'), trim(coalesce(p ->> 'descripcion', '')),
            (p ->> 'costo_usd')::numeric, (p ->> 'precio_usd')::numeric,
            coalesce((p ->> 'en_catalogo')::boolean, true))
    returning id into nuevo;
    if coalesce((p ->> 'stock_inicial')::numeric, 0) <> 0 then
        perform privado.mover(nuevo, (p ->> 'stock_inicial')::numeric, 'alta',
                              null, 'Existencia al registrar el producto');
    end if;
    return to_jsonb(nuevo);
end
$$;

-- No toca el stock: el stock solo cambia por un movimiento.
create or replace function public.actualizar_producto(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    update public.productos
       set nombre = trim(p ->> 'nombre'),
           descripcion = trim(coalesce(p ->> 'descripcion', '')),
           costo_usd = (p ->> 'costo_usd')::numeric,
           precio_usd = (p ->> 'precio_usd')::numeric,
           en_catalogo = (p ->> 'en_catalogo')::boolean,
           actualizado_en = now()
     where id = privado.id(p ->> 'id')
    returning to_jsonb(true)
$$;

-- Borrado logico: las fotos y los movimientos son el historial de ventas hechas.
create or replace function public.eliminar_producto(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    update public.productos set activo = false, actualizado_en = now()
     where id = privado.id(p ->> 'id')
    returning to_jsonb(true)
$$;

-- ---------------------------------------------------------------------------
-- Stock
-- ---------------------------------------------------------------------------

-- Entrada de mercancia. **No es un gasto**: el costo ya se cuenta al vender.
create or replace function public.reabastecer(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
begin
    perform privado.mover(privado.id(p ->> 'producto_id'), (p ->> 'cantidad')::numeric,
                          'compra', null, coalesce(p ->> 'nota', ''));
    if p ->> 'costo_usd' is not null then
        update public.productos
           set costo_usd = (p ->> 'costo_usd')::numeric, actualizado_en = now()
         where id = privado.id(p ->> 'producto_id');
    end if;
    return to_jsonb(true);
end
$$;

-- "Conte y hay 7, no 5". Se guarda la diferencia, no el total.
create or replace function public.ajustar_stock(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    actual numeric;
    delta numeric;
begin
    select stock into actual from public.productos
     where id = privado.id(p ->> 'producto_id') for update;
    if not found then
        perform privado.fallar('Ese producto no existe.');
    end if;
    delta := (p ->> 'nuevo_total')::numeric - actual;
    if delta = 0 then
        return to_jsonb(0);
    end if;
    perform privado.mover(privado.id(p ->> 'producto_id'), delta, 'ajuste', null,
                          p ->> 'nota');
    return to_jsonb(delta);
end
$$;

-- La red de seguridad si el resumen y la verdad alguna vez se separan.
create or replace function public.recalcular_stock(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    total numeric;
begin
    select coalesce(sum(delta), 0) into total from public.movimientos_inventario
     where producto_id = privado.id(p ->> 'producto_id');
    update public.productos set stock = total
     where id = privado.id(p ->> 'producto_id');
    return to_jsonb(total);
end
$$;

create or replace function public.movimientos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(m) order by m.fecha desc), '[]'::jsonb)
      from (select * from public.movimientos_inventario
             where producto_id = privado.id(p ->> 'producto_id')
             order by fecha desc
             limit coalesce((p ->> 'limite')::integer, 50)) m
$$;

-- ---------------------------------------------------------------------------
-- Fotos (las imagenes viajan en base64 dentro del JSON)
-- ---------------------------------------------------------------------------

create or replace function public.listar_fotos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(
               jsonb_build_object('id', id, 'producto_id', producto_id,
                                  'orden', orden,
                                  'miniatura', encode(miniatura, 'base64'))
               || case when coalesce((p ->> 'con_datos')::boolean, false)
                       then jsonb_build_object(
                                'catalogo', encode(catalogo, 'base64'),
                                'completa', encode(completa, 'base64'))
                       else '{}'::jsonb end
               order by orden), '[]'::jsonb)
      from public.producto_fotos
     where producto_id = privado.id(p ->> 'producto_id')
$$;

create or replace function public.obtener_foto(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(encode(case p ->> 'tamano'
                               when 'miniatura' then miniatura
                               when 'catalogo' then catalogo
                               else completa end, 'base64'))
      from public.producto_fotos where id = privado.id(p ->> 'id')
$$;

-- La primera foto de un producto queda en el orden 1, y esa es la principal.
create or replace function public.guardar_foto(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    producto uuid := privado.id(p ->> 'producto_id');
    libre integer;
    nueva uuid;
begin
    -- Se bloquea el producto para que dos fotos subidas a la vez no elijan el
    -- mismo lugar libre.
    perform 1 from public.productos where id = producto for update;
    select n into libre from unnest(array[1, 2, 3]) n
     where n not in (select orden from public.producto_fotos
                      where producto_id = producto)
     order by n limit 1;
    if libre is null then
        perform privado.fallar('Ya tiene tres fotos. Borra una para agregar otra.');
    end if;
    insert into public.producto_fotos (producto_id, orden, miniatura, catalogo,
                                       completa)
    values (producto, libre, decode(p ->> 'miniatura', 'base64'),
            decode(p ->> 'catalogo', 'base64'), decode(p ->> 'completa', 'base64'))
    returning id into nueva;
    return to_jsonb(nueva);
end
$$;

-- Borrado de verdad: una foto no es historia contable. Si se borra la principal,
-- la siguiente ocupa su lugar; sin principal el producto no se veria en la lista.
create or replace function public.eliminar_foto(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    producto uuid;
    f record;
    n integer := 0;
begin
    delete from public.producto_fotos where id = privado.id(p ->> 'id')
    returning producto_id into producto;
    if producto is null then
        return to_jsonb(false);
    end if;
    -- De menor a mayor: cada foto baja a un lugar que ya quedo libre, asi que
    -- la restriccion `unique (producto_id, orden)` nunca choca a mitad de camino.
    for f in select id from public.producto_fotos
              where producto_id = producto order by orden loop
        n := n + 1;
        update public.producto_fotos set orden = n where id = f.id;
    end loop;
    return to_jsonb(true);
end
$$;

-- Intercambia esta foto con la del orden 1. Pasa por el orden 0 porque el
-- intercambio directo chocaria contra `unique (producto_id, orden)`.
create or replace function public.hacer_principal(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    foto record;
    principal uuid;
begin
    select producto_id, orden into foto from public.producto_fotos
     where id = privado.id(p ->> 'id');
    if not found or foto.orden = 1 then
        return to_jsonb(false);
    end if;
    select id into principal from public.producto_fotos
     where producto_id = foto.producto_id and orden = 1;
    update public.producto_fotos set orden = 0 where id = privado.id(p ->> 'id');
    if principal is not null then
        update public.producto_fotos set orden = foto.orden where id = principal;
    end if;
    update public.producto_fotos set orden = 1 where id = privado.id(p ->> 'id');
    return to_jsonb(true);
end
$$;

-- ---------------------------------------------------------------------------
-- Clientes
-- ---------------------------------------------------------------------------

create or replace function public.listar_clientes(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(c) order by lower(c.nombre)), '[]'::jsonb)
      from (select * from public.clientes
             where activo
               and privado.coincide(p ->> 'busqueda', nombre, telefono)
             order by lower(nombre)
             limit (p ->> 'limite')::integer) c
$$;

create or replace function public.obtener_cliente(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(c) from public.clientes c where id = privado.id(p ->> 'id')
$$;

create or replace function public.crear_cliente(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    insert into public.clientes (nombre, telefono, notas)
    values (p ->> 'nombre', coalesce(p ->> 'telefono', ''),
            coalesce(p ->> 'notas', ''))
    returning to_jsonb(id)
$$;

create or replace function public.actualizar_cliente(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    update public.clientes
       set nombre = p ->> 'nombre', telefono = coalesce(p ->> 'telefono', ''),
           notas = coalesce(p ->> 'notas', ''), actualizado_en = now()
     where id = privado.id(p ->> 'id')
    returning to_jsonb(true)
$$;

-- Borrado logico, y solo si no debe nada: si desapareciera con saldo, esa deuda
-- quedaria fuera de los cobros sin que nadie se entere.
create or replace function public.eliminar_cliente(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
begin
    if (select coalesce(sum(restante), 0)
          from privado.pendientes(privado.id(p ->> 'id'))) > 0.005 then
        perform privado.fallar('No se puede borrar un cliente que todavía debe.');
    end if;
    update public.clientes set activo = false, actualizado_en = now()
     where id = privado.id(p ->> 'id');
    return to_jsonb(true);
end
$$;

-- ---------------------------------------------------------------------------
-- Metodos de pago
-- ---------------------------------------------------------------------------

create or replace function public.listar_metodos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(m) order by m.orden, lower(m.nombre)),
                    '[]'::jsonb)
      from public.metodos_pago m
     where m.activo or coalesce((p ->> 'incluir_inactivos')::boolean, false)
$$;

create or replace function public.obtener_metodo(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(m) from public.metodos_pago m where id = privado.id(p ->> 'id')
$$;

-- Se compara sin mayusculas para que no queden "Zelle" y "zelle" como dos.
create or replace function public.crear_metodo(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    nuevo uuid;
begin
    if exists (select 1 from public.metodos_pago
                where lower(nombre) = lower(p ->> 'nombre') and activo) then
        perform privado.fallar(format('Ya existe un método llamado «%s».',
                                      p ->> 'nombre'));
    end if;
    insert into public.metodos_pago (nombre, moneda, orden)
    values (p ->> 'nombre', p ->> 'moneda',
            (select coalesce(max(orden), -1) + 1 from public.metodos_pago))
    returning id into nuevo;
    return to_jsonb(nuevo);
end
$$;

create or replace function public.actualizar_metodo(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
begin
    if exists (select 1 from public.metodos_pago
                where lower(nombre) = lower(p ->> 'nombre') and activo
                  and id <> privado.id(p ->> 'id')) then
        perform privado.fallar(format('Ya existe un método llamado «%s».',
                                      p ->> 'nombre'));
    end if;
    update public.metodos_pago
       set nombre = p ->> 'nombre', moneda = p ->> 'moneda', actualizado_en = now()
     where id = privado.id(p ->> 'id');
    return to_jsonb(true);
end
$$;

-- Borrado logico: las ventas viejas tienen su nombre congelado en `venta_pagos`.
create or replace function public.desactivar_metodo(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
begin
    if (select count(*) from public.metodos_pago where activo) <= 1 then
        perform privado.fallar('Tiene que quedar al menos un método de pago.');
    end if;
    update public.metodos_pago set activo = false, actualizado_en = now()
     where id = privado.id(p ->> 'id');
    return to_jsonb(true);
end
$$;

-- ---------------------------------------------------------------------------
-- Ventas
-- ---------------------------------------------------------------------------

-- Una venta completa. Entra entera o no entra.
--
-- `p.items` llega ya **agrupado por producto** (lo hace la app): si el mismo
-- producto entrara dos veces, cada linea validaria el stock por su cuenta y entre
-- las dos podrian pasarse del disponible.
--
-- **El precio, el costo y el nombre se copian a la linea**, y la tasa a la venta:
-- si el margen se calculara con el costo de hoy, recomprar mas caro reescribiria
-- la ganancia de meses pasados.
create or replace function public.registrar_venta(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    tasa numeric := (p ->> 'tasa_usada')::numeric;
    item jsonb;
    cantidad numeric;
    prod record;
    total numeric := 0;
    lineas jsonb := '[]'::jsonb;
    pagos_listos jsonb;
    pago jsonb;
    linea jsonb;
    venta uuid;
    numero integer;
begin
    for item in select * from jsonb_array_elements(p -> 'items') loop
        cantidad := (item ->> 'cantidad')::numeric;
        -- `for update`: entre que se arma el carrito y se confirma, el stock pudo
        -- cambiar. Se comprueba aca adentro, con la fila bloqueada.
        select id, nombre, precio_usd, costo_usd, stock, activo into prod
          from public.productos where id = privado.id(item ->> 'producto_id')
           for update;
        if not found or not prod.activo then
            perform privado.fallar('Uno de los productos ya no existe.');
        end if;
        if prod.stock < cantidad then
            perform privado.fallar(format('«%s»: quedan %s y se quieren vender %s.',
                                          prod.nombre, privado.g(prod.stock),
                                          privado.g(cantidad)), 'SinExistencia');
        end if;
        total := total + cantidad * prod.precio_usd;
        lineas := lineas || jsonb_build_array(jsonb_build_object(
            'producto_id', prod.id, 'nombre', prod.nombre, 'cantidad', cantidad,
            'precio', prod.precio_usd, 'costo', prod.costo_usd));
    end loop;

    total := round(total, 2);
    -- El reparto se comprueba **antes** de escribir nada.
    pagos_listos := privado.preparar_pagos(p -> 'pagos', total, tasa);

    select coalesce(max(correlativo), 0) + 1 into numero from public.ventas;
    insert into public.ventas (correlativo, cliente_id, tipo, total_usd, tasa_usada,
                               fecha_pago_prevista, estado)
    values (numero, privado.id(p ->> 'cliente_id'), p ->> 'tipo', total, tasa,
            nullif(p ->> 'fecha_pago_prevista', '')::date, 'activa')
    returning id into venta;

    -- El nombre del metodo se congela igual que el del producto.
    for pago in select * from jsonb_array_elements(pagos_listos) loop
        insert into public.venta_pagos (venta_id, metodo_id, metodo_nombre, moneda,
                                        monto, monto_usd)
        values (venta, privado.id(pago ->> 'metodo_id'), pago ->> 'metodo_nombre',
                pago ->> 'moneda', (pago ->> 'monto')::numeric,
                (pago ->> 'monto_usd')::numeric);
    end loop;

    for linea in select * from jsonb_array_elements(lineas) loop
        insert into public.venta_lineas (venta_id, producto_id, nombre_congelado,
                                         cantidad, precio_unit_usd, costo_unit_usd)
        values (venta, privado.id(linea ->> 'producto_id'), linea ->> 'nombre',
                (linea ->> 'cantidad')::numeric, (linea ->> 'precio')::numeric,
                (linea ->> 'costo')::numeric);
        perform privado.mover(privado.id(linea ->> 'producto_id'),
                              -(linea ->> 'cantidad')::numeric, 'venta', venta, '');
    end loop;

    return jsonb_build_object('id', venta, 'correlativo', numero,
                              'total_usd', total, 'tasa_usada', tasa);
end
$$;

-- Marca la venta como anulada y devuelve la mercancia con **movimientos nuevos en
-- sentido contrario**: el historial sigue contando lo que de verdad paso.
create or replace function public.anular_venta(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    venta uuid := privado.id(p ->> 'id');
    estado_actual text;
    abonado numeric;
    linea record;
begin
    select estado into estado_actual from public.ventas where id = venta for update;
    if not found then
        perform privado.fallar('Esa venta no existe.');
    end if;
    if estado_actual = 'anulada' then
        perform privado.fallar('Esa venta ya estaba anulada.');
    end if;
    select coalesce(sum(monto_usd), 0) into abonado
      from public.abono_aplicaciones where venta_id = venta;
    if abonado <> 0 then
        -- Anularla dejaria abonos apuntando a una factura que ya no cuenta.
        perform privado.fallar(format(
            'Esa venta ya tiene $ %s abonados. No se puede anular.',
            privado.dinero(abonado)));
    end if;
    for linea in select producto_id, cantidad from public.venta_lineas
                  where venta_id = venta loop
        perform privado.mover(linea.producto_id, linea.cantidad, 'ajuste', venta,
                              'Devolución por venta anulada');
    end loop;
    update public.ventas set estado = 'anulada' where id = venta;
    return to_jsonb(true);
end
$$;

create or replace function public.obtener_venta(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select jsonb_build_object(
        'venta', to_jsonb(v),
        'lineas', coalesce((select jsonb_agg(to_jsonb(l))
                              from public.venta_lineas l where l.venta_id = v.id),
                           '[]'::jsonb))
      from public.ventas v where v.id = privado.id(p ->> 'id')
$$;

create or replace function public.pagos_de_venta(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb)
      from public.venta_pagos x where venta_id = privado.id(p ->> 'venta_id')
$$;

-- Cuanto entro por cada metodo, cada moneda en la suya. Es lo que cuadra la caja.
create or replace function public.desglose_de_pagos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(x) order by x.monto_usd desc), '[]'::jsonb)
      from (select pg.metodo_nombre, pg.moneda, sum(pg.monto) as monto,
                   sum(pg.monto_usd) as monto_usd, count(*) as veces
              from public.venta_pagos pg
              join public.ventas v on v.id = pg.venta_id
             where v.fecha >= (p ->> 'desde')::timestamptz
               and (p ->> 'hasta' is null or v.fecha < (p ->> 'hasta')::timestamptz)
               and v.estado = 'activa'
             group by pg.metodo_nombre, pg.moneda) x
$$;

-- El historial, de la mas nueva a la mas vieja. `correlativo` desempata.
create or replace function public.listar_ventas(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(v) order by v.fecha desc,
                              v.correlativo desc), '[]'::jsonb)
      from (select * from public.ventas
             where (p ->> 'desde' is null or fecha >= (p ->> 'desde')::timestamptz)
               and (p ->> 'hasta' is null or fecha < (p ->> 'hasta')::timestamptz)
             order by fecha desc, correlativo desc
             limit coalesce((p ->> 'limite')::integer, 40)) v
$$;

create or replace function public.contar_ventas(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select to_jsonb(count(*)) from public.ventas
     where (p ->> 'desde' is null or fecha >= (p ->> 'desde')::timestamptz)
       and (p ->> 'hasta' is null or fecha < (p ->> 'hasta')::timestamptz)
$$;

-- Cuantas y cuanto, solo las activas: una venta anulada no ingreso.
create or replace function public.resumen_ventas(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select jsonb_build_object('ventas', count(*),
                              'ingreso', coalesce(sum(total_usd), 0))
      from public.ventas
     where estado = 'activa'
       and (p ->> 'desde' is null or fecha >= (p ->> 'desde')::timestamptz)
       and (p ->> 'hasta' is null or fecha < (p ->> 'hasta')::timestamptz)
$$;

-- ---------------------------------------------------------------------------
-- Cuentas por cobrar
-- ---------------------------------------------------------------------------

create or replace function public.facturas_pendientes(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(x) order by x.fecha, x.correlativo),
                    '[]'::jsonb)
      from privado.pendientes(privado.id(p ->> 'cliente_id')) x
$$;

-- Quien debe, cuanto y su vencimiento mas proximo: primero lo vencido, despues lo
-- que vence pronto, y al final lo que no tiene fecha.
create or replace function public.clientes_con_saldo(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(x) order by x.vence nulls last,
                              lower(x.nombre)), '[]'::jsonb)
      from (select c.id, c.nombre, c.telefono,
                   round(sum(pe.restante), 2) as saldo,
                   min(pe.fecha_pago_prevista) as vence,
                   count(*) as facturas
              from public.clientes c
              join privado.pendientes() pe on pe.cliente_id = c.id
             where c.activo
             group by c.id) x
$$;

-- El credito en la calle. **No depende del periodo**: es una foto de hoy. `hoy`
-- lo manda la app, porque es la fecha del telefono la que la persona tiene en la
-- cabeza, no la del servidor.
create or replace function public.total_por_cobrar(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select jsonb_build_object(
        'total', coalesce(round(sum(restante), 2), 0),
        'vencido', coalesce(round(sum(case when fecha_pago_prevista
                                                < (p ->> 'hoy')::date
                                           then restante else 0 end), 2), 0),
        'clientes', count(distinct cliente_id),
        'facturas', count(*))
      from privado.pendientes()
$$;

-- Abona al **saldo del cliente**, saldando la factura mas vieja primero, y deja
-- escrito a que factura fue cada pedazo. El monto en dolares ya viene calculado y
-- validado por la app; aca se reparte.
create or replace function public.registrar_abono(p jsonb) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
    cliente uuid := privado.id(p ->> 'cliente_id');
    monto_usd numeric := (p ->> 'monto_usd')::numeric;
    saldo numeric;
    metodo_elegido uuid;
    metodo_nombre text := '';
    abono uuid;
    por_repartir numeric;
    trozo numeric;
    factura record;
    aplicadas jsonb := '[]'::jsonb;
begin
    -- Bloquea al cliente: dos abonos a la vez se repartirian sobre el mismo saldo.
    perform 1 from public.clientes where id = cliente for update;

    if not exists (select 1 from privado.pendientes(cliente)) then
        perform privado.fallar('Ese cliente no tiene nada pendiente.');
    end if;
    select round(sum(restante), 2) into saldo from privado.pendientes(cliente);
    if monto_usd - saldo > 0.01 then
        perform privado.fallar(format(
            'El abono se pasa: debe $ %s y se están recibiendo $ %s.',
            privado.dinero(saldo), privado.dinero(monto_usd)));
    end if;
    -- Diferencia de centavos: se ajusta al restante exacto.
    monto_usd := least(monto_usd, saldo);

    if nullif(p ->> 'metodo_id', '') is not null then
        select id, nombre into metodo_elegido, metodo_nombre
          from public.metodos_pago where id = privado.id(p ->> 'metodo_id');
    end if;

    insert into public.abonos (cliente_id, monto_usd, moneda_recibida,
                               monto_recibido, tasa_usada, metodo_id,
                               metodo_nombre, nota)
    values (cliente, round(monto_usd, 2), p ->> 'moneda',
            (p ->> 'monto_recibido')::numeric,
            coalesce((p ->> 'tasa')::numeric, 0),
            metodo_elegido, coalesce(metodo_nombre, ''),
            trim(coalesce(p ->> 'nota', '')))
    returning id into abono;

    por_repartir := round(monto_usd, 2);
    for factura in select * from privado.pendientes(cliente) loop
        exit when por_repartir <= 0.005;
        trozo := round(least(por_repartir, factura.restante), 2);
        insert into public.abono_aplicaciones (abono_id, venta_id, monto_usd)
        values (abono, factura.id, trozo);
        por_repartir := round(por_repartir - trozo, 2);
        aplicadas := aplicadas || jsonb_build_array(jsonb_build_object(
            'correlativo', factura.correlativo, 'monto', trozo,
            'saldada', trozo >= factura.restante - 0.005));
    end loop;

    return jsonb_build_object('id', abono, 'monto_usd', round(monto_usd, 2),
                              'aplicadas', aplicadas,
                              'saldo_restante', round(saldo - monto_usd, 2));
end
$$;

create or replace function public.abonos_de_cliente(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(a) order by a.fecha desc), '[]'::jsonb)
      from (select * from public.abonos
             where cliente_id = privado.id(p ->> 'cliente_id')
             order by fecha desc
             limit coalesce((p ->> 'limite')::integer, 30)) a
$$;

-- ---------------------------------------------------------------------------
-- Gastos
-- ---------------------------------------------------------------------------

-- Un gasto **operativo**. La compra de mercancia no va aca: ver `reabastecer`.
create or replace function public.crear_gasto(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    insert into public.gastos (categoria, descripcion, monto_usd, moneda_pagada,
                               monto_pagado, tasa_usada)
    values (p ->> 'categoria', coalesce(p ->> 'descripcion', ''),
            (p ->> 'monto_usd')::numeric, p ->> 'moneda',
            (p ->> 'monto_pagado')::numeric, coalesce((p ->> 'tasa')::numeric, 0))
    returning to_jsonb(id)
$$;

create or replace function public.eliminar_gasto(p jsonb) returns jsonb
language sql security invoker set search_path = '' as $$
    update public.gastos set activo = false where id = privado.id(p ->> 'id')
    returning to_jsonb(true)
$$;

create or replace function public.listar_gastos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(g) order by g.fecha desc), '[]'::jsonb)
      from (select * from public.gastos
             where activo
               and (p ->> 'desde' is null or fecha >= (p ->> 'desde')::timestamptz)
               and (p ->> 'hasta' is null or fecha < (p ->> 'hasta')::timestamptz)
             order by fecha desc
             limit coalesce((p ->> 'limite')::integer, 100)) g
$$;

-- Las ya usadas, de la mas usada a la menos, sin distinguir mayusculas: sin eso
-- las metricas cuentan "Delivery" y "delivery" como dos cosas.
create or replace function public.categorias_de_gasto(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(x.categoria order by x.veces desc, x.categoria),
                    '[]'::jsonb)
      from (select min(categoria) as categoria, count(*) as veces
              from public.gastos where activo
             group by lower(categoria)) x
$$;

-- ---------------------------------------------------------------------------
-- Metricas (los rangos de fecha los arma la app con la hora del telefono)
-- ---------------------------------------------------------------------------

-- Las sumas de la cascada. Las cuentas derivadas (ganancia, margen) las hace la
-- app, igual que antes. **Se cuenta por venta, no por cobro**; lo cobrado va
-- aparte para ver cuanto entro de verdad en la caja.
create or replace function public.metricas(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    with v as (
        select * from public.ventas
         where fecha >= (p ->> 'desde')::timestamptz
           and fecha < (p ->> 'hasta')::timestamptz and estado = 'activa')
    select jsonb_build_object(
        'ventas', (select count(*) from v),
        'vendido', (select coalesce(sum(total_usd), 0) from v),
        'costo', (select coalesce(sum(l.cantidad * l.costo_unit_usd), 0)
                    from public.venta_lineas l join v on v.id = l.venta_id),
        'gastos', (select coalesce(sum(monto_usd), 0) from public.gastos
                    where activo and fecha >= (p ->> 'desde')::timestamptz
                      and fecha < (p ->> 'hasta')::timestamptz),
        'cobrado_ventas', (select coalesce(sum(pg.monto_usd), 0)
                             from public.venta_pagos pg
                             join v on v.id = pg.venta_id),
        'cobrado_abonos', (select coalesce(sum(monto_usd), 0) from public.abonos
                            where fecha >= (p ->> 'desde')::timestamptz
                              and fecha < (p ->> 'hasta')::timestamptz),
        'sin_costo', (select count(*) from public.productos
                       where activo and costo_usd <= 0))
$$;

create or replace function public.top_productos(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(x) order by x.vendido desc), '[]'::jsonb)
      from (select l.nombre_congelado as nombre, sum(l.cantidad) as unidades,
                   round(sum(l.cantidad * l.precio_unit_usd), 2) as vendido,
                   round(sum(l.cantidad * (l.precio_unit_usd - l.costo_unit_usd)), 2)
                       as ganancia
              from public.venta_lineas l
              join public.ventas v on v.id = l.venta_id
             where v.fecha >= (p ->> 'desde')::timestamptz
               and v.fecha < (p ->> 'hasta')::timestamptz and v.estado = 'activa'
             group by l.nombre_congelado
             order by vendido desc
             limit coalesce((p ->> 'limite')::integer, 5)) x
$$;

create or replace function public.gastos_por_categoria(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(to_jsonb(x) order by x.total desc), '[]'::jsonb)
      from (select min(categoria) as categoria, count(*) as veces,
                   round(sum(monto_usd), 2) as total
              from public.gastos
             where fecha >= (p ->> 'desde')::timestamptz
               and fecha < (p ->> 'hasta')::timestamptz and activo
             group by lower(categoria)) x
$$;

-- Cada venta del rango con su costo. **El agrupado por dia lo hace la app**, con
-- la zona del telefono: agrupar aca daria el dia UTC, y en Venezuela (UTC-4) las
-- ventas despues de las 20:00 caerian en el dia siguiente.
create or replace function public.ventas_para_serie(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(jsonb_build_object(
               'fecha', v.fecha, 'total_usd', v.total_usd,
               'costo', (select coalesce(sum(l.cantidad * l.costo_unit_usd), 0)
                           from public.venta_lineas l where l.venta_id = v.id))),
           '[]'::jsonb)
      from public.ventas v
     where v.fecha >= (p ->> 'desde')::timestamptz
       and v.fecha < (p ->> 'hasta')::timestamptz and v.estado = 'activa'
$$;

-- ---------------------------------------------------------------------------
-- Resumen y catalogo
-- ---------------------------------------------------------------------------

create or replace function public.resumen_inventario(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select jsonb_build_object(
        'productos', count(*),
        'unidades', coalesce(sum(stock), 0),
        'valor_costo', coalesce(sum(stock * costo_usd), 0),
        'sin_costo', count(*) filter (where costo_usd <= 0),
        'sin_stock', count(*) filter (where stock <= 0),
        'bajo_costo', count(*) filter (where precio_usd < costo_usd))
      from public.productos where activo
$$;

-- Los marcados para el catalogo, con la foto de catalogo de su foto principal.
create or replace function public.productos_del_catalogo(p jsonb) returns jsonb
language sql stable security invoker set search_path = '' as $$
    select coalesce(jsonb_agg(jsonb_build_object(
               'id', pr.id, 'nombre', pr.nombre, 'descripcion', pr.descripcion,
               'precio_usd', pr.precio_usd, 'stock', pr.stock,
               'foto', encode(f.catalogo, 'base64'))
               order by lower(pr.nombre)), '[]'::jsonb)
      from public.productos pr
      left join public.producto_fotos f on f.producto_id = pr.id and f.orden = 1
     where pr.activo and pr.en_catalogo
       and (coalesce((p ->> 'incluir_sin_stock')::boolean, true) or pr.stock > 0)
$$;

-- ---------------------------------------------------------------------------
-- Quien puede llamarlas
-- ---------------------------------------------------------------------------
--
-- Postgres le da permiso a todo el mundo (`public`) sobre cada funcion nueva, y
-- Supabase ademas a `anon`. Se les quita a los dos y se le da solo a quien tiene
-- sesion. Aunque `anon` pudiera llamarlas no veria nada —el RLS lo impide—, pero
-- la puerta cerrada es mejor que la puerta abierta a un cuarto vacio.

do $$
declare
    f regprocedure;
begin
    for f in select pr.oid::regprocedure
               from pg_proc pr join pg_namespace n on n.oid = pr.pronamespace
              where n.nspname in ('public', 'privado') loop
        execute format('revoke all on function %s from public', f);
        execute format('revoke all on function %s from anon', f);
        execute format('grant execute on function %s to authenticated', f);
    end loop;
end
$$;
