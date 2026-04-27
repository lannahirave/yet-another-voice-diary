-- Voice Diary Database Schema

-- Recording sessions
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    notes TEXT,
    language_hint TEXT
);

-- Speech utterances with transcripts
CREATE TABLE IF NOT EXISTS utterances (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    started_ms INTEGER NOT NULL,
    ended_ms INTEGER NOT NULL,
    transcript TEXT NOT NULL,
    language TEXT,
    confidence REAL,
    speaker_segment_id TEXT,
    source TEXT NOT NULL DEFAULT 'mic',
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (speaker_segment_id) REFERENCES speaker_segments(id)
);

-- Speaker segments for re-identification
CREATE TABLE IF NOT EXISTS speaker_segments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    contact_id TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    embedding BLOB,
    diarization_model_id TEXT NOT NULL DEFAULT 'pyannote',
    sim_score REAL,
    reviewed_at INTEGER,
    source TEXT NOT NULL DEFAULT 'mic',
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id)
);

-- Known contacts
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    notes TEXT,
    created_at INTEGER NOT NULL
);

-- Voice profiles for each contact (multiple per person)
CREATE TABLE IF NOT EXISTS voice_profiles (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    embedding BLOB NOT NULL,
    model_id TEXT NOT NULL DEFAULT 'ecapa',
    embedding_dim INTEGER NOT NULL DEFAULT 0,
    quality_score REAL,
    recorded_at INTEGER NOT NULL,
    source_session_id TEXT,
    source TEXT NOT NULL DEFAULT 'mic',
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    FOREIGN KEY (source_session_id) REFERENCES sessions(id)
);

-- Unresolved speakers queue
CREATE TABLE IF NOT EXISTS unknown_queue (
    id TEXT PRIMARY KEY,
    speaker_segment_id TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    resolved_contact_id TEXT,
    resolved_at INTEGER,
    source TEXT NOT NULL DEFAULT 'mic',
    FOREIGN KEY (speaker_segment_id) REFERENCES speaker_segments(id),
    FOREIGN KEY (resolved_contact_id) REFERENCES contacts(id)
);

-- Full-text search index for utterances
CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(
    transcript,
    content='utterances',
    content_rowid='rowid'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_utterances_session ON utterances(session_id);
CREATE INDEX IF NOT EXISTS idx_utterances_speaker ON utterances(speaker_segment_id);
CREATE INDEX IF NOT EXISTS idx_speaker_segments_session ON speaker_segments(session_id);
CREATE INDEX IF NOT EXISTS idx_speaker_segments_contact ON speaker_segments(contact_id);
CREATE INDEX IF NOT EXISTS idx_voice_profiles_contact ON voice_profiles(contact_id);
CREATE INDEX IF NOT EXISTS idx_unknown_queue_segment ON unknown_queue(speaker_segment_id);
-- Source-column indexes (idx_voice_profiles_source, idx_speaker_segments_source)
-- live in storage/source_migration.py because legacy databases need the
-- ALTER TABLE … ADD COLUMN to run before any index can reference `source`.
