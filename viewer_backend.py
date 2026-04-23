"""FastAPI backend for interactive diff review and human validation workflow."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request


DEFAULT_DIFF_PATH = Path("d591_d595_diff.json")
DB_PATH = Path("viewer_state.db")
BASE_DIR = Path(__file__).resolve().parent


@dataclass
class DiffContext:
    """In-memory holder for currently loaded diff report and file path."""

    path: Path
    report: Dict[str, Any]


class ReviewUpdateRequest(BaseModel):
    """Payload for human review status updates."""

    validation_status: str = Field(pattern=r"^(approved|rejected|needs_review)$")
    reviewer: str = "anonymous"
    note: str = ""


class ClassificationUpdateRequest(BaseModel):
    """Payload for manual/automated classification updates."""

    classification: Optional[str] = Field(default=None, pattern=r"^(editorial|slight|significant)?$")
    source: str = "manual"


class ReviewStore:
    """SQLite-backed persistence for review and classification annotations."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        """Open a sqlite connection with row dict-style access."""

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create required tables if they do not already exist."""

        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS diff_review (
                    diff_id TEXT PRIMARY KEY,
                    validation_status TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    note TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS diff_classification (
                    diff_id TEXT PRIMARY KEY,
                    classification TEXT,
                    source TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def set_review(self, diff_id: str, update: ReviewUpdateRequest) -> None:
        """Insert or update review metadata for one diff item."""

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO diff_review(diff_id, validation_status, reviewer, note, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(diff_id) DO UPDATE SET
                    validation_status=excluded.validation_status,
                    reviewer=excluded.reviewer,
                    note=excluded.note,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (diff_id, update.validation_status, update.reviewer, update.note),
            )

    def set_classification(self, diff_id: str, update: ClassificationUpdateRequest) -> None:
        """Insert or update classification metadata for one diff item."""

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO diff_classification(diff_id, classification, source, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(diff_id) DO UPDATE SET
                    classification=excluded.classification,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (diff_id, update.classification, update.source),
            )

    def get_review(self, diff_id: str) -> Optional[Dict[str, Any]]:
        """Fetch review metadata for one diff id."""

        with self._conn() as conn:
            row = conn.execute("SELECT * FROM diff_review WHERE diff_id = ?", (diff_id,)).fetchone()
            return dict(row) if row else None

    def get_classification(self, diff_id: str) -> Optional[Dict[str, Any]]:
        """Fetch classification metadata for one diff id."""

        with self._conn() as conn:
            row = conn.execute("SELECT * FROM diff_classification WHERE diff_id = ?", (diff_id,)).fetchone()
            return dict(row) if row else None


def load_report(path: Path) -> Dict[str, Any]:
    """Load a diff report JSON file from disk."""

    if not path.exists():
        raise FileNotFoundError(f"Diff file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _diff_id(diff: Dict[str, Any], idx: int) -> str:
    """Build deterministic UI id for a diff row."""

    sid_a = diff.get("section_id_a") or "none"
    sid_b = diff.get("section_id_b") or "none"
    return f"{idx}:{sid_a}->{sid_b}"


def merge_runtime_fields(store: ReviewStore, diffs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Overlay persisted review/classification state onto raw diff payload."""

    enriched: List[Dict[str, Any]] = []
    for idx, diff in enumerate(diffs):
        item = dict(diff)
        diff_id = _diff_id(diff, idx)
        item["diff_id"] = diff_id

        review = store.get_review(diff_id)
        item["human_review"] = review or {
            "validation_status": "needs_review",
            "reviewer": "",
            "note": "",
            "updated_at": None,
        }

        classification = store.get_classification(diff_id)
        if classification and classification.get("classification"):
            item["change_classification"] = classification["classification"]
            item["classification_source"] = classification.get("source")
        else:
            item["classification_source"] = "diff_payload" if item.get("change_classification") else None

        enriched.append(item)
    return enriched


def create_app(diff_path: Path = DEFAULT_DIFF_PATH, db_path: Path = DB_PATH) -> FastAPI:
    """Create and configure FastAPI app instance."""

    app = FastAPI(title="PDF Diff Viewer", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    resolved_diff_path = diff_path if diff_path.is_absolute() else BASE_DIR / diff_path
    resolved_db_path = db_path if db_path.is_absolute() else BASE_DIR / db_path
    context = DiffContext(path=resolved_diff_path, report=load_report(resolved_diff_path))
    store = ReviewStore(resolved_db_path)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "title": "PDF Diff Viewer",
                "diff_file": str(context.path),
            },
        )

    @app.get("/api/diffs")
    async def get_diffs() -> Dict[str, Any]:
        diffs = merge_runtime_fields(store, context.report.get("diffs", []))
        return {
            "pdf_a": context.report.get("pdf_a"),
            "pdf_b": context.report.get("pdf_b"),
            "summary": context.report.get("summary", {}),
            "diffs": diffs,
        }

    @app.get("/api/diffs/{diff_id}")
    async def get_diff_by_id(diff_id: str) -> Dict[str, Any]:
        diffs = merge_runtime_fields(store, context.report.get("diffs", []))
        for d in diffs:
            if d.get("diff_id") == diff_id:
                return d
        raise HTTPException(status_code=404, detail="Diff not found")

    @app.post("/api/diffs/{diff_id}/human-review")
    async def set_human_review(diff_id: str, payload: ReviewUpdateRequest) -> Dict[str, Any]:
        store.set_review(diff_id, payload)
        return {"ok": True, "diff_id": diff_id, "human_review": store.get_review(diff_id)}

    @app.post("/api/diffs/{diff_id}/classify")
    async def set_classification(diff_id: str, payload: ClassificationUpdateRequest) -> Dict[str, Any]:
        store.set_classification(diff_id, payload)
        return {
            "ok": True,
            "diff_id": diff_id,
            "classification": store.get_classification(diff_id),
        }

    @app.post("/api/reload")
    async def reload_report() -> Dict[str, Any]:
        context.report = load_report(context.path)
        return {
            "ok": True,
            "summary": context.report.get("summary", {}),
            "count": len(context.report.get("diffs", [])),
        }

    return app


app = create_app()


def main() -> None:
    """Local development server entrypoint."""

    import uvicorn

    uvicorn.run("viewer_backend:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
