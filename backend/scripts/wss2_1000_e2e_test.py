"""wss2_1000 (case25~28) E2E 검증.

3파일 분리: world + setting + scenario.

실행:
  python scripts/wss2_1000_e2e_test.py
  python scripts/wss2_1000_e2e_test.py --case 0
"""
import asyncio
import os
import sys
import io
import json
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.graph import InMemoryGraphService, reset_graph_service
from app.services.detection import DetectionService
from app.models.api import DocumentChunk, ChunkLocation
from app.models.vertices import Source
from app.models.enums import SourceType

CASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "wss2_1000"
)

TEST_CASES = [
    {
        "name": "case25",
        "files": [
            ("case25_world.txt", "worldview"),
            ("case25_setting.txt", "settings"),
            ("case25_scenario.txt", "scenario"),
        ],
        "expectation": "expectation25.txt",
    },
    {
        "name": "case26",
        "files": [
            ("case26_world.txt", "worldview"),
            ("case26_setting.txt", "settings"),
            ("case26_scenario.txt", "scenario"),
        ],
        "expectation": "expectation26.txt",
    },
    {
        "name": "case27",
        "files": [
            ("case27_world.txt", "worldview"),
            ("case27_setting.txt", "settings"),
            ("case27_scenario.txt", "scenario"),
        ],
        "expectation": "expectation27.txt",
    },
    {
        "name": "case28",
        "files": [
            ("case28_world.txt", "worldview"),
            ("case28_setting.txt", "settings"),
            ("case28_scenario.txt", "scenario"),
        ],
        "expectation": "expectation28.txt",
    },
]


async def upload_and_build_graph(files):
    graph = InMemoryGraphService()
    for filename, source_type in files:
        filepath = os.path.join(CASE_DIR, filename)
        with open(filepath, encoding="utf-8") as f:
            text = f.read()
        source_id = f"src-{filename.replace('.txt', '')}"
        chunk = DocumentChunk(
            id=f"chunk-{filename}-0", source_id=source_id, chunk_index=0,
            content=text,
            location=ChunkLocation(source_id=source_id, source_name=filename),
        )
        results = await ExtractionService().extract_from_chunks([chunk], source_type=source_type)
        normalized = await NormalizationService().normalize(results)
        source = Source(source_id=source_id, source_type=SourceType(source_type),
                        name=filename, file_path=filepath)
        graph.materialize(normalized, source)
    return graph


async def run_single_test(tc):
    reset_graph_service()
    graph = await upload_and_build_graph(tc["files"])
    response = await DetectionService().full_scan(graph)
    return response, graph.get_stats()


def parse_expected(tc):
    with open(os.path.join(CASE_DIR, tc["expectation"]), encoding="utf-8") as f:
        text = f.read()
    match = re.search(r'총\s*(\d+)\s*건', text)
    if match:
        return int(match.group(1))
    return len([l for l in text.strip().splitlines() if l.strip()])


async def run_case(idx):
    tc = TEST_CASES[idx]
    try:
        response, stats = await run_single_test(tc)
    except Exception as e:
        print(json.dumps({"name": tc["name"], "error": str(e), "expected": parse_expected(tc)}, ensure_ascii=False))
        return
    n_conf = len(response.confirmations)
    n_total = len(response.contradictions) + n_conf
    details = []
    for r in response.contradictions:
        hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
        tval = r.type.value if hasattr(r.type, "value") else r.type
        details.append(f"[{hs}] ({r.confidence:.2f}) {tval}: {r.description[:100]}")
    for c in response.confirmations:
        details.append(f"[CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:100]}")
    print(json.dumps({"name": tc["name"], "hard": response.hard_count, "soft": response.soft_count,
                       "conf": n_conf, "total": n_total, "expected": parse_expected(tc),
                       "details": details}, ensure_ascii=False))


async def main_all():
    print("=" * 70)
    print("  wss2_1000 (case25~28) E2E 검증")
    print("=" * 70)
    all_results = []
    for tc in TEST_CASES:
        print(f"\n{'─' * 70}\n  {tc['name']}\n{'─' * 70}")
        try:
            response, stats = await run_single_test(tc)
        except Exception as e:
            print(f"  ERROR: {e}"); all_results.append({"name": tc["name"], "error": str(e)}); continue
        n_total = len(response.contradictions) + len(response.confirmations)
        expected = parse_expected(tc)
        print(f"  탐지: HARD={response.hard_count}, SOFT={response.soft_count}, 합계={n_total}")
        print(f"  기대: {expected}건")
        all_results.append({"name": tc["name"], "total": n_total, "expected": expected})
    te = sum(r.get("expected", 0) for r in all_results if "error" not in r)
    td = sum(r.get("total", 0) for r in all_results if "error" not in r)
    print(f"\n{'=' * 70}\n  합계: 기대={te} 탐지={td}\n{'=' * 70}")


if __name__ == "__main__":
    if "--case" in sys.argv:
        asyncio.run(run_case(int(sys.argv[sys.argv.index("--case") + 1])))
    else:
        asyncio.run(main_all())
