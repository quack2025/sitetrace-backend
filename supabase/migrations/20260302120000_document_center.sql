-- ============================================================
-- MIGRATION 005: Document Center + Bulletins
-- SiteTrace Document Currency Hub
-- ============================================================

-- ── Project Team Members ──
-- Who receives bulletins and notifications about document changes
CREATE TABLE IF NOT EXISTS project_team_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  role TEXT,  -- superintendent, foreman, painter, electrician, architect, client
  receives_bulletins BOOLEAN DEFAULT TRUE,
  phone TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(project_id, email)
);

-- ── Project Documents (Versioned) ──
-- Central registry of project documents with version control
CREATE TABLE IF NOT EXISTS project_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  category TEXT NOT NULL,   -- architectural_plans, paint_specs, electrical, plumbing, finishes, structural, mechanical
  name TEXT NOT NULL,
  version INT DEFAULT 1,
  status TEXT DEFAULT 'current' CHECK (status IN ('current', 'superseded', 'draft')),
  storage_path TEXT,          -- Supabase Storage path (standalone mode)
  external_url TEXT,          -- External URL: Google Drive, Dropbox, etc. (integration mode)
  mime_type TEXT,
  file_size_bytes BIGINT,
  uploaded_by UUID,
  superseded_by UUID REFERENCES project_documents(id),
  superseded_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_project_documents_project ON project_documents(project_id);
CREATE INDEX idx_project_documents_status ON project_documents(project_id, status);
CREATE INDEX idx_project_documents_category ON project_documents(project_id, category);

-- ── Change Order Documents (N:N linking) ──
-- Links change orders to documents they affect
CREATE TABLE IF NOT EXISTS change_order_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  change_order_id UUID REFERENCES change_orders(id) ON DELETE CASCADE,
  document_id UUID REFERENCES project_documents(id) ON DELETE CASCADE,
  impact_type TEXT DEFAULT 'supersedes' CHECK (impact_type IN ('supersedes', 'amends', 'references')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(change_order_id, document_id)
);

-- ── Document Bulletins ──
-- AI-generated summaries distributed when COs are signed
CREATE TABLE IF NOT EXISTS document_bulletins (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  change_order_id UUID REFERENCES change_orders(id),
  bulletin_number TEXT NOT NULL,
  title TEXT NOT NULL,
  summary_text TEXT NOT NULL,
  affected_areas JSONB DEFAULT '[]',     -- [{category, document_name, section, action}]
  distribution_list JSONB DEFAULT '[]',  -- [{email, name, role, sent_at}]
  pdf_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bulletins_project ON document_bulletins(project_id);
CREATE INDEX idx_bulletins_co ON document_bulletins(change_order_id);

-- ── Storage Bucket ──
INSERT INTO storage.buckets (id, name, public)
VALUES ('project-documents', 'project-documents', false)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('bulletins', 'bulletins', false)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- RLS POLICIES
-- ============================================================

ALTER TABLE project_team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_order_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_bulletins ENABLE ROW LEVEL SECURITY;

-- Service role full access (backend API)
CREATE POLICY "Service role full access on project_team_members"
  ON project_team_members FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access on project_documents"
  ON project_documents FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access on change_order_documents"
  ON change_order_documents FOR ALL
  TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access on document_bulletins"
  ON document_bulletins FOR ALL
  TO service_role USING (true) WITH CHECK (true);

-- Authenticated users: read own project data
CREATE POLICY "Contractors read own team members"
  ON project_team_members FOR SELECT
  TO authenticated
  USING (
    project_id IN (
      SELECT p.id FROM projects p
      JOIN contractors c ON p.contractor_id = c.id
      WHERE c.user_id = auth.uid()
    )
  );

CREATE POLICY "Contractors read own documents"
  ON project_documents FOR SELECT
  TO authenticated
  USING (
    project_id IN (
      SELECT p.id FROM projects p
      JOIN contractors c ON p.contractor_id = c.id
      WHERE c.user_id = auth.uid()
    )
  );

CREATE POLICY "Contractors read own bulletins"
  ON document_bulletins FOR SELECT
  TO authenticated
  USING (
    project_id IN (
      SELECT p.id FROM projects p
      JOIN contractors c ON p.contractor_id = c.id
      WHERE c.user_id = auth.uid()
    )
  );

-- Storage policies
CREATE POLICY "Service role manages project-documents"
  ON storage.objects FOR ALL
  TO service_role
  USING (bucket_id = 'project-documents')
  WITH CHECK (bucket_id = 'project-documents');

CREATE POLICY "Authenticated read project-documents"
  ON storage.objects FOR SELECT
  TO authenticated
  USING (bucket_id = 'project-documents');

CREATE POLICY "Service role manages bulletins"
  ON storage.objects FOR ALL
  TO service_role
  USING (bucket_id = 'bulletins')
  WITH CHECK (bucket_id = 'bulletins');

CREATE POLICY "Authenticated read bulletins"
  ON storage.objects FOR SELECT
  TO authenticated
  USING (bucket_id = 'bulletins');
