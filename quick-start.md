# Quick Start

Run from project root (`/home/alpha/pdf`).

## 1) Activate environment

```bash
source env/bin/activate
```

## 2) Generate section-wise diff JSON

```bash
python cli.py diff bcbs75.pdf d595.pdf --output bcb765_d595_diff.json --mode primary-semantic --dump-intermediate
```

## 3) Classify diffs (editorial/slight/significant)

```bash
python classify_report.py bcb765_d595_diff.json --output bcb765_d595_classified.json
```

## 4) Export CSV report

```bash
python export_table.py bcb765_d595_diff.json --csv bcb765_d595_table.csv
```

## 5) Optional: launch web viewer

```bash
python viewer_backend.py --diff bcb765_d595_diff.json
```

Open:

- `http://127.0.0.1:8000`

## Common variants

### Use different source PDFs

```bash
python cli.py diff old.pdf new.pdf --output my_diff.json --mode primary-semantic --dump-intermediate
python classify_report.py my_diff.json --output my_diff_classified.json
python export_table.py my_diff.json --csv my_diff_table.csv
python viewer_backend.py --diff my_diff.json
```
