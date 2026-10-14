-- ShopStore's · la carpeta privada de descargas (Supabase Storage)
--
-- **Para que existe.** En el iPhone, Safari solo deja bajar un archivo si la orden
-- sale dentro del toque, y desde Python la orden llega tarde (lo mismo que paso
-- con la galeria). Lo que si funciona dentro del toque es abrir un enlace. Asi
-- que el respaldo y el resumen semanal se suben aca, Supabase da un enlace
-- firmado que vence en una hora, y el boton «Descargar» abre ese enlace.
--
-- **Es privada.** Cada cuenta tiene su carpeta, con el nombre de su usuario, y el
-- RLS de abajo hace que solo pueda leer y escribir en la suya. Sin enlace
-- firmado, un archivo de aca no se puede bajar ni conociendo su nombre.
--
-- Se guarda un solo archivo de cada cosa por cuenta (`respaldo.zip`,
-- `resumen.pdf`): el nuevo reemplaza al anterior, asi la carpeta no crece.
--
-- Se puede correr mas de una vez.
--
-- **Como se corre:** igual que los otros. SQL Editor -> New query -> pegar -> Run.

insert into storage.buckets (id, name, public, file_size_limit)
values ('descargas', 'descargas', false, 52428800)       -- 50 MB por archivo
on conflict (id) do nothing;

drop policy if exists "descargas: cada cuenta su carpeta" on storage.objects;
create policy "descargas: cada cuenta su carpeta" on storage.objects
    for all to authenticated
    using (bucket_id = 'descargas'
           and (storage.foldername(name))[1] = (select auth.uid()::text))
    with check (bucket_id = 'descargas'
                and (storage.foldername(name))[1] = (select auth.uid()::text));
