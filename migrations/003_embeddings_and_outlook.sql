-- Migration 003: Add embedding support and Outlook integration fields

-- Enable pgvector extension for embedding storage
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column to change_events
ALTER TABLE change_events ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Index for fast similarity search within a project
CREATE INDEX IF NOT EXISTS idx_change_events_embedding
ON change_events USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 10);

-- Index for project-scoped queries on change_events
CREATE INDEX IF NOT EXISTS idx_change_events_project_status
ON change_events (project_id, status);

-- Add connected_email to integrations for display purposes
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS connected_email TEXT;

-- Add cf_project_id to projects (Contractor Foreman mapping)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS cf_project_id TEXT;
