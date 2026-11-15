-- FINN chat memory. Run once in Supabase: Dashboard -> SQL Editor -> New query -> paste -> Run.
-- Row level security is ON with no policies, so the browser (anon key) can't read or write.
-- Only the Vercel server function, using the service-role key, can.

create table if not exists public.finn_messages (
  id          bigint generated always as identity primary key,
  user_id     text        not null,
  role        text        not null check (role in ('user', 'assistant')),
  content     text        not null,
  mode        text,
  symbols     text[]      default '{}',
  created_at  timestamptz not null default now()
);
create index if not exists finn_messages_user_time on public.finn_messages (user_id, created_at desc);

create table if not exists public.finn_memories (
  id          bigint generated always as identity primary key,
  user_id     text        not null,
  note        text        not null,
  created_at  timestamptz not null default now()
);
create index if not exists finn_memories_user_time on public.finn_memories (user_id, created_at desc);

alter table public.finn_messages enable row level security;
alter table public.finn_memories enable row level security;
