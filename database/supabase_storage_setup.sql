-- Supabase Storage setup for the merged workspace registration flow.
-- Run this in the Supabase SQL Editor for the project used by
-- RecDigit-main/Frontend/.env.local.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  (
    'candidate-cvs',
    'candidate-cvs',
    false,
    10485760,
    array[
      'application/pdf',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]
  ),
  (
    'company-logos',
    'company-logos',
    true,
    5242880,
    array[
      'image/png',
      'image/jpeg',
      'image/webp',
      'image/svg+xml'
    ]
  )
on conflict (id) do nothing;

drop policy if exists "Authenticated users can upload candidate CVs" on storage.objects;
create policy "Authenticated users can upload candidate CVs"
on storage.objects
for insert
to authenticated
with check (bucket_id = 'candidate-cvs');

drop policy if exists "Authenticated users can view candidate CVs" on storage.objects;
create policy "Authenticated users can view candidate CVs"
on storage.objects
for select
to authenticated
using (bucket_id = 'candidate-cvs');

drop policy if exists "Authenticated users can upload company logos" on storage.objects;
create policy "Authenticated users can upload company logos"
on storage.objects
for insert
to authenticated
with check (bucket_id = 'company-logos');

drop policy if exists "Anyone can view company logos" on storage.objects;
create policy "Anyone can view company logos"
on storage.objects
for select
to public
using (bucket_id = 'company-logos');
