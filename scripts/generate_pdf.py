#!/usr/bin/env python3
"""Converts PROJECT_EXPLANATION.md into a beautifully styled HTML document
and uses headless Chromium to compile PROJECT_EXPLANATION.pdf.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "docs" / "explanation" / "PROJECT_EXPLANATION.md"
HTML_PATH = ROOT / "docs" / "explanation" / "PROJECT_EXPLANATION.html"
PDF_PATH = ROOT / "docs" / "explanation" / "PROJECT_EXPLANATION.pdf"


def md_to_html(md_text):
    html_lines = []
    in_code = False
    code_lang = ""
    code_buf = []
    in_table = False
    table_buf = []
    in_ul = False
    in_ol = False

    def process_inline(text):
        # Escape HTML entities
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # Math blocks (KaTeX / LaTeX style)
        text = re.sub(r"\$\$([^\$]+)\$\$", r'<span class="math-display">\1</span>', text)
        text = re.sub(r"\$([^\$]+)\$", r'<span class="math-inline">\1</span>', text)
        # Code snippets
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        # Bold & Italic
        text = re.sub(r"\*\*\*([^\*]+)\*\*\*", r"<strong><em>\1</em></strong>", text)
        text = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*([^\*]+)\*", r"<em>\1</em>", text)
        # Markdown links
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        return text

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    def flush_table():
        nonlocal in_table, table_buf
        if not table_buf:
            return
        out = ['<div class="table-wrapper"><table>']
        header_done = False
        for row in table_buf:
            raw_cells = [c.strip() for c in row.strip().strip("|").split("|")]
            # Check if separator row
            if all(re.match(r"^:?-{2,}:?$", c) for c in raw_cells if c):
                header_done = True
                continue
            tag = "th" if not header_done else "td"
            cells_html = "".join(f"<{tag}>{process_inline(c)}</{tag}>" for c in raw_cells)
            row_html = f"<tr>{cells_html}</tr>"
            if not header_done:
                out.append(f"<thead>{row_html}</thead><tbody>")
            else:
                out.append(row_html)
        if header_done:
            out.append("</tbody>")
        out.append("</table></div>")
        html_lines.append("\n".join(out))
        table_buf = []
        in_table = False

    lines = md_text.splitlines()
    for line in lines:
        stripped = line.strip()

        # Code block boundaries
        if stripped.startswith("```"):
            if in_code:
                in_code = False
                code_raw = "\n".join(code_buf).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(f'<pre class="code-block language-{code_lang}"><code>{code_raw}</code></pre>')
                code_buf = []
            else:
                close_lists()
                if in_table:
                    flush_table()
                in_code = True
                code_lang = stripped[3:].strip()
            continue

        if in_code:
            code_buf.append(line)
            continue

        # Markdown tables
        if stripped.startswith("|") and stripped.endswith("|"):
            close_lists()
            if not in_table:
                in_table = True
                table_buf = []
            table_buf.append(line)
            continue
        elif in_table:
            flush_table()

        # Headings
        if line.startswith("#"):
            close_lists()
            level = len(line.split()[0])
            title = line.lstrip("#").strip()
            anchor_id = re.sub(r"[^a-zA-Z0-9_-]", "", title.lower().replace(" ", "-"))
            html_lines.append(f'<h{level} id="{anchor_id}">{process_inline(title)}</h{level}>')
            continue

        # Blockquotes
        if line.startswith(">"):
            close_lists()
            quote_text = line.lstrip(">").strip()
            html_lines.append(f"<blockquote><p>{process_inline(quote_text)}</p></blockquote>")
            continue

        # Unordered list items
        if line.startswith("- ") or line.startswith("* "):
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            content = line[2:].strip()
            html_lines.append(f"<li>{process_inline(content)}</li>")
            continue

        # Ordered list items
        if re.match(r"^\d+\.\s", line):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            content = re.sub(r"^\d+\.\s", "", line).strip()
            html_lines.append(f"<li>{process_inline(content)}</li>")
            continue

        close_lists()

        # Horizontal rule
        if stripped == "---":
            html_lines.append("<hr/>")
            continue

        # Regular paragraph
        if stripped:
            html_lines.append(f"<p>{process_inline(line)}</p>")
        else:
            html_lines.append('<div class="spacer"></div>')

    close_lists()
    if in_table:
        flush_table()

    return "\n".join(html_lines)


def build_html_document(body_html):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Codebase Onboarding & Architecture Guide: futex-lab</title>
<style>
  @page {{
    size: A4;
    margin: 18mm 14mm 18mm 14mm;
    @bottom-right {{
      content: counter(page);
      font-size: 8pt;
      color: #718096;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
  }}

  * {{
    box-sizing: border-box;
  }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 9pt;
    line-height: 1.55;
    color: #1a202c;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
  }}

  h1, h2, h3, h4, h5, h6 {{
    color: #0f172a;
    font-weight: 700;
    line-height: 1.25;
    margin-top: 1.4em;
    margin-bottom: 0.5em;
    page-break-after: avoid;
    break-after: avoid;
  }}

  h1 {{
    font-size: 18pt;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 6px;
    margin-top: 0;
    color: #1e3a8a;
  }}

  h2 {{
    font-size: 13pt;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 4px;
    margin-top: 1.8em;
    color: #1e40af;
  }}

  h3 {{
    font-size: 11pt;
    margin-top: 1.3em;
    color: #1e293b;
  }}

  h4 {{
    font-size: 9.5pt;
    font-weight: 600;
    color: #334155;
  }}

  p {{
    margin-top: 0;
    margin-bottom: 0.7em;
  }}

  a {{
    color: #2563eb;
    text-decoration: none;
  }}
  a:hover {{
    text-decoration: underline;
  }}

  code {{
    font-family: "JetBrains Mono", "Fira Code", Menlo, Monaco, Consolas, monospace;
    font-size: 8pt;
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 1px 4px;
    border-radius: 3px;
    border: 1px solid #e2e8f0;
  }}

  pre.code-block {{
    font-family: "JetBrains Mono", "Fira Code", Menlo, Monaco, Consolas, monospace;
    font-size: 7.5pt;
    line-height: 1.4;
    background-color: #f8fafc;
    color: #0f172a;
    padding: 10px 12px;
    border-radius: 6px;
    border: 1px solid #cbd5e1;
    overflow-x: auto;
    margin: 0.8em 0;
    page-break-inside: avoid;
    break-inside: avoid;
    white-space: pre-wrap;
    word-break: break-word;
  }}

  pre.code-block code {{
    background: none;
    padding: 0;
    border: none;
    color: inherit;
    font-size: inherit;
  }}

  blockquote {{
    border-left: 3.5px solid #3b82f6;
    background-color: #eff6ff;
    color: #1e3a8a;
    margin: 0.8em 0;
    padding: 8px 14px;
    border-radius: 0 4px 4px 0;
    font-size: 8.5pt;
    page-break-inside: avoid;
    break-inside: avoid;
  }}

  blockquote p {{
    margin: 0;
  }}

  hr {{
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 1.5em 0;
  }}

  .table-wrapper {{
    width: 100%;
    margin: 1em 0;
    page-break-inside: avoid;
    break-inside: avoid;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 7.5pt;
    line-height: 1.35;
  }}

  th, td {{
    border: 1px solid #cbd5e1;
    padding: 4px 7px;
    text-align: left;
    vertical-align: top;
  }}

  th {{
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 600;
  }}

  tr:nth-child(even) td {{
    background-color: #f8fafc;
  }}

  ul, ol {{
    margin-top: 0;
    margin-bottom: 0.8em;
    padding-left: 20px;
  }}

  li {{
    margin-bottom: 0.3em;
  }}

  .math-inline {{
    font-family: "Cambria Math", "Latin Modern Math", serif;
    font-style: italic;
  }}

  .math-display {{
    display: block;
    text-align: center;
    font-family: "Cambria Math", "Latin Modern Math", serif;
    font-size: 10pt;
    margin: 0.6em 0;
  }}

  .spacer {{
    height: 4px;
  }}

  .header-badge {{
    display: inline-block;
    padding: 2px 8px;
    font-size: 7.5pt;
    font-weight: 600;
    background-color: #dbeafe;
    color: #1e40af;
    border-radius: 4px;
    margin-bottom: 8px;
  }}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


def main():
    if not MD_PATH.exists():
        sys.exit(f"Error: {MD_PATH} not found.")

    print(f"Reading {MD_PATH.name}...")
    md_content = MD_PATH.read_text(encoding="utf-8")

    print("Converting Markdown to rich HTML...")
    body_html = md_to_html(md_content)
    full_html = build_html_document(body_html)

    HTML_PATH.write_text(full_html, encoding="utf-8")
    print(f"Wrote {HTML_PATH.relative_to(ROOT)} ({len(full_html)} bytes)")

    print(f"Compiling PDF via headless Chromium to {PDF_PATH.name}...")
    cmd = [
        "chromium",
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--user-data-dir=/tmp/chromium-data",
        f"--print-to-pdf={PDF_PATH}",
        "--print-to-pdf-no-header",
        str(HTML_PATH),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Chromium error stderr:\n", res.stderr)
        sys.exit(f"Chromium exited with code {res.returncode}")

    if PDF_PATH.exists():
        size_kb = PDF_PATH.stat().st_size / 1024
        print(f"Successfully generated {PDF_PATH.relative_to(ROOT)} ({size_kb:.1f} KB)")
    else:
        sys.exit("Error: PDF output file was not created.")


if __name__ == "__main__":
    main()
