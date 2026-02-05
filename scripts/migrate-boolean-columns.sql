-- Migration: Convert enable_diarization, enable_timestamps, enable_punctuation
-- from VARCHAR(5) ('true'/'false') to BOOLEAN.
--
-- Run this script ONLY on databases created before the Boolean column fix.
-- Safe to run multiple times (checks column type before altering).
--
-- Usage:
--   psql "$DATABASE_URL" -f scripts/migrate-boolean-columns.sql

DO $$
DECLARE
    col_type TEXT;
BEGIN
    -- Check current type of enable_diarization
    SELECT data_type INTO col_type
    FROM information_schema.columns
    WHERE table_name = 'transcription_jobs'
      AND column_name = 'enable_diarization';

    IF col_type = 'character varying' THEN
        RAISE NOTICE 'Migrating VARCHAR boolean columns to BOOLEAN...';

        ALTER TABLE transcription_jobs
            ALTER COLUMN enable_diarization
                TYPE BOOLEAN USING (enable_diarization = 'true'),
            ALTER COLUMN enable_diarization SET DEFAULT false;

        ALTER TABLE transcription_jobs
            ALTER COLUMN enable_timestamps
                TYPE BOOLEAN USING (enable_timestamps = 'true'),
            ALTER COLUMN enable_timestamps SET DEFAULT true;

        ALTER TABLE transcription_jobs
            ALTER COLUMN enable_punctuation
                TYPE BOOLEAN USING (enable_punctuation = 'true'),
            ALTER COLUMN enable_punctuation SET DEFAULT true;

        RAISE NOTICE 'Migration complete.';
    ELSE
        RAISE NOTICE 'Columns already BOOLEAN, no migration needed.';
    END IF;
END
$$;
