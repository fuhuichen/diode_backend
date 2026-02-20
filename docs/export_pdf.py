#!/usr/bin/env python3
"""Export markdown documents to styled PDF files."""
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

CSS = """
@page {
    size: A4;
    margin: 2cm 2.5cm;
    @bottom-center { content: counter(page) " / " counter(pages); font-size: 9px; color: #999; }
}
body {
    font-family: -apple-system, "Noto Sans TC", "Microsoft JhengHei", sans-serif;
    font-size: 13px;
    line-height: 1.7;
    color: #1a1a1a;
}
h1 { font-size: 24px; color: #312e81; border-bottom: 2px solid #6366f1; padding-bottom: 8px; margin-top: 32px; }
h2 { font-size: 18px; color: #4338ca; margin-top: 28px; }
h3 { font-size: 15px; color: #4f46e5; margin-top: 20px; }
h4 { font-size: 13px; color: #6366f1; margin-top: 16px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 12px; }
th { background: #f1f5f9; color: #334155; font-weight: 600; text-align: left; padding: 8px 10px; border: 1px solid #e2e8f0; }
td { padding: 6px 10px; border: 1px solid #e2e8f0; }
tr:nth-child(even) td { background: #f8fafc; }
code { background: #f1f5f9; padding: 1px 5px; border-radius: 3px; font-size: 11px; font-family: "SF Mono", Menlo, monospace; }
pre { background: #1e293b; color: #e2e8f0; padding: 14px 18px; border-radius: 6px; font-size: 11px; line-height: 1.5; overflow-x: auto; white-space: pre-wrap; }
pre code { background: none; color: inherit; padding: 0; }
blockquote { border-left: 3px solid #6366f1; margin: 12px 0; padding: 8px 16px; background: #eef2ff; color: #3730a3; }
blockquote p { margin: 4px 0; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }
strong { color: #1e293b; }
"""

def md_to_pdf(md_path: str, pdf_path: str):
    md_text = Path(md_path).read_text(encoding="utf-8")
    html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "nl2br"])
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{html_body}</body></html>"""
    HTML(string=full_html).write_pdf(pdf_path)
    print(f"  {pdf_path}")


if __name__ == "__main__":
    docs_dir = Path(__file__).parent
    files = sys.argv[1:] if len(sys.argv) > 1 else [
        str(docs_dir / "business-plan.md"),
        str(docs_dir / "diode-cloud-proposal.md"),
    ]
    print("Exporting PDFs:")
    for f in files:
        p = Path(f)
        if p.exists() and p.suffix == ".md":
            md_to_pdf(str(p), str(p.with_suffix(".pdf")))
    print("Done.")
