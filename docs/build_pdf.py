"""Render docs/explanation.md to explanation.pdf (repo root).

Needs: pip install markdown playwright && playwright install chromium
Run:   python docs/build_pdf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "explanation.md"
OUT = ROOT / "explanation.pdf"

CSS = """
@page { size: A4; margin: 13mm 14mm 13mm 14mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 8.6pt; line-height: 1.36; color: #0f172a; }
h1 { font-size: 14pt; margin: 0 0 6px; }
h2 { font-size: 10.5pt; margin: 9px 0 3px; color: #0f172a; border-bottom: 1px solid #cbd5e1; padding-bottom: 1px; }
p { margin: 3px 0 4px; text-align: justify; }
ul { margin: 2px 0 4px 0; padding-left: 15px; }
li { margin: 1px 0; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 6px; font-size: 8pt; }
th, td { border: 1px solid #cbd5e1; padding: 2px 5px; vertical-align: top; text-align: left; }
th { background: #f1f5f9; }
code { font-family: Menlo, Consolas, monospace; font-size: 7.8pt; background: #f1f5f9; padding: 0 2px; border-radius: 2px; }
.diagram { margin: 2px 0 4px; }
.diagram svg { width: 100%; height: auto; }
"""


def main() -> int:
    body = markdown.markdown(SRC.read_text(encoding="utf-8"), extensions=["tables", "md_in_html", "sane_lists"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(OUT), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
