"""StatsBomb open data (github.com/hudl/open-data): download once, keep on disk, load as Python objects.

Data licence: free for research; any published analysis must name StatsBomb as the source.
Coordinates: pitch 120 x 80, x grows towards the opponent's goal, y from the left touchline.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional

# jsDelivr mirrors the same GitHub repository through a CDN; GitHub raw throttles after ~100 MB
BASES = ["https://cdn.jsdelivr.net/gh/hudl/open-data@master/data",
         "https://raw.githubusercontent.com/hudl/open-data/master/data"]
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "statsbomb"


def _get(rel: str, retries: int = 3) -> bytes:
    for base in BASES:
        url = f"{base}/{rel}"
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = r.read()
                json.loads(data)               # a truncated or error page must not land in the cache
                return data
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break                      # try the next mirror
                time.sleep(2 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, ValueError):
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"не удалось скачать {rel}")


def fetch(rel: str) -> Path:
    """Path to the cached file, downloading it the first time."""
    path = RAW / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _get(rel)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")   # unique per writer
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def load(rel: str):
    return json.loads(fetch(rel).read_text(encoding="utf-8"))


def competitions() -> List[dict]:
    return load("competitions.json")


def find_season(competition: str, season: str) -> dict:
    for c in competitions():
        if c["competition_name"] == competition and c["season_name"] == season:
            return c
    raise KeyError(f"{competition} {season} нет в открытых данных StatsBomb")


def matches(competition_id: int, season_id: int) -> List[dict]:
    return load(f"matches/{competition_id}/{season_id}.json")


def events(match_id: int) -> List[dict]:
    return load(f"events/{match_id}.json")


def lineups(match_id: int) -> List[dict]:
    return load(f"lineups/{match_id}.json")


def download(match_ids: Iterable[int], kinds=("events", "lineups"), workers: int = 8,
             progress: Optional[callable] = None) -> int:
    """Fetch several matches in parallel; returns how many files were actually downloaded."""
    todo = [f"{k}/{m}.json" for m in match_ids for k in kinds if not (RAW / f"{k}/{m}.json").exists()]
    done = 0
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(fetch, rel): rel for rel in todo}
        for f in as_completed(futures):
            f.result()
            done += 1
            if progress:
                progress(done, len(todo))
    return len(todo)


if __name__ == "__main__":
    # python -m fi.statsbomb "Premier League" 2015/2016 [team]
    sys.stdout.reconfigure(encoding="utf-8")
    comp, season = sys.argv[1], sys.argv[2]
    team = sys.argv[3] if len(sys.argv) > 3 else None
    s = find_season(comp, season)
    ms = matches(s["competition_id"], s["season_id"])
    if team:
        ms = [m for m in ms if team in (m["home_team"]["home_team_name"], m["away_team"]["away_team_name"])]
    print(f"{comp} {season}: {len(ms)} матчей", flush=True)
    t = time.time()
    n = download([m["match_id"] for m in ms],
                 progress=lambda d, total: d % 20 == 0 and print(f"  {d}/{total} файлов", flush=True))
    print(f"скачано файлов: {n} за {time.time() - t:.0f} с")
