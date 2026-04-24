"""FastAPI backend for interactive diff review and human validation workflow."""

from __future__ import annotations

import json
import sqlite3
import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request


DEFAULT_DIFF_PATH = Path("d591_d595_diff.json")
DB_PATH = Path("viewer_state.db")
BASE_DIR = Path(__file__).resolve().parent
ENV_DIFF_PATH = "PDF_DIFFER_DIFF_PATH"
ENV_DB_PATH = "PDF_DIFFER_DB_PATH"


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


class ReloadRequest(BaseModel):
    """Optional request body for reloading/switching the active diff JSON."""

    path: Optional[str] = None


class ClassificationImportRequest(BaseModel):
    """Optional request body for loading a classified-report JSON file."""

    path: Optional[str] = None


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


def list_available_reports(base_dir: Path) -> List[str]:
    """List JSON report candidates in a directory."""

    return sorted(p.name for p in base_dir.glob("*.json") if p.is_file())


def list_available_csvs(base_dir: Path) -> List[str]:
    """List CSV exports available for download in a directory."""

    return sorted(p.name for p in base_dir.glob("*.csv") if p.is_file())


def _classification_candidate_paths(diff_report_path: Path) -> List[Path]:
    """Build likely classified-report file paths for a given diff report path."""

    stem = diff_report_path.stem
    candidates: List[Path] = []
    if "_diff" in stem:
        candidates.append(diff_report_path.with_name(stem.replace("_diff", "_classified") + ".json"))
    candidates.append(diff_report_path.with_name(stem + "_classified.json"))
    # Deduplicate while preserving order
    seen = set()
    unique: List[Path] = []
    for c in candidates:
        if c not in seen:
            unique.append(c)
            seen.add(c)
    return unique


def load_external_classifications(path: Path) -> Dict[str, str]:
    """Load section_id -> final_classification mapping from classified report JSON."""

    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for row in payload.get("classifications", []):
        sid = row.get("section_id")
        label = row.get("final_classification")
        if sid and label:
            out[str(sid)] = str(label)
    return out


def discover_external_classifications(diff_report_path: Path) -> tuple[Dict[str, str], Optional[Path]]:
    """Find and load first available classified-report sibling; return empty mapping if none."""

    for candidate in _classification_candidate_paths(diff_report_path):
        data = load_external_classifications(candidate)
        if data:
            return data, candidate
    return {}, None


def resolve_report_path(base_dir: Path, requested: str | None, current: Path) -> Path:
    """
    Resolve a user-requested report path safely under the report directory.

    Allows file-name selection from the dropdown without permitting traversal
    outside `base_dir`.
    """

    if not requested:
        return current

    candidate = Path(requested)
    candidate = candidate if candidate.is_absolute() else (base_dir / candidate)
    candidate = candidate.resolve()
    base_resolved = base_dir.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise FileNotFoundError("Requested report path is outside allowed directory")
    if not candidate.exists() or candidate.suffix.lower() != ".json":
        raise FileNotFoundError(f"Requested report not found: {candidate}")
    return candidate


def resolve_csv_path(base_dir: Path, requested: str) -> Path:
    """Resolve a CSV download path safely under the report directory."""

    candidate = (base_dir / requested).resolve()
    base_resolved = base_dir.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise FileNotFoundError("Requested CSV path is outside allowed directory")
    if not candidate.exists() or candidate.suffix.lower() != ".csv":
        raise FileNotFoundError(f"Requested CSV not found: {candidate}")
    return candidate


def _diff_id(diff: Dict[str, Any], idx: int) -> str:
    """Build deterministic UI id for a diff row."""

    sid_a = diff.get("section_id_a") or "none"
    sid_b = diff.get("section_id_b") or "none"
    return f"{idx}:{sid_a}->{sid_b}"


def merge_runtime_fields(
    store: ReviewStore,
    diffs: List[Dict[str, Any]],
    external_classifications: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Overlay persisted review/classification state onto raw diff payload."""

    external_classifications = external_classifications or {}
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
            if not item.get("change_classification"):
                sid_b = item.get("section_id_b")
                sid_a = item.get("section_id_a")
                label = None
                if sid_b and sid_b in external_classifications:
                    label = external_classifications[sid_b]
                elif sid_a and sid_a in external_classifications:
                    label = external_classifications[sid_a]
                if label:
                    item["change_classification"] = label
                    item["classification_source"] = "classified_report"
            item["classification_source"] = "diff_payload" if item.get("change_classification") and not item.get("classification_source") else item.get("classification_source")

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
    reports_dir = context.path.parent
    external_classifications, external_source = discover_external_classifications(context.path)

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
        diffs = merge_runtime_fields(
            store,
            context.report.get("diffs", []),
            external_classifications=external_classifications,
        )
        return {
            "pdf_a": context.report.get("pdf_a"),
            "pdf_b": context.report.get("pdf_b"),
            "summary": context.report.get("summary", {}),
            "diffs": diffs,
            "diff_file": context.path.name,
            "external_classification_file": external_source.name if external_source else None,
        }

    @app.get("/api/reports")
    async def get_reports() -> Dict[str, Any]:
        return {
            "current": context.path.name,
            "reports": list_available_reports(reports_dir),
        }

    @app.get("/api/csvs")
    async def get_csvs() -> Dict[str, Any]:
        return {
            "csvs": list_available_csvs(reports_dir),
        }

    @app.get("/api/csvs/download")
    async def download_csv(name: str) -> FileResponse:
        try:
            csv_path = resolve_csv_path(reports_dir, name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path=csv_path, media_type="text/csv", filename=csv_path.name)

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
    async def reload_report(payload: Optional[ReloadRequest] = None) -> Dict[str, Any]:
        nonlocal external_classifications, external_source
        requested = payload.path if payload else None
        context.path = resolve_report_path(reports_dir, requested, context.path)
        context.report = load_report(context.path)
        external_classifications, external_source = discover_external_classifications(context.path)
        return {
            "ok": True,
            "diff_file": context.path.name,
            "external_classification_file": external_source.name if external_source else None,
            "summary": context.report.get("summary", {}),
            "count": len(context.report.get("diffs", [])),
        }

    @app.post("/api/classifications/import")
    async def import_external_classifications(payload: Optional[ClassificationImportRequest] = None) -> Dict[str, Any]:
        nonlocal external_classifications, external_source
        requested = payload.path if payload and payload.path else None
        if requested:
            candidate = resolve_report_path(reports_dir, requested, context.path)
            external_classifications = load_external_classifications(candidate)
            external_source = candidate if external_classifications else None
        else:
            external_classifications, external_source = discover_external_classifications(context.path)
        return {
            "ok": True,
            "loaded": len(external_classifications),
            "source": external_source.name if external_source else None,
        }

    return app


def build_app_from_env() -> FastAPI:
    """App factory used by uvicorn reload mode."""

    diff_path = Path(os.environ.get(ENV_DIFF_PATH, str(DEFAULT_DIFF_PATH)))
    db_path = Path(os.environ.get(ENV_DB_PATH, str(DB_PATH)))
    return create_app(diff_path=diff_path, db_path=db_path)


app = build_app_from_env()


def main() -> None:
    """Local development server entrypoint."""

    import uvicorn
    parser = argparse.ArgumentParser(description="Run PDF diff review web viewer")
    parser.add_argument("--diff", type=str, default=str(DEFAULT_DIFF_PATH), help="Diff JSON file to load at startup")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="SQLite state DB path")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload mode")
    args = parser.parse_args()

    os.environ[ENV_DIFF_PATH] = args.diff
    os.environ[ENV_DB_PATH] = args.db

    if args.no_reload:
        app_instance = create_app(diff_path=Path(args.diff), db_path=Path(args.db))
        uvicorn.run(app_instance, host=args.host, port=args.port, reload=False)
    else:
        uvicorn.run(
            "viewer_backend:build_app_from_env",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )


if __name__ == "__main__":
    main()
