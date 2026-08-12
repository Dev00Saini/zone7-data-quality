"""
Runs every query in sql/data_quality_analysis.sql against the local
zone7.db and prints the results, so you can see the actual numbers
behind docs/data_quality_findings.md.

Run from the scripts/ folder:
    python run_analysis.py
"""

import sqlite3
import re

DB_PATH = "../data/processed/zone7.db"
SQL_PATH = "../sql/data_quality_analysis.sql"

# Labels matching the numbered comments in the .sql file
LABELS = [
    "0. Station identity check",
    "1. Duplicate timestamps",
    "2. Completeness by station",
    "3. All individual gaps (this one is long — only preview printed)",
    "4. Gap summary by station",
    "5. Metric-level nulls by station",
]


def split_numbered_queries(sql_text):
    """Split the .sql file into queries based on the numbered comment
    headers ("-- 0.", "-- 1.", etc), skipping section 6 (reference only,
    not a runnable query)."""
    parts = re.split(r"\n-- \d+\. ", sql_text)
    queries = []
    for part in parts[1:]:
        lines = part.splitlines()
        # First line is the tail of the "-- N. <Title>" header line the
        # split consumed the "-- " prefix from — it's still just a title,
        # so drop it before scanning for further leading comment lines.
        lines = lines[1:]
        sql_lines = []
        in_comment_block = True
        for line in lines:
            if in_comment_block and line.strip().startswith("--"):
                continue
            in_comment_block = False
            sql_lines.append(line)
        query = "\n".join(sql_lines).strip()
        if query:
            queries.append(query)
    return queries[:6]  # sections 0-5; section 6 is reference-only text


def print_table(rows, col_names, max_rows=15):
    if not rows:
        print("  (no rows)")
        return
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows[:max_rows])) for i, c in enumerate(col_names)]
    header = "  ".join(str(c).ljust(w) for c, w in zip(col_names, widths))
    print(" ", header)
    print(" ", "-" * len(header))
    for row in rows[:max_rows]:
        print(" ", "  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    if len(rows) > max_rows:
        print(f"  ... ({len(rows) - max_rows} more rows)")


def main():
    conn = sqlite3.connect(DB_PATH)
    with open(SQL_PATH, encoding="utf-8") as f:
        sql_text = f.read()

    queries = split_numbered_queries(sql_text)

    for label, query in zip(LABELS, queries):
        print(f"\n{'=' * 70}")
        print(label)
        print("=" * 70)
        try:
            cur = conn.execute(query)
            col_names = [d[0] for d in cur.description]
            rows = cur.fetchall()
            print(f"({len(rows)} rows)")
            print_table(rows, col_names)
        except Exception as e:
            print(f"QUERY FAILED: {e}")
            print("Query text was:")
            print(query[:500])

    conn.close()


if __name__ == "__main__":
    main()