"""Build local crosswalks from completed source snapshots. No Django writes."""
import argparse
import csv
import gzip
import json
from pathlib import Path

IMDB_BASICS = ("tconst", "titleType", "primaryTitle", "originalTitle",
               "isAdult", "startYear", "endYear", "runtimeMinutes", "genres")


def tvmaze_imdb(tvmaze_path, imdb_path, output):
    output.mkdir(parents=True, exist_ok=True)
    wanted = set()
    with tvmaze_path.open() as stream:
        for line in stream:
            imdb_id = (json.loads(line).get("externals") or {}).get("imdb")
            if imdb_id:
                wanted.add(imdb_id)

    imdb_rows = {}
    with gzip.open(imdb_path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        for row in reader:
            if row["tconst"] in wanted:
                imdb_rows[row["tconst"]] = row

    matched_path = output / "tvmaze_imdb.csv"
    unmatched_path = output / "tvmaze_imdb_unmatched.csv"
    external_path = output / "tvmaze_external_ids.csv"
    counts = {"tvmaze_shows": 0, "tvmaze_with_imdb_id": 0, "matched": 0,
              "imdb_id_not_in_basics": 0, "tvmaze_without_imdb_id": 0}
    with matched_path.open("w", newline="") as matched, \
            unmatched_path.open("w", newline="") as unmatched, \
            external_path.open("w", newline="") as external:
        match_writer = csv.writer(matched)
        match_writer.writerow(["tvmaze_id", "tvmaze_name", "tvmaze_type", "tvmaze_premiered",
                               "tvmaze_status", "imdb_tconst", "imdb_primary_title",
                               "imdb_original_title", "imdb_title_type", "imdb_start_year",
                               "imdb_end_year", "match_method"])
        unmatched_writer = csv.writer(unmatched)
        unmatched_writer.writerow(["tvmaze_id", "tvmaze_name", "tvmaze_type",
                                   "tvmaze_premiered", "imdb_tconst", "reason"])
        external_writer = csv.writer(external)
        external_writer.writerow(["tvmaze_id", "scheme", "value"])
        with tvmaze_path.open() as stream:
            for line in stream:
                show = json.loads(line)
                counts["tvmaze_shows"] += 1
                ext = show.get("externals") or {}
                for scheme in ("imdb", "thetvdb", "tvrage"):
                    if ext.get(scheme):
                        external_writer.writerow([show["id"], scheme, ext[scheme]])
                imdb_id = ext.get("imdb")
                if not imdb_id:
                    counts["tvmaze_without_imdb_id"] += 1
                    continue
                counts["tvmaze_with_imdb_id"] += 1
                row = imdb_rows.get(imdb_id)
                if not row:
                    counts["imdb_id_not_in_basics"] += 1
                    unmatched_writer.writerow([show["id"], show.get("name", ""),
                                               show.get("type", ""), show.get("premiered", ""),
                                               imdb_id, "imdb_id_not_in_title_basics"])
                    continue
                counts["matched"] += 1
                match_writer.writerow([
                    show["id"], show.get("name", ""), show.get("type", ""),
                    show.get("premiered", ""), show.get("status", ""),
                    row["tconst"], row["primaryTitle"], row["originalTitle"],
                    row["titleType"], row["startYear"], row["endYear"],
                    "tvmaze.externals.imdb == imdb.title.basics.tconst",
                ])
    manifest = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "tvmaze": str(tvmaze_path),
        "imdb": str(imdb_path),
        "outputs": [str(matched_path), str(unmatched_path), str(external_path)],
        "counts": counts,
        "method": "Exact identifier join only. No title matching, no merges.",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tvmaze", type=Path, required=True)
    parser.add_argument("--imdb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tvmaze_imdb(args.tvmaze, args.imdb, args.output)


if __name__ == "__main__":
    main()
