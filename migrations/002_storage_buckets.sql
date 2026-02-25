-- Migration 002: Create Supabase Storage buckets
-- Run this after creating the Supabase project

-- Create storage buckets
INSERT INTO storage.buckets (id, name, public) VALUES
  ('evidence', 'evidence', false),
  ('change-orders', 'change-orders', false),
  ('processed', 'processed', false)
ON CONFLICT (id) DO NOTHING;

-- RLS policies for evidence bucket
-- Contractors can upload/read evidence for their projects
CREATE POLICY "Contractors can upload evidence"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'evidence'
  AND (storage.foldername(name))[1] IN (
    SELECT id::text FROM projects WHERE contractor_id = (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  )
);

CREATE POLICY "Contractors can view evidence"
ON storage.objects FOR SELECT
TO authenticated
USING (
  bucket_id = 'evidence'
  AND (storage.foldername(name))[1] IN (
    SELECT id::text FROM projects WHERE contractor_id = (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  )
);

-- RLS policies for change-orders bucket
CREATE POLICY "Contractors can upload change order PDFs"
ON storage.objects FOR INSERT
TO authenticated
WITH CHECK (
  bucket_id = 'change-orders'
  AND (storage.foldername(name))[1] IN (
    SELECT id::text FROM projects WHERE contractor_id = (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  )
);

CREATE POLICY "Contractors can view change order PDFs"
ON storage.objects FOR SELECT
TO authenticated
USING (
  bucket_id = 'change-orders'
  AND (storage.foldername(name))[1] IN (
    SELECT id::text FROM projects WHERE contractor_id = (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  )
);

-- Service role can access all buckets (for backend operations)
CREATE POLICY "Service role full access evidence"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'evidence')
WITH CHECK (bucket_id = 'evidence');

CREATE POLICY "Service role full access change-orders"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'change-orders')
WITH CHECK (bucket_id = 'change-orders');

CREATE POLICY "Service role full access processed"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'processed')
WITH CHECK (bucket_id = 'processed');

-- Add client_ip and client_user_agent columns to change_orders if not exists
DO $$ BEGIN
  ALTER TABLE change_orders ADD COLUMN IF NOT EXISTS client_ip TEXT;
  ALTER TABLE change_orders ADD COLUMN IF NOT EXISTS client_user_agent TEXT;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
