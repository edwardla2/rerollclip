-- Run once in the Supabase SQL editor (Project → SQL → New query).
create table if not exists public.waitlist (
  id bigint generated always as identity primary key,
  email text not null unique check (char_length(email) <= 254),
  game text check (game in ('valorant', 'cs2', 'fortnite', 'roblox', 'other')),
  windows text check (windows in ('11', '10', 'unsure')),
  source text,
  created_at timestamptz not null default now()
);

-- Row-level security on with no policies: the public (anon) key can't read or write.
-- Only the site's server function, using the service-role key, can insert.
alter table public.waitlist enable row level security;
