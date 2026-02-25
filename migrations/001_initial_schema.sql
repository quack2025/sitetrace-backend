-- SiteTrace Initial Schema v3.0
-- Execute in Supabase SQL Editor

-- Extensiones
CREATE EXTENSION IF NOT EXISTS "vector";

-- Usuarios / Contratistas
CREATE TABLE contractors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  company TEXT,
  email TEXT NOT NULL,
  phone TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Proyectos
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contractor_id UUID REFERENCES contractors(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  address TEXT,
  client_name TEXT NOT NULL,
  client_email TEXT NOT NULL,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'completed', 'archived')),
  project_type TEXT CHECK (project_type IN ('residential', 'commercial', 'remodel', 'new_build')),
  scope_summary TEXT,
  key_materials JSONB DEFAULT '[]',
  original_budget DECIMAL(12,2),
  currency TEXT DEFAULT 'USD',
  gmail_label TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Eventos de ingesta (capa abstracta de entrada)
CREATE TABLE ingest_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id),
  channel TEXT NOT NULL CHECK (channel IN ('gmail', 'outlook', 'whatsapp', 'manual', 'api')),
  raw_payload JSONB NOT NULL,
  attachments JSONB DEFAULT '[]',
  sender_email TEXT,
  sender_name TEXT,
  subject TEXT,
  received_at TIMESTAMPTZ,
  external_message_id TEXT UNIQUE,
  processing_status TEXT DEFAULT 'queued' CHECK (
    processing_status IN ('queued', 'processing', 'completed', 'failed')
  ),
  error_message TEXT,
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Eventos de cambio detectados
CREATE TABLE change_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  status TEXT DEFAULT 'proposed' CHECK (
    status IN ('proposed', 'confirmed', 'rejected', 'pending_client', 'signed', 'manual_review')
  ),
  description TEXT NOT NULL,
  area TEXT,
  material_from TEXT,
  material_to TEXT,
  confidence_score FLOAT CHECK (confidence_score BETWEEN 0 AND 1),
  raw_text TEXT,
  evidence_urls TEXT[] DEFAULT '{}',
  embedding vector(1536),
  prompt_version TEXT,
  model_used TEXT,
  tokens_used INT,
  processing_time_ms INT,
  proposed_at TIMESTAMPTZ DEFAULT NOW(),
  confirmed_at TIMESTAMPTZ,
  rejected_at TIMESTAMPTZ,
  rejection_reason TEXT,
  confirmed_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Relación N:N entre ingest_events y change_events
CREATE TABLE change_event_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  change_event_id UUID REFERENCES change_events(id) ON DELETE CASCADE,
  ingest_event_id UUID REFERENCES ingest_events(id) ON DELETE CASCADE,
  relevance_score FLOAT DEFAULT 1.0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(change_event_id, ingest_event_id)
);

-- Change Orders
CREATE TABLE change_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id),
  order_number TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT DEFAULT 'draft' CHECK (
    status IN ('draft', 'sent_to_client', 'signed', 'rejected_by_client')
  ),
  subtotal DECIMAL(12,2) DEFAULT 0,
  markup_percent DECIMAL(5,2) DEFAULT 0,
  markup_amount DECIMAL(12,2) DEFAULT 0,
  tax_percent DECIMAL(5,2) DEFAULT 0,
  tax_amount DECIMAL(12,2) DEFAULT 0,
  total DECIMAL(12,2) DEFAULT 0,
  currency TEXT DEFAULT 'USD',
  pdf_url TEXT,
  cf_change_order_id TEXT,
  sent_to_client_at TIMESTAMPTZ,
  signed_at TIMESTAMPTZ,
  client_ip INET,
  client_user_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Line items de un Change Order
CREATE TABLE change_order_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  change_order_id UUID REFERENCES change_orders(id) ON DELETE CASCADE,
  change_event_id UUID REFERENCES change_events(id),
  description TEXT NOT NULL,
  category TEXT CHECK (category IN ('labor', 'material', 'equipment', 'subcontract', 'other')),
  quantity DECIMAL(10,2) DEFAULT 1,
  unit TEXT DEFAULT 'unit',
  unit_cost DECIMAL(12,2) DEFAULT 0,
  total_cost DECIMAL(12,2) DEFAULT 0,
  notes TEXT,
  sort_order INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notificaciones (email)
CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id),
  change_event_id UUID REFERENCES change_events(id),
  type TEXT CHECK (type IN (
    'change_proposed',
    'change_confirmed',
    'client_sign_request',
    'change_closed'
  )),
  recipient_email TEXT NOT NULL,
  recipient_role TEXT CHECK (recipient_role IN ('contractor', 'client')),
  action_token TEXT,
  action_token_expires_at TIMESTAMPTZ,
  action_token_used_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  opened_at TIMESTAMPTZ,
  action_taken_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Notificaciones in-app
CREATE TABLE in_app_notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contractor_id UUID REFERENCES contractors(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  entity_type TEXT,
  entity_id UUID,
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- State transitions (event sourcing light)
CREATE TABLE state_transitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('change_event', 'change_order', 'project', 'integration')),
  entity_id UUID NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  actor_id UUID,
  actor_type TEXT CHECK (actor_type IN ('system', 'contractor', 'client', 'ai')),
  reason TEXT,
  metadata JSONB DEFAULT '{}',
  ip_address INET,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Integraciones por contratista
CREATE TABLE integrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contractor_id UUID REFERENCES contractors(id),
  type TEXT CHECK (type IN ('gmail', 'outlook', 'contractor_foreman')),
  access_token TEXT,
  refresh_token TEXT,
  token_expires_at TIMESTAMPTZ,
  cf_api_key TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  last_polled_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices
CREATE INDEX idx_ingest_events_project ON ingest_events(project_id);
CREATE INDEX idx_ingest_events_status ON ingest_events(processing_status);
CREATE INDEX idx_ingest_events_external_id ON ingest_events(external_message_id);
CREATE INDEX idx_change_events_project ON change_events(project_id);
CREATE INDEX idx_change_events_status ON change_events(status);
CREATE INDEX idx_change_orders_project ON change_orders(project_id);
CREATE INDEX idx_state_transitions_entity ON state_transitions(entity_type, entity_id);
CREATE INDEX idx_in_app_notifications_contractor ON in_app_notifications(contractor_id, read_at);

-- Row Level Security
ALTER TABLE contractors ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_event_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE in_app_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE state_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "contractors_own" ON contractors
  FOR ALL USING (user_id = auth.uid());

CREATE POLICY "projects_own" ON projects
  FOR ALL USING (contractor_id IN (
    SELECT id FROM contractors WHERE user_id = auth.uid()
  ));

CREATE POLICY "change_events_own" ON change_events
  FOR ALL USING (project_id IN (
    SELECT id FROM projects WHERE contractor_id IN (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  ));

CREATE POLICY "change_orders_own" ON change_orders
  FOR ALL USING (project_id IN (
    SELECT id FROM projects WHERE contractor_id IN (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  ));

CREATE POLICY "ingest_events_own" ON ingest_events
  FOR ALL USING (project_id IN (
    SELECT id FROM projects WHERE contractor_id IN (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  ));

CREATE POLICY "change_event_sources_own" ON change_event_sources
  FOR ALL USING (change_event_id IN (
    SELECT id FROM change_events WHERE project_id IN (
      SELECT id FROM projects WHERE contractor_id IN (
        SELECT id FROM contractors WHERE user_id = auth.uid()
      )
    )
  ));

CREATE POLICY "change_order_items_own" ON change_order_items
  FOR ALL USING (change_order_id IN (
    SELECT id FROM change_orders WHERE project_id IN (
      SELECT id FROM projects WHERE contractor_id IN (
        SELECT id FROM contractors WHERE user_id = auth.uid()
      )
    )
  ));

CREATE POLICY "notifications_own" ON notifications
  FOR ALL USING (project_id IN (
    SELECT id FROM projects WHERE contractor_id IN (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  ));

CREATE POLICY "in_app_notifications_own" ON in_app_notifications
  FOR ALL USING (contractor_id IN (
    SELECT id FROM contractors WHERE user_id = auth.uid()
  ));

CREATE POLICY "state_transitions_own" ON state_transitions
  FOR ALL USING (entity_id IN (
    SELECT id FROM change_events WHERE project_id IN (
      SELECT id FROM projects WHERE contractor_id IN (
        SELECT id FROM contractors WHERE user_id = auth.uid()
      )
    )
    UNION
    SELECT id FROM change_orders WHERE project_id IN (
      SELECT id FROM projects WHERE contractor_id IN (
        SELECT id FROM contractors WHERE user_id = auth.uid()
      )
    )
    UNION
    SELECT id FROM projects WHERE contractor_id IN (
      SELECT id FROM contractors WHERE user_id = auth.uid()
    )
  ));

CREATE POLICY "integrations_own" ON integrations
  FOR ALL USING (contractor_id IN (
    SELECT id FROM contractors WHERE user_id = auth.uid()
  ));

-- Función helper para updated_at automático
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_contractors_updated_at BEFORE UPDATE ON contractors
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_change_events_updated_at BEFORE UPDATE ON change_events
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_change_orders_updated_at BEFORE UPDATE ON change_orders
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
