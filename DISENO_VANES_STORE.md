# Vane's Store — Documento de diseño

> App móvil de gestión de ventas para **una persona** que vende pocos productos, en línea.
> Nombre visible: **Vane's Store**. Identificador Android: `com.bolivarsoftware.vanesstore`
> (el apóstrofo y el espacio no son válidos en el identificador; el nombre en pantalla sí
> los lleva).
> Escrito el 4 de septiembre de 2026. **Las seis fases están hechas y probadas en
> la computadora** al 6 de septiembre; falta compilar el APK. La aplicación vive en
> `app/` y las pruebas técnicas de la Fase 0 en `pruebas_fase0/`.

## Dónde va cada cosa

El código está partido en dos, con el mismo criterio que SELL-B (`backend/` y
`frontend_desktop/` allá):

```
app/
  main.py            el arranque: arma la navegación y elige la pantalla.
                     Único archivo en la raíz, porque es el que abre `flet`.
  backend/           lo que la aplicación sabe hacer sin pantalla
    basedatos.py       la base SQLite entera: esquema, migraciones y consultas
    almacenamiento.py  dónde se escribe en el disco y la configuración suelta
    seguridad.py       el PIN y el cifrado de los secretos
    catalogo.py        genera el PDF del catálogo y el correo con el que sale
    resumen_semanal.py genera el PDF del resumen y su correo
    correo.py          el envío por Gmail
    nube.py            el respaldo en Neon
    fotos.py           redimensionado de las fotos de producto
    formato.py         cómo se escriben montos, cantidades y fechas
  frontend/          lo que se ve
    vistas/            una pantalla por archivo
    estilo.py          tipografía, tarjetas, botones
    paleta.py          los colores
    marca.py           el logo
    dialogos.py        las ventanas que se abren encima
  assets/            el icono, que es también el de Android
  datos/             la base con la que se prueba en la computadora (no se sube)
  pruebas/           las suites
```

**La regla es de una sola dirección**: el frontend llama al backend, nunca al revés.
Una pantalla le pide datos a `backend.basedatos`; la base de datos no sabe que hay
pantallas. La prueba de que la línea está bien trazada es que **ningún archivo de
`backend/` importa `flet`** — si alguno lo necesitara, es que está en la carpeta
equivocada.

---

## 1. Qué es y qué no es

Es **solo móvil**. No hay computadora en el local, no hay empleados, no hay roles. El
teléfono es el negocio entero.

Se parece a SELL-B en las funciones, pero **no en la arquitectura**: SELL-B Móvil es un
control remoto de una PC que tiene la base de datos. Aquí no hay PC. De SELL-B se reutiliza
el esqueleto de la interfaz y las lecciones, no el modelo cliente-servidor.

Lo que hace:

| Módulo | Para qué |
|---|---|
| Inventario | Productos con hasta 3 fotos, costo, precio, stock |
| Venta | Carrito, cliente opcional, contado o crédito |
| Cobros | Cuentas por cobrar agrupadas por cliente, con abonos |
| Catálogo | PDF con los productos, para mandar |
| Métricas | Ingresos, costos, gastos, ganancia neta |
| Gastos | Gastos operativos, aparte de la mercancía |

---

## 2. Arquitectura

**SQLite en el teléfono es la verdad. Neon es la copia que sobrevive al teléfono.**

```
  Vende y consulta               Cuando hay señal
  ┌──────────────┐              ┌──────────────┐
  │   SQLite     │ ───push───▶  │     Neon     │
  │ (el teléfono)│              │  (respaldo)  │
  └──────────────┘              └──────────────┘
       la verdad                   la copia
```

- La venta se escribe local y responde al instante. **Nunca se bloquea una venta esperando
  la red.**
- Cuando hay señal, se empuja lo que falta. Es un empujón **en una sola dirección**; la
  bajada existe solo para restaurar en un teléfono nuevo.
- **No hay API en el medio.** Neon es Postgres y habla su protocolo directo. Lo que en
  SELL-B obligaba a montar un FastAPI era que había dos cerebros (la PC y el teléfono) y
  empleados a quienes ocultarles la credencial. Aquí no hay ni una cosa ni la otra, y sacar
  el FastAPI del medio elimina el costo de hospedaje — que fue lo que dejó parada la Fase 4
  de SELL-B.

### Por qué no hay sincronización bidireccional

Escribe **un solo dispositivo**. No hay nada que reconciliar, nadie que gane un empate,
ningún stock que recalcular desde dos lados. Toda la complejidad de la Fase 4 de SELL-B
nace de que las dos copias escribían; aquí no.

Aun así, las escrituras nacen **con UUID y append-only** desde el día uno. No se usa hoy,
pero es lo que permite que un segundo teléfono más adelante sea una capa nueva y no una
reescritura.

### Driver

**`pg8000`** — Python puro. `psycopg2` trae extensiones en C y no sobrevive al empaquetado
del APK. Si el socket TLS fallara dentro del APK, la red de seguridad es el **modo HTTP de
Neon**, que sería `requests` pelado.

Como la base local es la verdad, **la app funciona completa aunque la conexión a Neon nunca
abra**. El respaldo puede esperar; la venta no.

---

## 3. Acceso y seguridad

Amenazas distintas, defensas distintas. Una sola pantalla de login no cubre las tres:

| Amenaza | Qué la frena |
|---|---|
| Alguien consigue el **APK** | Que la credencial **no esté compilada adentro** |
| Alguien agarra el **teléfono desbloqueado** | El PIN de la app |
| Le **roban el teléfono** y sacan los archivos | El bloqueo de pantalla de Android |

**La autenticación es la de Postgres, no una inventada.** Neon ya trae usuarios; no hace
falta una tabla de usuarios propia. Dentro del APK queda solo la dirección del servidor y
el nombre de la base — sin contraseña, eso no sirve de nada.

- La credencial se guarda **cifrada**, con la llave derivada del PIN (PBKDF2). Entra con el
  PIN, la app descifra y conecta. **La clave de aplicación de Gmail** (ver §8) se guarda
  igual: da permiso para mandar correo en su nombre, así que no puede quedar en claro.
- **PIN de 6 dígitos como mínimo.** Cuatro dígitos son diez mil combinaciones: nada para
  alguien que ya tiene los archivos del teléfono.
- En Neon, un **rol con permisos recortados**: leer e insertar en las tablas de la app y
  nada más. Sin `DROP`, sin tocar otras bases. Aun en el peor caso, el daño tiene techo.

**Asumido a conciencia:** la copia local de SQLite tiene los mismos datos y **no está
cifrada**. Android impide que otras apps la lean, y para el caso de una persona en su
propio teléfono se considera aceptable. Queda escrito para que sea una decisión y no un
olvido.

---

## 4. Moneda

**El dólar es la moneda constante.** Todo lo que se analiza está en dólares.

- Precios de venta y costos: en dólares.
- La deuda de un cliente: en dólares.
- Cada venta **congela su tasa**, así el total en bolívares de esa venta no se mueve nunca
  más aunque la tasa cambie mañana.
- Los abonos y los gastos guardan **lo que efectivamente se pagó** (monto y moneda) más la
  tasa de ese día, y además el equivalente en dólares ya calculado. Las métricas leen
  siempre la columna en dólares.

Es la lección del arqueo de SELL-B: cada moneda se compara contra la suya, sin convertir
para atrás con la tasa de hoy. Convertir hacia atrás inventaba descuadres.

---

## 5. Modelo de datos

Todas las tablas llevan `creado_en`, `actualizado_en` (ISO UTC) y `sincronizado_en`
(`NULL` = pendiente de empujar a Neon). No hace falta una tabla de cola: lo pendiente es
lo que tiene `sincronizado_en IS NULL`.

```
productos
  id                TEXT PK (uuid)
  nombre            TEXT NOT NULL
  descripcion       TEXT
  costo_usd         REAL NOT NULL     -- costo actual de reposición
  precio_usd        REAL NOT NULL
  stock             REAL NOT NULL     -- resumen calculado de movimientos_inventario
  en_catalogo       INTEGER DEFAULT 1
  activo            INTEGER DEFAULT 1 -- borrado lógico, nunca DELETE

producto_fotos
  id                TEXT PK
  producto_id       TEXT FK
  orden             INTEGER           -- 1..3; la 1 es la principal
  miniatura         BLOB              -- ~15 KB, la que va en las listas
  completa          BLOB              -- ~150 KB, al abrir el producto y en el catálogo
  UNIQUE (producto_id, orden)

movimientos_inventario                -- APPEND-ONLY: nunca se edita ni se borra
  id                TEXT PK
  producto_id       TEXT FK
  delta             REAL              -- +7 al comprar, -3 al vender
  motivo            TEXT              -- alta | compra | venta | ajuste
  referencia_id     TEXT              -- la venta o la compra que lo originó
  nota              TEXT
  fecha             TEXT

clientes
  id                TEXT PK (uuid)
  nombre            TEXT NOT NULL
  telefono          TEXT
  notas             TEXT
  activo            INTEGER DEFAULT 1

ventas                                -- APPEND-ONLY: nunca se editan
  id                TEXT PK (uuid)
  correlativo       INTEGER           -- el número legible que ve el cliente
  cliente_id        TEXT NULL         -- NULL = venta suelta, sin cliente
  fecha             TEXT
  tipo              TEXT              -- contado | credito
  total_usd         REAL
  tasa_usada        REAL              -- congelada
  fecha_pago_prevista TEXT NULL
  estado            TEXT              -- activa | anulada

venta_lineas
  id                TEXT PK
  venta_id          TEXT FK
  producto_id       TEXT FK
  nombre_congelado  TEXT              -- congelado
  cantidad          REAL
  precio_unit_usd   REAL              -- congelado
  costo_unit_usd    REAL              -- congelado

abonos
  id                TEXT PK (uuid)
  cliente_id        TEXT FK
  fecha             TEXT
  monto_usd         REAL              -- equivalente en la moneda constante
  moneda_recibida   TEXT              -- USD | Bs
  monto_recibido    REAL              -- lo que efectivamente entregó
  tasa_usada        REAL
  nota              TEXT

abono_aplicaciones                    -- a qué factura fue cada pedazo del abono
  id                TEXT PK
  abono_id          TEXT FK
  venta_id          TEXT FK
  monto_usd         REAL

gastos
  id                TEXT PK (uuid)
  fecha             TEXT
  categoria         TEXT              -- libre, con sugerencia de lo ya escrito
  descripcion       TEXT
  monto_usd         REAL
  moneda_pagada     TEXT              -- USD | Bs
  monto_pagado      REAL
  tasa_usada        REAL

configuracion
  clave             TEXT PK
  valor             TEXT
  -- tasa_bcv, tasa_actualizada_en, correlativo_actual,
  -- catalogo_incluye_sin_stock, correo_remitente,
  -- correo_clave_app (cifrada con el PIN), neon_credencial (cifrada con el PIN)
```

### Las tres decisiones del modelo que no son obvias

**1. El costo y el precio se congelan en la línea de venta.** Si el margen histórico se
calculara con el costo *actual* del producto, el día que recompre más caro se le reescribe
la ganancia de meses pasados. La línea guarda su propio `costo_unit_usd` y
`precio_unit_usd`, copiados al momento de vender.

**2. El stock es la suma de `movimientos_inventario`, no un número que se pisa.** Se guarda
"menos 3", nunca "ponelo en 100". Lo relativo se puede aplicar en cualquier orden y da el
mismo resultado. En SELL-B, una sola columna escrita en absoluto
(`actualizar_producto_maestro`) era **el único punto que rompía todo el diseño de
dualidad**. Acá nace bien. `productos.stock` queda como resumen calculado, para que las
consultas de lista no tengan que sumar movimientos cada vez.

**3. `abono_aplicaciones` existe para poder responder "¿qué factura me quedó saldada?".**
El cliente paga $50 al bulto y el sistema los reparte sobre sus facturas viejas. Sin esa
tabla habría un saldo que baja, pero nadie podría decir a cuál factura fue cada pedazo.

---

## 6. Reglas de negocio

### Abonos: al saldo, la más vieja primero

El abono se registra contra el **cliente**, no contra una factura. El sistema lo reparte
solo: cancela la factura más antigua y lo que sobra pasa a la siguiente, dejando escrita
cada aplicación. Es como funciona una cuenta corriente, y es lo natural cuando alguien debe
varias facturas.

**La ficha del cliente es el grupo.** No hace falta una entidad "factura agrupada": la
cuenta del cliente suma sus facturas abiertas y muestra un saldo, con el detalle debajo.

Protecciones (las mismas que se blindaron en SELL-B al exponer los abonos a la red):
rechazar montos `<= 0`, rechazar abonos sobre cuentas ya saldadas, y si el monto excede lo
pendiente por centavos, ajustarlo al restante exacto en vez de dejar saldo negativo.

### Stock: no se vende sin existencia

Si marca 3, no deja vender 5. **Bloquea.**

Eso vuelve al stock un dato crítico: el día que el número real no coincida con el del
sistema, la app le bloquea una venta que sí puede hacer. Por eso viene obligatorio de la
mano el **ajuste de stock** ("conté y hay 7, no 5"), que escribe su movimiento con motivo
`ajuste` y queda registrado. Bloquear sin dar una salida rápida es lo que hace que la gente
termine vendiendo por fuera del sistema.

### Gastos: la mercancía no es un gasto

Es el error clásico y arruina las métricas. Si una compra de mercancía se registra como
gasto, el costo se cuenta **dos veces**: una al comprar y otra cuando la venta descuenta el
`costo_unit_usd` congelado.

| | Toca inventario | Cómo pega en la ganancia |
|---|---|---|
| **Compra de mercancía** | Sí, suma stock y fija el costo | Ya está contada al vender |
| **Gasto operativo** | No | Se resta aparte |

Gastos son delivery, empaques, publicidad, internet, comisiones de pago móvil.

```
Ingresos                $ 1.200
− Costo de lo vendido   $   700
────────────────────────────────
= Ganancia bruta        $   500
− Gastos                $   120
────────────────────────────────
= Ganancia neta         $   380     ← el número que importa
```

### Categorías de gasto

Texto libre, **con sugerencia de lo ya escrito**. Sigue siendo manual, pero la segunda vez
que escriba "del…" le ofrece "Delivery". Sin eso, las métricas terminan contando
*Delivery*, *delivery* y *deliveri* como tres categorías distintas.

### Recordatorios de cobro

Pantalla de avisos al abrir la app: vencidos arriba, después lo que vence esta semana.
**Sin notificación de Android** — decidido así; una notificación con la app cerrada necesita
un plugin y trabajo de Android que hoy no se justifica. La lógica de vencimientos se
escribe una sola vez, así que si más adelante se quiere la notificación, se enchufa encima
sin rehacer nada.

El teléfono del cliente se guarda para poder llamarlo o copiarlo. **No** se genera mensaje
de WhatsApp automático.

---

## 7. Fotos

Hasta **3 por producto**. La primera es la **principal**: va en la lista, en el carrito y en
el catálogo. Las otras dos se ven al abrir el producto.

**Se eligen de la galería del teléfono, no se toman con una cámara dentro de la app.**
Quien vende en línea ya tiene las fotos tomadas, y el teléfono trae una app de cámara mucho
mejor que la que podríamos hacer nosotros. Se resuelve con `FilePicker`, que viene en Flet:
ahorra el paquete `flet-camera`, el permiso de cámara y una pantalla de captura entera.

- **Se redimensionan al capturar, no al mostrar.** Una foto de cámara son 4–6 MB; veinte
  productos sin tocar serían 100 MB adentro del teléfono, listas que se arrastran y un
  catálogo imposible de mandar por WhatsApp.
- Van en **tabla aparte**. Si la foto fuera una columna de `productos`, cada consulta de
  lista arrastraría megabytes que nadie pidió.
- **Hay que rotar por EXIF al guardar.** El teléfono no rota el píxel: escribe la
  orientación en el EXIF. Sin `ImageOps.exif_transpose`, la mitad de los productos saldría
  acostada en el catálogo.

### Tres tamaños, no dos

Medido en la Fase 0 (§11): con **un solo** tamaño grande, un catálogo de 50 productos pesa
**1,9 MB**; con una imagen de catálogo aparte baja a **0,5 MB**.

| | Lado | Calidad | Presupuesto | Para qué |
|---|---|---|---|---|
| Miniatura | 200 px | 70 | 25 KB | Listas y carrito |
| Catálogo | 400 px | 70 | 60 KB | El PDF |
| Completa | 1000 px | 80 | 250 KB | Al abrir el producto |

**Si la foto que entra ya es un JPEG derecho, ya cabe en el lado máximo y ya pesa menos que
su presupuesto, se guarda tal cual sin tocarla.** Volver a codificar un JPEG le quita
calidad aunque no cambie de tamaño —pérdida generacional, cada pasada degrada un poco más—
y en ese caso no habría nada que ganar.

El criterio es el presupuesto y **no** "cuál de los dos pesa menos": elegir siempre el más
chico sería cambiar calidad por bytes a espaldas del usuario, en fotos que ya estaban bien.

El argumento no es de peso sino de resolución: en el PDF la foto se imprime a 32 mm de
ancho, así que **400 px ya son más de 300 puntos por pulgada**. Todo lo que sobre de ahí es
detalle que nadie puede ver y que solo engorda el archivo que hay que mandar por correo.

**Aviso de peso:** tres fotos multiplican por tres el respaldo en Neon. Con 200 productos y
3 fotos de ~150 KB son ~90 MB, y el plan gratuito de Neon anda por el medio giga. Entra,
pero hay que vigilarlo. Se suben **las tres**: un respaldo que restaura un tercio de las
fotos no es un respaldo.

---

## 8. Catálogo

**Uno solo.** Se arma con los productos que tengan `en_catalogo = 1`.

PDF con foto principal, nombre, descripción y precio.

**Va sin el nombre del negocio**, ni en el encabezado ni en los datos internos del archivo:
el catálogo se manda por mensaje a alguien que ya sabe a quién le está comprando. El
encabezado dice solo "Catálogo".

### Productos sin stock: un interruptor

Como se toman encargos, lo que está en cero **puede entrar al catálogo**. El interruptor
`catalogo_incluye_sin_stock` vive en la pantalla del Catálogo y no en Configuración: es una
propiedad del catálogo y se cambia según lo que se esté mandando.

Cuando entran, salen **marcados "A pedido"** con su precio. Si aparecieran iguales que el
resto, alguien pide algo esperando recibirlo mañana.

**Choca con "no se vende sin stock", y se decidió no resolverlo por ahora.** Si alguien
encarga algo que está en cero, la venta no se puede registrar hasta que llegue la
mercancía: se toma el encargo por WhatsApp, se compra, se ingresa al inventario y ahí se
registra. El encargo vive fuera de la app. Un módulo de encargos —pedidos pendientes que se
convierten en venta al llegar la mercancía— queda anotado como posible, **no en el plan**,
hasta ver si de verdad hace falta.

### Cómo sale el PDF del teléfono

Se genera con **`fpdf2`** (Python puro; las librerías con extensiones en C no sobreviven al
APK).

Mandarlo es la parte difícil, y por eso la vía principal es **el correo, con `smtplib`**:
está en la biblioteca estándar y **no le pide nada a Android** — ni permisos, ni plugin, ni
acceso a carpetas compartidas.

| Camino | Qué necesita de Android |
|---|---|
| **Correo (`smtplib`)** — el elegido | **Nada** |
| Guardar en Descargas | Permiso y escritura por MediaStore; la carpeta privada de la app **no la ve WhatsApp** |
| Menú de compartir | Plugin, sin verificar |

El correo cumple dos funciones: mandárselo al cliente que use correo, y —más importante—
**mandárselo a sí misma**. Abre el correo en el teléfono, descarga el adjunto, y ahí sí
WhatsApp lo ve y lo puede reenviar. Aunque el menú de compartir de Android nunca funcione,
el PDF siempre tiene por dónde salir.

Dos cosas asumidas:

- Gmail no acepta la contraseña normal para `smtplib`: hace falta una **clave de
  aplicación**, que se genera con la verificación en dos pasos activada. Se guarda
  **cifrada con el PIN**, igual que la credencial de Neon.
- **Los clientes probablemente usan WhatsApp y no correo.** El correo es el piso
  garantizado, no el reemplazo del menú de compartir — que sigue en las pruebas de la
  Fase 0 y, si sale, se agrega como atajo.

---

## 9. Pantallas

Son seis módulos y en una barra inferior entran cinco cómodos. Se usa el mismo criterio de
SELL-B, donde Configuración vive detrás del engranaje de Inicio y no gasta pestaña:

```
Barra:    Inicio · Venta · Inventario · Cobros · Métricas
            │                  │                    │
            │                  └─ Catálogo          └─ Gastos
            └─ avisos de cobro + engranaje
```

**Catálogo** cuelga de Inventario porque es una vista de los mismos productos. **Gastos**
cuelga de Métricas porque es donde se mira el dinero. Ninguno se usa a diario.

| Pantalla | Contenido |
|---|---|
| **PIN** | Entrada con el PIN; descifra la credencial de Neon y lanza una consulta de despertar |
| **Inicio** | Avisos de cobro (vencidos / vence esta semana), resumen del día, engranaje |
| **Venta** | Buscador de productos, carrito, cliente opcional, contado o crédito con fecha prevista |
| **Inventario** | Lista con miniatura y buscador, alta, edición, ajuste de stock, compra |
| **Catálogo** | Marcar qué entra, interruptor de "incluir sin stock", previsualizar, generar y mandar por correo |
| **Cobros** | Clientes con saldo ordenados por vencimiento; ficha con sus facturas; abonar |
| **Métricas** | Período, ingresos, costo, bruta, gastos, neta, top de productos |
| **Gastos** | Alta de gasto y lista por período, agrupada por categoría |
| **Configuración** | Tasa del día, respaldo y sincronización, cambio de PIN, credencial de Neon |

---

## 10. Lo que se reutiliza de SELL-B Móvil

De `APPMOVIL_SELL-B`, el esqueleto que no depende del negocio:

- **`main.py`** — sesión en un dict, navegación **por nombre y no por índice**, y el
  `try/except` que pinta el traceback en pantalla en vez de morir en silencio. (La barra
  armada por rol no hace falta: aquí hay un solo usuario.)
- **`storage.py`** — config persistente con `FLET_APP_STORAGE_DATA`, la única ruta
  escribible en Android.
- **El workflow de GitHub Actions** — compilación del APK en la nube, ya con el borrado de
  `.git`, `.github` y `__pycache__` resuelto.
- **El patrón de listas rápidas** — tope de tarjetas por lote con "Ver más", reciclado de
  filas y carga diferida por pestaña. Es lo que bajó Inventario de 1.205 ms a 57 ms con
  1.000 productos.

### Trampas de Flet 0.85.3 ya pagadas — no volver a descubrirlas

- `ft.padding.symmetric/only` y `ft.border.all` **no existen**: van `ft.Padding(l,t,r,b)` y
  `ft.Border(BorderSide × 4)`.
- La etiqueta de `ElevatedButton` y `TextButton` es **`.content`, no `.text`**. Asignar
  `.text` no da error y deja el botón en blanco.
- Los diálogos hay que **limpiarlos del `overlay` al abrir, no al cerrar**: si se quitan en
  el mismo update en que se cierran, la ventana queda colgada.
- Reasignar el `.value` de un `Switch` **dispara su `on_change`**. Hay que silenciarlo al
  repintar listas, o se llama al servidor en bucle.

Lo que **no** se reutiliza: `api_client.py` (no hay API), roles y permisos, la tasa como
concepto remoto, y todo el modelo maestro/presentaciones con factor de reducción.

---

## 11. Fase 0 — COMPLETADA en la computadora

**Una sola app con las tres pruebas**, no tres. Código en `pruebas_fase0/`. Corrida el
5 de septiembre de 2026 en Windows; **las tres pasaron**. Falta repetirlas dentro del APK.

| | Prueba | Resultado |
|---|---|---|
| 1 | Foto y redimensionado (Pillow) | **Pasa.** 5 imágenes distintas, 15–114 ms |
| 2a | Catálogo en PDF (`fpdf2`) | **Pasa.** 6 productos, 1 página, 8 KB, 7 ms |
| 2b | Envío por correo (`smtplib`) | **Pasa.** Entregado en 3,1 s y **abrible en el visor de Gmail sin descargarlo** |
| 3 | Conexión a Neon (`pg8000`) | **Pasa.** 2.165 ms de conexión (incluye despertar), 212 ms de consulta, escritura correcta |

La prueba 1 se ejerció con una cuadrada, una 9:16, una 1199×1466, un PNG con transparencia
y un JPEG apaisado con etiqueta EXIF de orientación fabricado a propósito. En todas la
proporción salió bien, y la apaisada **salió enderezada**: el EXIF se lee.

**El `endpoint=` de Neon no hace falta.** `pg8000` manda bien el SNI; la conexión entró por
el camino normal. El plan B queda en el código por si acaso, pero no se usa.

### Lo que ya quedó resuelto sin compilar

- **Pillow tiene rueda para Android**, y justo la 12.2.0. El redimensionado no era un
  riesgo después de todo.
- **`fpdf2` y `pg8000` son `py3-none-any`** (Python puro), igual que sus dependencias. Se
  empaquetan sin rueda especial.
- La lógica de redimensionado, del PDF y del parseo de la cadena de Neon **está corrida y
  verificada en la computadora**; lo que falta probar es solo lo que depende de Android.
- **No hace falta `flet-camera`.** Al elegir las fotos de la galería, `FilePicker` alcanza,
  y con eso la prueba 1 se corre entera en la computadora.

### El clavo que se descubrió y hay que respetar

**`pillow` va clavado en 12.2.0.** Flet publica ruedas para Android de unas pocas versiones
(12.2.0, 11.1.0, 10.4.0) y **la 12.3.0 no está**. Como `fpdf2` pide `Pillow>=8.3.2`, sin el
clavo pip resuelve a la más nueva y la compilación del APK falla al no encontrar la rueda.

### El puerto 5432 se bloquea con facilidad

La prueba 3 falló al principio con `ConnectionResetError`, y **no era el código**: el TCP
conectaba pero nadie contestaba al pedido de cifrado. La causa era **Proton VPN**, activo en
la máquina de desarrollo. Apagándolo, la conexión entró a la primera.

Es un patrón que va a repetirse, así que conviene reconocerlo: los VPN y muchos proveedores
de internet dejan pasar los puertos conocidos —443 de web, 465 de correo— y filtran el
5432, que es de base de datos. El síntoma es siempre el mismo: **el TCP conecta y después
no llega nada**.

Consecuencias para la app:

- **El mensaje de error tiene que decirlo.** "No se pudo conectar" no ayuda; hay que sugerir
  que puede ser un VPN o el proveedor bloqueando el puerto.
- **El plan B sigue siendo el modo HTTP de Neon**, sobre el 443. Se verificó que ese puerto
  sale sin problema desde esta máquina, incluso con el VPN encendido.
- Como el respaldo no es urgente, un bloqueo así **no rompe nada**: la app sigue vendiendo
  contra su SQLite y empuja cuando pueda.

### Lo que solo se puede saber en el teléfono

- Que el selector de archivos de Android devuelva los bytes de la foto.
- Que la foto salga derecha (que el EXIF se lea igual que en Windows).
- Que un socket TLS al 5432 salga de la red móvil.

Queda una cuarta prueba **opcional**: el menú de compartir de Android. Si sale, es un atajo
sobre el correo; si no sale, no bloquea nada.

---

## 12. Orden de construcción

| Fase | Qué | Estado |
|---|---|---|
| **0** | Las tres pruebas técnicas | **Hecha** · 5-sep · ver §11 |
| **1** | Base local, PIN, Inventario con fotos | **Hecha** · 5-sep |
| **2** | Venta, carrito, movimientos de stock | **Hecha** · 5-sep · con métodos de pago y pago mixto |
| **3** | Clientes, Cobros, abonos, avisos | **Hecha** · 5-sep |
| **4** | Gestión (métricas) y Gastos | **Hecha** · 5-sep · más el crédito pendiente |
| **5** | Catálogo en PDF y correo | **Hecha** · 6-sep · más el resumen semanal |
| **6** | Respaldo y restauración en Neon | **Hecha** · 6-sep · falta probar con credenciales reales |

Lo único que falta del plan es **compilar el APK**. El flujo de GitHub Actions ya
está escrito en `app/.github/workflows/`; hace falta subir la carpeta `app/` como
raíz de un repositorio y correrlo a mano.

---

## 13. Identidad visual

Blanco y beige. **Solo modo claro** — `ThemeMode.LIGHT` fijo, igual que SELL-B Móvil. Una
paleta beige es luminosa por definición; un modo oscuro obligaría a inventar una segunda
paleta entera que no se parecería a esta, y no se justifica.

### Paleta

**Superficies**

| Color | Uso |
|---|---|
| `#FBF9F5` | Fondo de la app (blanco cálido, no clínico) |
| `#FFFFFF` | Tarjetas |
| `#F2EADC` | Encabezados y secciones |
| `#E3D5BF` | Bordes, separadores, chips |

**Marca, acción y texto**

| Color | Uso | Contraste con blanco encima |
|---|---|---|
| `#8B6340` | Botón principal, marca | **5,3:1** — apto para texto normal |
| `#A67C52` | Íconos, bordes activos, texto grande | **3,7:1** — **no** apto para texto normal |
| `#2E2A26` | Texto principal | — |
| `#7A6E62` | Texto secundario | — |

**Semánticos**

| Color | Uso | Contraste con blanco encima |
|---|---|---|
| `#4A7C59` | Pagado, margen sano | **4,9:1** — apto |
| `#B4534B` | Vencido, margen negativo | **4,9:1** — apto |
| `#C9922E` | Vence pronto | **2,8:1** — **nunca texto blanco**; va con `#2E2A26` encima (5,1:1) o solo como punto y borde |

### Dos decisiones que no son de gusto

**El beige no puede ser un botón.** No tiene contraste contra el fondo, y un botón que no
se distingue no se toca. Por eso la paleta suma `#8B6340`, un caramelo profundo de la misma
familia que sí funciona como acción.

**Los semánticos van en versión terrosa a propósito.** SELL-B usa rojo `#EF4444` y verde
`#008000` puros. Sobre gris funcionan; sobre beige se ven chillones, como pegados de otra
app. El rojo ladrillo y el verde oliva dicen exactamente lo mismo sin romper la paleta.

Los contrastes de la tabla están **medidos, no elegidos a ojo**, y las dos excepciones
anotadas hay que respetarlas: `#A67C52` y `#C9922E` no llevan texto blanco normal encima.

### Logo

**Concepto A: monograma.** La letra V en blanco cálido (`#FBF9F5`) sobre un cuadrado
redondeado de `#8B6340`, trazo de extremos y vértice redondeados.

Se eligió por cómo se comporta **a 48 píxeles**, que es como se ve en la pantalla de inicio
del teléfono: es una sola forma y aguanta. Las alternativas descartadas eran una bolsa de
compras (a ese tamaño se le pierde el asa y queda una mancha) y un sello circular (el aro
fino desaparece).

Archivos en `assets/`:

- `logo.svg` — el original vectorial, para reescalar sin pérdida.
- `icon.png` — 1024 × 1024, el que toma `flet build` para el APK.

---

## 14. Lo que se agregó sobre el plan

Cosas que no estaban en el diseño original y salieron de usar la aplicación:

- **Métodos de pago editables y pago mixto.** El reparto se guarda **solo si cuadra**
  con el total; si no cuadra, no se cobra. Es la corrección del punto que más
  problemas dio en SELL-B, donde un reparto que no cerraba se guardaba igual.
- **Crédito pendiente** en Gestión: lo facturado y no cobrado, separando lo vencido.
  Es la única cifra de esa pantalla que **no depende del período** —es una foto del
  momento— y por eso lo dice.
- **«Entró en caja»**, aparte de los ingresos. Las métricas cuentan por venta, no por
  cobro; sin este número, un negocio con mucho crédito parece rentable y no tiene
  dinero en la mano.
- **Resumen semanal por correo**, conservado de SELL-B. Con su lección: el envío no
  depende de que sea lunes, porque el rango lo fija la consulta y no el día. La
  única guarda es no repetir la misma semana.
- **Historial de ventas completo**, agrupado por día, en vez de solo las de hoy.
- **`estilo.py`**: la tipografía y las piezas visuales en un solo lugar.

## 15. Los cuatro errores que costaron encontrar

Vale la pena que queden escritos: los tres eran invisibles para las pruebas de
entonces y ninguno daba un mensaje de error.

**El orden «la más vieja primero» estaba indeterminado.** Tres facturas creadas en
el mismo segundo empataban, y el motor las devolvía en cualquier orden: un abono
podía saldar la equivocada. Se arregló con el correlativo como desempate y subiendo
el reloj a milisegundos.

**El gráfico perdía las ventas de la tarde.** Agrupaba por día UTC y buscaba por día
local; en Venezuela (UTC−4) todo lo vendido después de las 20:00 desaparecía. El
comentario del código decía que reagrupaba por día local, pero el código no lo hacía.

**El correo se enviaba muchas veces.** El envío corría en el hilo de la interfaz, la
pantalla quedaba congelada varios segundos, y cada toque extra encolaba otro envío.
Se arregló con tres cosas: el diálogo confirma una sola vez, el trabajo lento va a
otro hilo, y el botón dice «Enviando…» mientras tanto.

**Un botón que dejaba de responder.** Al arreglar el punto anterior saqué el
diálogo del overlay al cerrarlo. Eso destruye el control mientras se procesa el clic
de su propio botón, y la ventana se cuelga — la trampa que el código ya advertía
desde SELL-B. Partirlo en dos actualizaciones no alcanza: las dos ocurren dentro del
mismo manejador. La salida es que **cerrar no toque el overlay** y que la limpieza
la haga el siguiente `abrir`.

Los cuatro comparten la misma forma: **el programa no falla, simplemente hace algo
distinto de lo que dice hacer.** Son los que las pruebas de "no revienta" no
encuentran, y por eso cada uno tiene ahora una prueba que lo vigila.

Y dejaron dos herramientas que faltaban, en `app/pruebas/`:

- **`revisar.py`** encuentra nombres que no existen sin ejecutar nada. Nació de que
  una pantalla reventaba al pulsar un botón y las 260 comprobaciones pasaban igual,
  porque construían las pantallas sin pulsar nada.
- **`probar_botones.py`** abre cada diálogo, llena sus campos, pulsa el botón y
  comprueba en la base que la acción ocurrió.

Se corren juntos con `python pruebas/correr.py`, y la revisión va primero.
