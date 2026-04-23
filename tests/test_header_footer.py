from extractor import HeaderFooterDetector
from models import ExtractedLine, HeuristicConfig


def _line(text: str, page: int, y0: float, y1: float) -> ExtractedLine:
    return ExtractedLine(text=text, page=page, x0=0, y0=y0, x1=100, y1=y1)


def test_repeated_footer_detected() -> None:
    cfg = HeuristicConfig(min_header_footer_repeat_ratio=0.6)
    detector = HeaderFooterDetector(cfg)

    page_lines = {
        1: [_line("Policy Update 2024", 1, 760, 780)],
        2: [_line("Policy Update 2025", 2, 760, 780)],
        3: [_line("Policy Update 2026", 3, 760, 780)],
    }
    page_heights = {1: 800.0, 2: 800.0, 3: 800.0}

    removable = detector.detect(page_lines, page_heights)
    assert (1, "Policy Update 2024") in removable
    assert (2, "Policy Update 2025") in removable
    assert (3, "Policy Update 2026") in removable


def test_page_number_detected_as_footer() -> None:
    cfg = HeuristicConfig(min_header_footer_repeat_ratio=0.95)
    detector = HeaderFooterDetector(cfg)
    page_lines = {
        1: [_line("1", 1, 760, 780)],
        2: [_line("2", 2, 760, 780)],
    }
    page_heights = {1: 800.0, 2: 800.0}
    removable = detector.detect(page_lines, page_heights)
    assert (1, "1") in removable
    assert (2, "2") in removable


def test_running_title_with_page_number_detected_fuzzily() -> None:
    cfg = HeuristicConfig(min_header_footer_repeat_ratio=0.8)
    detector = HeaderFooterDetector(cfg)
    page_lines = {
        1: [_line("Consultation on the Principles for the management of credit risk 11", 1, 760, 780)],
        2: [_line("Consultation on the  Principles for management of credit risk 12", 2, 760, 780)],
        3: [_line("Consultation on Principles for the management of credit risk 13", 3, 760, 780)],
    }
    page_heights = {1: 800.0, 2: 800.0, 3: 800.0}
    removable = detector.detect(page_lines, page_heights)
    assert (1, "Consultation on the Principles for the management of credit risk 11") in removable
    assert (2, "Consultation on the Principles for management of credit risk 12") in removable
    assert (3, "Consultation on Principles for the management of credit risk 13") in removable
