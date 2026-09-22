from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..content import (
    create_blank_document,
    create_image_plan,
    create_platform_variant,
    edit_selection,
    export_variant,
    get_document,
    list_documents,
    list_publish_center,
    mark_variant_published,
    restore_version,
    save_document,
)
from ..exporter import export_markdown, export_wechat_html


class DocumentCreateBody(BaseModel):
    title: str = "未命名文章"


class DocumentSaveBody(BaseModel):
    title: str
    content_json: dict
    content_html: str = ""
    plain_text: str = ""
    source: str = "MANUAL"
    note: str | None = None


class PlatformVariantBody(BaseModel):
    platform: str


class SelectionEditBody(BaseModel):
    selected_text: str
    instruction: str
    before_context: str = ""
    after_context: str = ""


class PublishedBody(BaseModel):
    external_url: str | None = None


def build_content_router(get_conn, output_dir: Path) -> APIRouter:
    router=APIRouter()

    @router.post("/api/articles/{article_id}/export/{format_name}")
    def export_article(article_id: str, format_name: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            if format_name=="md":
                path=export_markdown(conn,article_id,output_dir)
            elif format_name=="wechat":
                path=export_wechat_html(conn,article_id,output_dir)
            else:
                raise ValueError("format must be md or wechat")
            return {"ok":True,"file":path.name,"url":f"/exports/{path.name}"}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get("/api/documents")
    def documents(conn: sqlite3.Connection = Depends(get_conn)):
        return {"items":list_documents(conn)}

    @router.post("/api/documents")
    def create_document(body: DocumentCreateBody, conn: sqlite3.Connection = Depends(get_conn)):
        return {"ok":True,"document_id":create_blank_document(conn,body.title)}

    @router.get("/api/documents/{document_id}")
    def document(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        data=get_document(conn,document_id)
        if not data:
            raise HTTPException(404,"document not found")
        return data

    @router.put("/api/documents/{document_id}")
    def update_document(document_id: str, body: DocumentSaveBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            version=save_document(
                conn,document_id,body.title,body.content_json,body.content_html,
                body.plain_text,body.source,body.note,
            )
            return {"ok":True,"version":version}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/documents/{document_id}/restore/{version_number}")
    def restore_document(document_id: str, version_number: int, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"version":restore_version(conn,document_id,version_number)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/documents/{document_id}/edit-selection")
    def document_edit_selection(document_id: str, body: SelectionEditBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {
                "ok":True,
                **edit_selection(
                    conn,document_id,body.selected_text,body.instruction,
                    body.before_context,body.after_context,
                ),
            }
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/documents/{document_id}/image-plan")
    def image_plan(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {"ok":True,"items":create_image_plan(conn,document_id)}
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/documents/{document_id}/variant")
    def platform_variant(document_id: str, body: PlatformVariantBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {
                "ok":True,
                "variant_id":create_platform_variant(conn,document_id,body.platform),
            }
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get("/api/publish")
    def publish_center(conn: sqlite3.Connection = Depends(get_conn)):
        return {"items":list_publish_center(conn)}

    @router.post("/api/platform-variants/{variant_id}/published")
    def mark_published(variant_id: str, body: PublishedBody, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            return {
                "ok":True,
                "publication_id":mark_variant_published(conn,variant_id,body.external_url),
            }
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post("/api/platform-variants/{variant_id}/export")
    def export_platform_variant(variant_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            path=export_variant(conn,variant_id,output_dir/"platforms")
            return {
                "ok":True,
                "file":path.name,
                "url":f"/exports/platforms/{path.name}",
            }
        except Exception as exc:
            raise HTTPException(400,str(exc)) from exc

    return router
