# PDF Semantic Section Extractor and Differ

Production-oriented Python toolchain to:

1. Extract robust semantic sections from one PDF into JSON
2. Diff two PDFs section-wise into a structured JSON report

The design explicitly avoids naive raw-text diffing by separating concerns into extraction, cleanup, sectionization, matching, and diff generation.

## Features

- Layout-aware extraction with PyMuPDF span coordinates
- Automatic repeated header/footer detection using top/bottom page bands
- Manual header/footer override patterns
- Line classifier with labels:
  - `major_heading`
  - `named_numbered_heading`
  - `numeric_heading`
  - `letter_heading`
  - `body`
  - `footer_or_header`
  - `footnote_label`
  - `reference_line`
- Section state machine with hierarchy support and preamble capture
- Two modes:
  - `primary-semantic` (default): named headings (e.g. `Principle 7`) are primary; numeric lines can be children
  - `numeric-primary`: numeric headings (e.g. `1.`) can become primary sections
- Weighted fuzzy section matching (`rapidfuzz`)
- Section-wise structured diff + unified diff
- Optional change-classification hook (no external LLM calls)
- Testable modular architecture

## Project Layout

- `models.py`: dataclasses for configs, lines, sections, matches, reports
- `extractor.py`: PDF extraction + header/footer detection
- `sectionizer.py`: line classification + section-building state machine
- `matcher.py`: section alignment across two PDFs
- `differ.py`: structured/unified section diffs + summary
- `cli.py`: command line interface
- `utils.py`: normalization/logging/JSON helpers
- `tests/`: unit tests

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## CLI Usage

### 1) Extract sections from one PDF

```bash
python cli.py extract input.pdf --output sections.json
```

### 2) Diff two PDFs section-wise

```bash
python cli.py diff old.pdf new.pdf --output diff.json
```

### Optional flags

- `--mode primary-semantic|numeric-primary`
- `--header-pattern "..."` (repeatable)
- `--footer-pattern "..."` (repeatable)
- `--debug`
- `--dump-intermediate`

Examples:

```bash
python cli.py extract d591.pdf --output d591_sections.json --dump-intermediate
python cli.py diff d591.pdf d595.pdf --output d591_d595_diff.json --mode primary-semantic --debug
```

## Tabular Export (CSV / Excel)

You can export an existing diff JSON into a 7-column table:

1. page number in file A
2. section number in file A
3. text in file A
4. page number in file B
5. section number in file B
6. text in file B
7. diff score

Exporter uses `semantic_text_a` / `semantic_text_b` when available, and falls back to raw section lines otherwise.

```bash
python export_table.py bcb765_d595_diff.json --csv bcb765_d595_table.csv
python export_table.py bcb765_d595_diff.json --excel bcb765_d595_table.xlsx
```

Excel export requires `openpyxl`:

```bash
pip install openpyxl
```

## Hybrid Change Classifier

The project includes a separate, production-oriented hybrid classification module:

- [classifier.py](/home/alpha/pdf/classifier.py)
- [llm_client.py](/home/alpha/pdf/llm_client.py)

It classifies section diffs as:

- `editorial`
- `slight`
- `significant`

### Inputs

Per section payload:

- `section_title`
- `before_text`
- `after_text`
- optional metadata (`diff_score`, etc.)

### Outputs (per section)

- `features`
- `rule_classification`
- `llm_classification` (stubbed)
- `hard_signal_flags`
- `disagreement_flag`
- `override_candidate`
- `final_classification` (currently follows LLM label)

### Example

```python
import json
from pathlib import Path
from classifier import classify_diff_report

report = json.loads(Path("bcb765_d595_diff.json").read_text(encoding="utf-8"))
classified = classify_diff_report(report)
print(classified["summary"])
```

### CLI wrapper

```bash
python classify_report.py bcb765_d595_diff.json --output bcb765_d595_classified.json
```

Viewer bridge behavior:

- If `*_classified.json` exists next to the active diff JSON, the viewer auto-loads those labels.
- If classified output is missing, viewer continues normally (no failure).
- Optional durable import into `viewer_state.db`:

```bash
python import_classifications.py bcb765_d595_diff.json bcb765_d595_classified.json --db viewer_state.db
```

### `.env` support for `llm_client.py`

`llm_client.py` automatically loads a top-level `.env` file in the project root.
Copy `.env.example` to `.env` and set values as needed:

```bash
cp .env.example .env
```

Supported keys:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `LLM_ENABLE_REAL_CALLS` (`true`/`false`, default `false`)
- `OPENAI_API_BASE` (optional, default `https://api.openai.com/v1`)
- `LLM_TIMEOUT_SECONDS` (optional, default `25`)
- `LLM_RETRIES` (optional, default `2`)

### Real OpenAI mode (optional)

By default, classifier uses a deterministic stub.  
To enable real OpenAI classification calls in `llm_client.py`, set:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.4
OPENAI_API_KEY=...
LLM_ENABLE_REAL_CALLS=true
```

If API calls fail, classification safely falls back to stub output so pipeline execution does not break.

## Web Diff Viewer

A lightweight web viewer is included for side-by-side visual diff review.

### Run

```bash
source env/bin/activate
python viewer_backend.py
python viewer_backend.py --diff bcb765_d595_diff.json --port 8001
```

Then open `http://127.0.0.1:8000`.

### Viewer features

- Summary cards for modified/added/removed/unchanged
- Diff-report dropdown (top bar) to switch between available `*.json` reports
- CSV dropdown + download button (top bar) to fetch generated `*.csv` exports
- Filterable/searchable section list
- Side-by-side diff panes
- Section-context rendering (each pane shows full `title + section body`)
- Color-coded changes:
  - additions in green
  - deletions in red
  - replacements highlighted inline (word-level)
- Optional title-diff display
- `renumbering_only` status for heading-label changes with unchanged body
- Low-confidence match flag surfaced in UI for manual review triage
- Human review state capture (`approved/rejected/needs_review`) with note
- Manual change classification capture (`editorial/slight/significant`)

Review and classification updates are stored in local SQLite `viewer_state.db`.

### API endpoints (phase-2 ready)

- `GET /api/diffs`
- `GET /api/diffs/{diff_id}`
- `POST /api/diffs/{diff_id}/human-review`
- `POST /api/diffs/{diff_id}/classify`
- `POST /api/reload`

## Output Schemas

### Extraction

```json
{
  "document": "input.pdf",
  "sections": [
    {
      "section_id": "...",
      "parent_id": null,
      "level": 1,
      "anchor_type": "named_numbered_heading",
      "title": "Principle 5: ...",
      "title_normalized": "principle 5 ...",
      "start_page": 3,
      "end_page": 5,
      "body": "...",
      "body_lines": ["..."],
      "children": [],
      "metadata": {}
    }
  ]
}
```

### Diff

```json
{
  "pdf_a": "old.pdf",
  "pdf_b": "new.pdf",
  "summary": {
    "total_sections_a": 0,
    "total_sections_b": 0,
    "matched": 0,
    "added": 0,
    "removed": 0,
    "modified": 0,
    "unchanged": 0
  },
  "diffs": [
    {
      "status": "modified",
      "section_id_a": "...",
      "section_id_b": "...",
      "parent_section_id_a": null,
      "parent_section_id_b": null,
      "title_a": "...",
      "title_b": "...",
      "page_no_in_a": 4,
      "page_no_in_b": 4,
      "match_score": 0.91,
      "match_confidence": "matched",
      "low_confidence": false,
      "anchor_type": "named_numbered_heading",
      "semantic_status": "modified",
      "semantic_text_a": "...",
      "semantic_text_b": "...",
      "semantic_structured_diff": [],
      "semantic_unified_diff": "--- ...",
      "title_diff": {
        "status": "modified",
        "structured_diff": [
          {
            "tag": "replace",
            "lines_a": ["I. Intro ................................................................ 4"],
            "lines_b": ["I. Intro"]
          }
        ],
        "unified_diff": "--- ..."
      },
      "structured_diff": [
        {
          "tag": "replace",
          "lines_a": ["old text"],
          "lines_b": ["new text"]
        }
      ],
      "unified_diff": "--- ...",
      "change_classification": null
    }
  ]
}
```

`semantic_*` fields are wrap-insensitive canonical diffs intended for downstream consumers (UI, CSV, future services).  
Raw `structured_diff` / `unified_diff` are retained for traceability to extraction output.

## Heuristic Notes

- Header/footer detection normalizes candidates by lowercasing, collapsing whitespace, and replacing standalone numbers with `<num>`.
- Repeated normalized text in top/bottom bands over a configurable ratio is removed.
- Page-number-only artifacts are removed.
- Sectionization relies on heading pattern classes and mode-specific primary heading decisions.
- In `primary-semantic`, numeric lines can be retained as child items.

## Change Classification Hook

`SectionDiffer` accepts a callable:

```python
def classify_change(old_text: str, new_text: str) -> str | None:
    return "editorial"
```

Pass it as `SectionDiffer(change_classifier=classify_change)`.

## Testing

```bash
pytest -q
```

Test coverage includes:

- heading pattern classification
- repeated header/footer removal behavior
- section boundary logic (mode-dependent)
- matching logic
- diff generation
