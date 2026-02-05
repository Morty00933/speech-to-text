-- Speech-to-Text Pipeline Database Initialization
-- This script runs automatically on first PostgreSQL startup

-- Create extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Job status enum
CREATE TYPE job_status AS ENUM (
    'queued',
    'processing',
    'completed',
    'failed',
    'cancelled'
);

-- Main transcription jobs table
CREATE TABLE IF NOT EXISTS transcription_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status job_status NOT NULL DEFAULT 'queued',

    -- Input
    audio_path VARCHAR(500) NOT NULL,
    audio_format VARCHAR(20),
    audio_duration FLOAT,
    file_size INTEGER,

    -- Options
    model_size VARCHAR(20) DEFAULT 'medium',
    language VARCHAR(10),
    enable_diarization BOOLEAN DEFAULT false,
    min_speakers INTEGER DEFAULT 1,
    max_speakers INTEGER,
    output_format VARCHAR(10) DEFAULT 'json',
    enable_timestamps BOOLEAN DEFAULT true,
    enable_punctuation BOOLEAN DEFAULT true,

    -- Result
    result_path VARCHAR(500),
    result_text TEXT,
    detected_language VARCHAR(10),
    speakers_count INTEGER,

    -- Metadata
    processing_time FLOAT,
    error_message TEXT,
    progress INTEGER DEFAULT 0,
    current_step VARCHAR(50),

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- API Key tracking
    api_key_hash VARCHAR(64)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_jobs_status ON transcription_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON transcription_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_api_key ON transcription_jobs(api_key_hash);

-- API Keys table for authentication
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_hash VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,
    rate_limit INTEGER DEFAULT 100,
    requests_count INTEGER DEFAULT 0
);

-- Job segments table for storing transcription segments
CREATE TABLE IF NOT EXISTS transcription_segments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES transcription_jobs(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    start_time FLOAT NOT NULL,
    end_time FLOAT NOT NULL,
    text TEXT NOT NULL,
    speaker VARCHAR(50),
    confidence FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_segments_job_id ON transcription_segments(job_id);

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_job_timestamps()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'processing' AND OLD.status = 'queued' THEN
        NEW.started_at = CURRENT_TIMESTAMP;
    ELSIF NEW.status IN ('completed', 'failed', 'cancelled') AND OLD.status != NEW.status THEN
        NEW.completed_at = CURRENT_TIMESTAMP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for automatic timestamp updates
DROP TRIGGER IF EXISTS trigger_update_job_timestamps ON transcription_jobs;
CREATE TRIGGER trigger_update_job_timestamps
    BEFORE UPDATE ON transcription_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_job_timestamps();

-- Insert default API key for development
INSERT INTO api_keys (key_hash, name, rate_limit)
VALUES (
    encode(sha256('dev-api-key'::bytea), 'hex'),
    'Development Key',
    1000
) ON CONFLICT (key_hash) DO NOTHING;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO stt;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO stt;
