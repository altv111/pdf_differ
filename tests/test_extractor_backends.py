from models import HeuristicConfig
from extractor import extract_pdf_lines


def test_extract_pdf_lines_rejects_unknown_backend() -> None:
    cfg = HeuristicConfig()
    try:
        extract_pdf_lines("dummy.pdf", cfg, extractor_backend="unknown")
    except ValueError as exc:
        assert "Unsupported extractor backend" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported backend")
