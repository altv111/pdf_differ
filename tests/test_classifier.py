from models import ExtractedLine, HeuristicConfig
from sectionizer import LineClassifier


classifier = LineClassifier()


def _line(text: str) -> ExtractedLine:
    return ExtractedLine(text=text, page=1, x0=0, y0=0, x1=10, y1=10)


def test_major_heading_classification() -> None:
    labeled = classifier.classify(_line("I. Introduction"))
    assert labeled.label == "major_heading"


def test_named_numbered_heading_classification() -> None:
    labeled = classifier.classify(_line("Principle 7: This is a test"))
    assert labeled.label == "named_numbered_heading"


def test_numeric_heading_classification() -> None:
    labeled = classifier.classify(_line("1. How to report risk?"))
    assert labeled.label == "numeric_heading"


def test_letter_heading_classification() -> None:
    labeled = classifier.classify(_line("a. types of risk"))
    assert labeled.label == "letter_heading"


def test_reference_line_classification() -> None:
    labeled = classifier.classify(_line("References"))
    assert labeled.label == "reference_line"


def test_toc_entry_classification() -> None:
    labeled = classifier.classify(_line("II. Establishing an appropriate credit risk environment .......... 5"))
    assert labeled.label == "reference_line"
