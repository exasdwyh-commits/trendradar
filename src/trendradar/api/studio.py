"""Creator Studio API: brief, materials, documents, writing assistant, variants, publications."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ..studio import agent as writing_agent
from ..studio import ai as studio_ai
from ..studio import brief as studio_brief
from ..studio import creation, translations
from ..studio import documents as docs
from ..studio import easel_bridge as easel
from ..studio import materials as mats
from ..studio import publishing as pub
from ..studio.overview import get_overview
from ..studio.stories import LANE_NAMES


# ───────────────────────── schemas ─────────────────────────
class BriefStatus(BaseModel):
    status: Literal["new", "saved", "dismissed"]


class ExtendRequest(BaseModel):
    angle: str | None = Field(default=None, max_length=200)


class MaterialCreate(BaseModel):
    kind: Literal["url", "note"] = "note"
    title: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    summary: str = Field(default="", max_length=2000)
    quote: str = Field(default="", max_length=1500)
    content: str = Field(default="", max_length=20000)
    tags: list[str] = Field(default_factory=list)
    lane: str | None = None


class MaterialUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    quote: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    lane: str | None = None
    archived: bool | None = None


class MaterialRef(BaseModel):
    ref_type: Literal["signal", "pain_cluster", "opportunity"]
    ref_id: str


class DocumentCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    content_md: str = ""
    thesis: str = Field(default="", max_length=1000)
    lane: str | None = None
    target_platform: Literal["wechat", "xiaohongshu", "zhihu", "toutiao", "x"] = "wechat"
    material_ids: list[str] = Field(default_factory=list)


class DocumentUpdate(BaseModel):
    title: str | None = None
    content_md: str | None = None
    thesis: str | None = None
    status: Literal["idea", "draft", "ready", "published", "archived"] | None = None
    lane: str | None = None
    target_platform: Literal["wechat", "xiaohongshu", "zhihu", "toutiao", "x"] | None = None
    save_mode: Literal["autosave", "manual", "ai"] = "autosave"
    note: str | None = Field(default=None, max_length=200)


class VersionCreate(BaseModel):
    note: str | None = Field(default=None, max_length=200)


class Bind(BaseModel):
    material_id: str
    relation: Literal["seed", "support", "context"] = "support"
    note: str | None = None


class AIRequest(BaseModel):
    selection: str | None = Field(default=None, max_length=8000)
    mode: str | None = None
    instruction: str | None = Field(default=None, max_length=500)
    platform: Literal["wechat", "xiaohongshu", "zhihu", "toutiao", "x"] | None = None
    section_id: str | None = Field(default=None, max_length=80)


class AIAccept(BaseModel):
    accepted: bool = True


class VariantCreate(BaseModel):
    platform: Literal["wechat", "xiaohongshu", "zhihu", "toutiao", "x"]


class VariantUpdate(BaseModel):
    title: str | None = None
    content_md: str | None = None


class PublicationCreate(BaseModel):
    platform: Literal["wechat", "xiaohongshu", "zhihu", "toutiao", "x"]
    external_url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=500)
    variant_id: str | None = None


class EaselHandoffRequest(BaseModel):
    variant_id: str | None = None


class WorkspaceUpdate(BaseModel):
    revision: int = Field(ge=0)
    changes: dict


class WorkspaceRevision(BaseModel):
    revision: int = Field(ge=0)


class ExcerptCreate(BaseModel):
    material_id: str
    fact: str = Field(min_length=1, max_length=1000)
    quote: str = Field(min_length=1, max_length=6000)
    note: str = Field(default="", max_length=2000)
    stance: Literal["support", "counter", "context"] = "support"


class SectionGenerate(WorkspaceRevision):
    instruction: str = Field(default="", max_length=1000)


class SectionAdopt(WorkspaceRevision):
    action_id: str


class AgentStart(BaseModel):
    instruction: str = Field(default="", max_length=2000)
    platforms: list[Literal["wechat", "xiaohongshu", "zhihu", "toutiao", "x"]] = Field(
        default_factory=list, max_length=5
    )
    restart: bool = False


class AgentStep(WorkspaceRevision):
    run_id: str = Field(min_length=1, max_length=80)


class AgentConfirm(AgentStep):
    proposal: dict


def build_router(get_conn) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/studio/overview")
    def studio_overview(conn: sqlite3.Connection = Depends(get_conn)):
        return get_overview(conn)

    @router.get("/documents/{document_id}/agent")
    def agent_status(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return writing_agent.get_latest(conn, document_id)

    @router.post("/documents/{document_id}/agent/start")
    def agent_start(document_id: str, body: AgentStart, conn: sqlite3.Connection = Depends(get_conn)):
        return writing_agent.start(conn, document_id, **body.model_dump())

    @router.post("/documents/{document_id}/agent/advance")
    def agent_advance(document_id: str, body: AgentStep, conn: sqlite3.Connection = Depends(get_conn)):
        return writing_agent.advance(conn, document_id, body.run_id, body.revision)

    @router.post("/documents/{document_id}/agent/confirm")
    def agent_confirm(document_id: str, body: AgentConfirm, conn: sqlite3.Connection = Depends(get_conn)):
        return writing_agent.confirm(conn, document_id, body.run_id, body.revision, body.proposal)

    @router.post("/documents/{document_id}/agent/adopt")
    def agent_adopt(document_id: str, body: AgentStep, conn: sqlite3.Connection = Depends(get_conn)):
        return writing_agent.adopt(conn, document_id, body.run_id, body.revision)

    @router.post("/brief/items/{item_id}/reassess")
    def brief_reassess(item_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return studio_brief.reassess_item(conn, item_id)

    @router.get("/documents/{document_id}/workspace")
    def workspace(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return creation.get_workspace(conn, document_id)

    @router.patch("/documents/{document_id}/workspace")
    def workspace_update(
        document_id: str, body: WorkspaceUpdate, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return creation.save_workspace(conn, document_id, body.changes, body.revision)

    @router.post("/documents/{document_id}/workspace/confirm")
    def outline_confirm(
        document_id: str, body: WorkspaceRevision, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return creation.confirm_outline(conn, document_id, body.revision)

    @router.post("/documents/{document_id}/workspace/excerpts", status_code=201)
    def excerpt_create(document_id: str, body: ExcerptCreate, conn: sqlite3.Connection = Depends(get_conn)):
        return creation.add_excerpt(conn, document_id, **body.model_dump())

    @router.delete("/documents/{document_id}/workspace/excerpts/{excerpt_id}")
    def excerpt_delete(
        document_id: str, excerpt_id: str, revision: int, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return creation.delete_excerpt(conn, document_id, excerpt_id, revision)

    @router.post("/documents/{document_id}/workspace/sections/{section_id}/generate")
    def section_generate(
        document_id: str, section_id: str, body: SectionGenerate, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return creation.generate_section(conn, document_id, section_id, body.revision, body.instruction)

    @router.post("/documents/{document_id}/workspace/sections/{section_id}/adopt")
    def section_adopt(
        document_id: str, section_id: str, body: SectionAdopt, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return creation.adopt_section(conn, document_id, section_id, body.action_id, body.revision)

    @router.post("/documents/{document_id}/workspace/assemble")
    def assemble(document_id: str, body: WorkspaceRevision, conn: sqlite3.Connection = Depends(get_conn)):
        return creation.assemble(conn, document_id, body.revision)

    @router.post("/documents/{document_id}/workspace/review")
    def review(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return creation.review_document(conn, document_id)

    @router.get("/translations/{ref_type}/{ref_id}")
    def translation(
        ref_type: Literal["signal", "material", "brief_item"],
        ref_id: str,
        scope: Literal["title", "full"] = "title",
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        return translations.get_translation(conn, ref_type, ref_id, scope)

    @router.post("/translations/{ref_type}/{ref_id}")
    def translate(
        ref_type: Literal["signal", "material", "brief_item"],
        ref_id: str,
        scope: Literal["title", "full"] = "title",
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        return translations.translate(conn, ref_type, ref_id, scope)

    # ── brief ──
    @router.get("/brief")
    def brief(
        day: str | None = None, include_dismissed: bool = False, conn: sqlite3.Connection = Depends(get_conn)
    ):
        data = studio_brief.get_brief(conn, day, include_dismissed=include_dismissed)
        data["lanes"] = LANE_NAMES
        return data

    @router.post("/brief/items/{item_id}/status")
    def brief_status(item_id: str, body: BriefStatus, conn: sqlite3.Connection = Depends(get_conn)):
        return studio_brief.set_item_status(conn, item_id, body.status)

    @router.post("/brief/items/{item_id}/extend")
    def brief_extend(
        item_id: str, body: ExtendRequest | None = None, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return studio_brief.extend_item(conn, item_id, angle=body.angle if body else None)

    @router.post("/brief/rebuild")
    def brief_rebuild(conn: sqlite3.Connection = Depends(get_conn)):
        """Recompose today's page from what is already in the database (no collection)."""
        return studio_brief.build_brief(conn)

    # ── materials ──
    @router.get("/materials")
    def materials(
        q: str | None = None,
        kind: str | None = None,
        archived: bool = False,
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        kinds = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM materials WHERE archived=? OR ? GROUP BY kind ORDER BY n DESC",
                (0, int(archived)),
            ).fetchall()
        }
        return {"items": mats.list_materials(conn, q=q, kind=kind, include_archived=archived), "kinds": kinds}

    @router.post("/materials", status_code=201)
    def material_create(body: MaterialCreate, conn: sqlite3.Connection = Depends(get_conn)):
        if body.kind == "url":
            material_id = mats.material_from_url(conn, body.url or "", note=body.content)
        else:
            material_id = mats.create_material(
                conn,
                kind="note",
                title=body.title or (body.content or "")[:60] or "备注",
                url=body.url,
                summary=body.summary,
                quote=body.quote,
                content=body.content,
                tags=body.tags,
                lane=body.lane,
                origin="manual",
            )
        return mats.get_material(conn, material_id)

    @router.post("/materials/from-ref", status_code=201)
    def material_from_ref(body: MaterialRef, conn: sqlite3.Connection = Depends(get_conn)):
        if body.ref_type == "signal":
            material_id = mats.material_from_signal(conn, body.ref_id)
        elif body.ref_type == "pain_cluster":
            material_id = mats.material_from_cluster(conn, body.ref_id)
        else:
            material_id = mats.material_from_opportunity(conn, body.ref_id)
        return mats.get_material(conn, material_id)

    @router.get("/materials/{material_id}")
    def material(material_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return mats.get_material(conn, material_id)

    @router.patch("/materials/{material_id}")
    def material_update(material_id: str, body: MaterialUpdate, conn: sqlite3.Connection = Depends(get_conn)):
        return mats.update_material(conn, material_id, body.model_dump(exclude_unset=True))

    @router.post("/materials/{material_id}/extend", status_code=201)
    def material_extend(material_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        material = mats.get_material(conn, material_id)
        document_id = docs.create_document(
            conn,
            title=material["title"],
            content_md=docs.seed_markdown(material),
            lane=material.get("lane"),
            seed_material_id=material_id,
        )
        return {"document_id": document_id, "material_id": material_id}

    # ── documents ──
    @router.get("/documents")
    def documents(
        status: str | None = None, q: str | None = None, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return {
            "items": docs.list_documents(conn, status=status, q=q),
            "statuses": docs.STATUSES,
            "platforms": pub.PLATFORM_NAMES,
        }

    @router.post("/documents", status_code=201)
    def document_create(body: DocumentCreate, conn: sqlite3.Connection = Depends(get_conn)):
        seed = body.material_ids[0] if body.material_ids else None
        document_id = docs.create_document(
            conn,
            title=body.title,
            content_md=body.content_md,
            thesis=body.thesis,
            lane=body.lane,
            target_platform=body.target_platform,
            seed_material_id=seed,
        )
        for material_id in body.material_ids[1:]:
            docs.bind_material(conn, document_id, material_id)
        return docs.get_document(conn, document_id)

    @router.get("/documents/{document_id}")
    def document(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return docs.get_document(conn, document_id)

    @router.patch("/documents/{document_id}")
    def document_update(document_id: str, body: DocumentUpdate, conn: sqlite3.Connection = Depends(get_conn)):
        fields = body.model_dump(exclude_unset=True)
        save_mode = fields.pop("save_mode", "autosave")
        note = fields.pop("note", None)
        return docs.update_document(conn, document_id, fields, save_mode=save_mode, note=note)

    @router.delete("/documents/{document_id}", status_code=204)
    def document_delete(document_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        docs.get_document(conn, document_id)
        docs.delete_document(conn, document_id)
        return Response(status_code=204)

    @router.post("/documents/{document_id}/versions", status_code=201)
    def version_create(document_id: str, body: VersionCreate, conn: sqlite3.Connection = Depends(get_conn)):
        number = docs.save_version(conn, document_id, body.note)
        return {"version_number": number}

    @router.get("/documents/{document_id}/versions/{number}")
    def version(document_id: str, number: int, conn: sqlite3.Connection = Depends(get_conn)):
        return docs.get_version(conn, document_id, number)

    @router.post("/documents/{document_id}/versions/{number}/restore")
    def version_restore(document_id: str, number: int, conn: sqlite3.Connection = Depends(get_conn)):
        return docs.restore_version(conn, document_id, number)

    @router.post("/documents/{document_id}/materials")
    def bind(document_id: str, body: Bind, conn: sqlite3.Connection = Depends(get_conn)):
        return docs.bind_material(conn, document_id, body.material_id, relation=body.relation, note=body.note)

    @router.delete("/documents/{document_id}/materials/{material_id}")
    def unbind(document_id: str, material_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return docs.unbind_material(conn, document_id, material_id)

    # ── writing assistant ──
    @router.post("/documents/{document_id}/ai/{action}")
    def ai_action(
        document_id: str,
        action: str,
        body: AIRequest | None = None,
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        options = body.model_dump(exclude_none=True) if body else {}
        return studio_ai.run_action(conn, document_id, action, options)

    @router.patch("/documents/{document_id}/ai/{action_id}")
    def ai_accept(
        document_id: str, action_id: str, body: AIAccept, conn: sqlite3.Connection = Depends(get_conn)
    ):
        studio_ai.mark_accepted(conn, document_id, action_id, body.accepted)
        return {"id": action_id, "accepted": body.accepted}

    @router.get("/studio/capabilities")
    def capabilities():
        return {
            "actions": studio_ai.ACTIONS,
            "rewrite_modes": studio_ai.REWRITE_MODES,
            "platforms": pub.PLATFORM_NAMES,
            "platform_rules": studio_ai.PLATFORM_RULES,
            "writing_slot": studio_ai.writing_slot(),
            "model_available": studio_ai.get_llm().slot_enabled(studio_ai.writing_slot()),
        }

    # ── variants / export / publications ──
    @router.post("/documents/{document_id}/variants", status_code=201)
    def variant_create(document_id: str, body: VariantCreate, conn: sqlite3.Connection = Depends(get_conn)):
        return pub.create_variant(conn, document_id, body.platform)

    @router.get("/variants/{variant_id}")
    def variant(variant_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return pub.get_variant(conn, variant_id)

    @router.patch("/variants/{variant_id}")
    def variant_update(variant_id: str, body: VariantUpdate, conn: sqlite3.Connection = Depends(get_conn)):
        return pub.update_variant(conn, variant_id, body.model_dump(exclude_unset=True))

    @router.delete("/variants/{variant_id}", status_code=204)
    def variant_delete(variant_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        pub.get_variant(conn, variant_id)
        pub.delete_variant(conn, variant_id)
        return Response(status_code=204)

    @router.get("/documents/{document_id}/export")
    def export(
        document_id: str,
        fmt: Literal["md", "html", "txt", "card"] = "md",
        variant_id: str | None = None,
        download: bool = False,
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        content, media_type, filename = pub.export_document(conn, document_id, fmt, variant_id=variant_id)
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"} if download else {}
        return Response(content=content, media_type=media_type, headers=headers)

    @router.post("/documents/{document_id}/publications", status_code=201)
    def publication_create(
        document_id: str, body: PublicationCreate, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return pub.record_publication(
            conn,
            document_id,
            platform=body.platform,
            external_url=body.external_url,
            note=body.note,
            variant_id=body.variant_id,
        )

    @router.delete("/publications/{publication_id}", status_code=204)
    def publication_delete(publication_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        pub.delete_publication(conn, publication_id)
        return Response(status_code=204)

    @router.get("/publish")
    def publish(conn: sqlite3.Connection = Depends(get_conn)):
        return pub.publish_center(conn)

    # ── Easel 发布桥接（docs/EASEL_BRIDGE.md）─────────────────────────────
    @router.get("/publish/easel")
    def easel_status():
        return {**easel.bridge_status(), "packages_detail": easel.list_packages()[:50]}

    @router.post("/documents/{document_id}/easel-handoff", status_code=201)
    def easel_handoff(
        document_id: str, body: EaselHandoffRequest, conn: sqlite3.Connection = Depends(get_conn)
    ):
        return easel.handoff(conn, document_id, variant_id=body.variant_id)

    @router.post("/publish/easel/sync")
    def easel_sync(conn: sqlite3.Connection = Depends(get_conn)):
        return easel.sync_results(conn)

    return router
