-- Lakebase Postgres schema for CoC Leagues Backend
CREATE TABLE IF NOT EXISTS public.cwl_leagues (
    id text NOT NULL PRIMARY KEY,
    clan_tag text NOT NULL,
    clan_name text NOT NULL,
    user_id text NOT NULL,
    user_email text,
    lineup_size integer NOT NULL DEFAULT 15,
    opted_in_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    schedule_by_day jsonb NOT NULL DEFAULT '{}'::jsonb,
    opponents_by_day jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cwl_leagues_clan_tag ON public.cwl_leagues (clan_tag);

CREATE TABLE IF NOT EXISTS public.user_ingame_accounts (
    id text NOT NULL PRIMARY KEY,
    user_id text NOT NULL,
    player_tag text NOT NULL,
    player_name text NOT NULL,
    town_hall_level integer NOT NULL DEFAULT 16,
    trophies integer NOT NULL DEFAULT 0,
    role text DEFAULT 'member'::text,
    clan_tag text NOT NULL,
    clan_name text NOT NULL,
    clan_badge_url text,
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_ingame_accounts_user_id ON public.user_ingame_accounts (user_id);
CREATE INDEX IF NOT EXISTS idx_user_ingame_accounts_player_tag ON public.user_ingame_accounts (player_tag);

