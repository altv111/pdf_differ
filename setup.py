from pathlib import Path

from setuptools import setup

BASE_DIR = Path(__file__).parent
README = (BASE_DIR / "README.md").read_text(encoding="utf-8")

setup(
    name="pdf-semantic-differ",
    version="0.1.0",
    description="Semantic PDF section extraction and section-wise diff tool",
    long_description=README,
    long_description_content_type="text/markdown",
    python_requires=">=3.11",
    py_modules=[
        "cli",
        "models",
        "utils",
        "extractor",
        "unstructured_extractor",
        "sectionizer",
        "matcher",
        "differ",
        "classifier",
        "llm_client",
        "classify_report",
        "compare_extractors",
        "export_table",
        "import_classifications",
        "viewer_backend",
    ],
    install_requires=[
        "PyMuPDF>=1.24.0",
        "rapidfuzz>=3.9.0",
        "fastapi>=0.136.0",
        "uvicorn>=0.46.0",
        "jinja2>=3.1.0",
    ],
    extras_require={
        "dev": ["pytest>=8.0.0"],
        "unstructured": ["unstructured[pdf]>=0.15.0"],
    },
    entry_points={
        "console_scripts": [
            "pdf-semantic-diff=cli:main",
            "pdf-diff-viewer=viewer_backend:main",
            "pdf-compare-extractors=compare_extractors:main",
        ]
    },
    include_package_data=True,
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
