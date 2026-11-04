CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Knowledge ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type text NOT NULL CHECK (source_type IN ('website','brochure','label','catalogue','technical','agronomy')),
  title text, url_or_path text NOT NULL, language text, sha256 text NOT NULL,
  version int NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','withdrawn')),
  fetched_at timestamptz DEFAULT now(),
  UNIQUE (url_or_path, version)
);
CREATE TABLE IF NOT EXISTS chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page int, section text, content text NOT NULL, language text,
  crops text[] NOT NULL DEFAULT '{}', problems text[] NOT NULL DEFAULT '{}',
  embedding vector(1024),
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  status text NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_crops_idx ON chunks USING gin (crops);

-- Verified product facts: the ONLY place dosage may come from -------------
CREATE TABLE IF NOT EXISTS products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE, aliases text[] NOT NULL DEFAULT '{}', category text,
  composition text, compatibility text, precautions text,
  status text NOT NULL DEFAULT 'verified' CHECK (status IN ('draft','verified','retired')),
  verified_by text NOT NULL, verified_on date NOT NULL
);
CREATE TABLE IF NOT EXISTS product_targets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  crop text NOT NULL, problem text NOT NULL, growth_stage text, method text,
  dosage text, frequency text,
  source_doc text NOT NULL, source_ref text NOT NULL, source_quote text NOT NULL,
  UNIQUE (product_id, crop, problem, method)
);

-- Conversation ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  channel text NOT NULL, channel_user_id text NOT NULL, name text,
  preferred_style text, consent_images boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (channel, channel_user_id)
);
CREATE TABLE IF NOT EXISTS cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  status text NOT NULL DEFAULT 'gathering',
  crop text, state jsonb NOT NULL DEFAULT '{}',
  opened_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz
);
CREATE INDEX IF NOT EXISTS cases_user_open_idx ON cases (user_id) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid REFERENCES cases(id), user_id uuid REFERENCES users(id),
  direction text NOT NULL CHECK (direction IN ('in','out')),
  text text, transcript text, style text, media text[] NOT NULL DEFAULT '{}',
  idempotency_key text UNIQUE, reply jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Learning ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS diagnoses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid REFERENCES cases(id), image_path text, result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS escalations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  short_code text UNIQUE NOT NULL,
  case_id uuid REFERENCES cases(id), user_id uuid REFERENCES users(id),
  reason text, status text NOT NULL DEFAULT 'open',
  agronomist_reply text, verified_crop text, verified_label text,
  created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz
);
CREATE TABLE IF NOT EXISTS feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid REFERENCES cases(id), source text NOT NULL, verdict text,
  corrected_crop text, corrected_label text, notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);
