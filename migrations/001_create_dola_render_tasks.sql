-- Migration for dola-render-gateway: Task Tracking & 24h Expiration
CREATE TABLE IF NOT EXISTS dola_render_tasks (
    id TEXT PRIMARY KEY,
    model TEXT,
    prompt TEXT,
    ratio TEXT,
    duration INTEGER,
    status TEXT DEFAULT 'pending',
    account TEXT,
    conversation_id TEXT,
    video_url TEXT,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (timezone('utc'::text, now()) + interval '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_dola_render_tasks_status ON dola_render_tasks (status);
CREATE INDEX IF NOT EXISTS idx_dola_render_tasks_created_at ON dola_render_tasks (created_at);
CREATE INDEX IF NOT EXISTS idx_dola_render_tasks_expires_at ON dola_render_tasks (expires_at);

-- Optional: Supabase Storage bucket policy (create bucket 'videos' if not exists)
INSERT INTO storage.buckets (id, name, public)
VALUES ('videos', 'videos', true)
ON CONFLICT (id) DO NOTHING;
