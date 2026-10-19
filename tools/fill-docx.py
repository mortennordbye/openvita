#!/usr/bin/env python3
"""Fill the empty table cells of a customer's Word form without changing anything else.

Tenders often come with a .docx you must return in the same format (a competence
matrix, a requirements table). This tool only writes text into cells that are empty in the
original. Every other byte of the file stays as it was: styles, headers, the other zip entries
and the XML around the filled cells.

  fill-docx.py extract FORM.docx ANSWERS.json   list the tables, one entry per empty cell
  fill-docx.py fill    FORM.docx ANSWERS.json OUT.docx

ANSWERS.json holds one entry per row with at least one empty cell. "row" is the row's text, so a
human (or Claude) can see what is being answered, and it is checked again on fill so answers
never land in the wrong row. "fill" maps a cell index to the text for it. A newline in the text
starts a new paragraph in the cell, formatted like the cell's empty paragraph.

extract keeps the answers already written when ANSWERS.json exists.
"""
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

DOC = "word/document.xml"


def spans(xml, tag, start=0, end=None):
    """(start, end) of each top-level <w:tag> element in xml[start:end], nesting aware."""
    end = len(xml) if end is None else end
    pat = re.compile(rf"<(/?)w:{tag}(?=[\s>/])[^>]*?(/?)>")
    depth, open_at = 0, None
    for m in pat.finditer(xml, start, end):
        closing, selfclosing = m.group(1), m.group(2)
        if selfclosing:
            if depth == 0:
                yield m.start(), m.end()
        elif not closing:
            if depth == 0:
                open_at = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                yield open_at, m.end()


def text(fragment):
    return "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", fragment)).replace("\xa0", " ").strip()


def cells(xml):
    """Yield (table, row, cell, cell_start, cell_end) for every cell of every top-level table."""
    for t, (ts, te) in enumerate(spans(xml, "tbl")):
        for r, (rs, re_) in enumerate(spans(xml, "tr", ts, te)):
            for c, (cs, ce) in enumerate(spans(xml, "tc", rs, re_)):
                yield t, r, c, cs, ce


def rows(xml):
    """Rows with their cells: {(table, row): [(cell, text, fillable)]}."""
    out = {}
    for t, r, c, cs, ce in cells(xml):
        cell = xml[cs:ce]
        if "<w:tbl" in cell:
            sys.exit(f"table {t} row {r} cell {c} holds a nested table, which this tool does not handle")
        merged = re.search(r'<w:vMerge(?![^>]*w:val="restart")', cell) is not None
        fillable = not text(cell) and not merged and "<w:p" in cell and "<w:drawing" not in cell
        out.setdefault((t, r), []).append((c, text(cell), fillable))
    return out


def row_label(cs):
    return " | ".join(t for _, t, _ in cs if t)


def extract(form, answers_path):
    xml = zipfile.ZipFile(form).read(DOC).decode("utf-8")
    old = {}
    if answers_path.exists():
        for e in json.loads(answers_path.read_text()).get("rows", []):
            old[(e["table"], e["row"])] = e
    entries = []
    for (t, r), cs in rows(xml).items():
        empty = [c for c, _, f in cs if f]
        label = row_label(cs)
        if not empty or not label:
            continue
        prev = old.get((t, r), {})
        fill = {str(c): prev.get("fill", {}).get(str(c), "") for c in empty}
        entries.append({"table": t, "row": r, "text": label,
                        "cells": [tx for _, tx, _ in cs], "fill": fill})
    answers_path.write_text(json.dumps({"form": form.name, "rows": entries},
                                       ensure_ascii=False, indent=2) + "\n")
    print(f"{answers_path}: {len(entries)} rows with empty cells")


RUN_RPR_DROP = re.compile(r"<w:(ins|del|moveFrom|moveTo|rPrChange)\b[^>]*?(/>|>.*?</w:\1>)", re.S)


def filled_cell(cell, value):
    """The cell with value written into its first empty paragraph."""
    ps = list(spans(cell, "p"))
    target = next(((s, e) for s, e in ps if not text(cell[s:e])), None)
    if target is None:
        return None
    s, e = target
    p = cell[s:e]
    ppr = re.search(r"<w:pPr>.*?</w:pPr>", p, re.S)
    ppr = ppr.group(0) if ppr else ""
    rpr = re.search(r"<w:rPr>.*?</w:rPr>", ppr, re.S)
    rpr = RUN_RPR_DROP.sub("", rpr.group(0)) if rpr else ""
    open_tag = re.match(r"<w:p(?=[\s>])[^>]*>", p).group(0)
    bare_open = re.sub(r'\s+w14:(paraId|textId)="[^"]*"', "", open_tag)
    paras = []
    for i, line in enumerate(value.split("\n")):
        run = f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line)}</w:t></w:r>' if line else ""
        paras.append(f"{open_tag if i == 0 else bare_open}{ppr}{run}</w:p>")
    return cell[:s] + "".join(paras) + cell[e:]


def fill(form, answers_path, out):
    zin = zipfile.ZipFile(form)
    xml = zin.read(DOC).decode("utf-8")
    answers = json.loads(answers_path.read_text())
    have = rows(xml)
    todo = {}
    for e in answers["rows"]:
        key = (e["table"], e["row"])
        if key not in have or row_label(have[key]) != e["text"]:
            sys.exit(f"table {e['table']} row {e['row']} no longer reads {e['text']!r}: wrong form? "
                     f"Run extract again.")
        for c, v in e["fill"].items():
            if v.strip():
                todo[(e["table"], e["row"], int(c))] = v.strip()
    # Edit from the end so earlier offsets stay valid.
    done = 0
    for t, r, c, cs, ce in reversed(list(cells(xml))):
        v = todo.pop((t, r, c), None)
        if v is None:
            continue
        new = filled_cell(xml[cs:ce], v)
        if new is None:
            sys.exit(f"table {t} row {r} cell {c} is not empty in the form")
        xml = xml[:cs] + new + xml[ce:]
        done += 1
    if todo:
        sys.exit(f"cells not found: {sorted(todo)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            data = xml.encode("utf-8") if info.filename == DOC else zin.read(info)
            zout.writestr(info, data, compress_type=info.compress_type)
    print(f"{out}: {done} cells filled")


def main(argv):
    if len(argv) == 4 and argv[1] == "extract":
        extract(Path(argv[2]), Path(argv[3]))
    elif len(argv) == 5 and argv[1] == "fill":
        fill(Path(argv[2]), Path(argv[3]), Path(argv[4]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
