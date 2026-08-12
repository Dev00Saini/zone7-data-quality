"""
Run the data quality SQL queries against zone7.db and print/export
the results. Run this after ingest.py has populated raw_readings.
"""

import sqlite3
import pandas as pd

DB_PATH = "../data/processed/zone7.db"
SQL_PATH = "../sql/data_quality_analysis.sql"


def split_queries(sql_text):
    """Split the .sql file into individual named queries by leading
    comment blocks, skipping section 6 (reference/documentation only)."""
    blocks = sql_text.split("\n\n\n")
    queries = []
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip() and not l.strip().startswith("--")]
        if lines:
            queries.append("\n".join(lines))
    return queries


def main():
    conn = sqlite3.connect(DB_PATH)
    with open(SQL_PATH) as f:
        sql_text = f.read()

    queries = split_queries(sql_text)
    labels = [
        "1_duplicates",
        "2_completeness_by_station",
        "3_all_gaps",
        "4_gap_summary_by_station",
        "5_out_of_range_values",
    ]

    for label, query in zip(labels, queries):
        try:
            df = pd.read_sql_query(query, conn)
            print(f"\n=== {label} ===")
            print(df.head(20))
            df.to_csv(f"../data/processed/{label}.csv", index=False)
        except Exception as e:
            print(f"\n=== {label} FAILED: {e} ===")

    conn.close()


if __name__ == "__main__":
    main()
