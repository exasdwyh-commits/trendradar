-- Reverse material lookups otherwise scan all bindings once per listed material.
CREATE INDEX IF NOT EXISTS idx_document_materials_material
ON document_materials(material_id, document_id);

-- Used by document counts, the publish matrix and ordered publication history.
CREATE INDEX IF NOT EXISTS idx_publications_document
ON publications(document_id, published_at DESC);
