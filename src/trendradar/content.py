"""Public content-service facade.

Implementation is split by responsibility under trendradar.services.
Keeping one import surface avoids leaking directory structure into callers while
preventing this module from becoming another business-logic monolith.
"""

from .services import (
    create_blank_document,
    create_image_plan,
    create_platform_variant,
    edit_selection,
    ensure_document_for_article,
    export_variant,
    get_document,
    list_documents,
    list_publish_center,
    mark_variant_published,
    restore_version,
    save_document,
)

__all__ = [
    "create_blank_document",
    "create_image_plan",
    "create_platform_variant",
    "edit_selection",
    "ensure_document_for_article",
    "export_variant",
    "get_document",
    "list_documents",
    "list_publish_center",
    "mark_variant_published",
    "restore_version",
    "save_document",
]
