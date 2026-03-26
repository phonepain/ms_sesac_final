"""wss1000 (case21~24) E2E 검증.

단일 파일에 [세계관]/[설정집]/[시나리오] 섹션 포함.

실행:
  python scripts/wss1000_e2e_test.py
  python scripts/wss1000_e2e_test.py --case 0
"""
import asyncio
import os
import sys
import io
import json

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
    "data", "sample", "wss1000"
)

TEST_CASES = [
    {"name": "case21", "file": "case21.txt", "expectation": "expectation21.txt"},
    {"name": "case22", "file": "case22.txt", "expectation": "expectation22.txt"},
    {"name": "case23", "file": "case23.txt", "expectation": "expectation23.txt"},
    {"name": "case24", "file": "case24.txt", "expectation": "expectation24.txt"},
]

SECTION_MAP = {"세계관": "worldview", "설정집": "settings", "시나리오": "scenario"}


def split_sections(text):
    sections = []
    current_type = "scenario"
    current_lines = []
    for line in text.splitlines():
        stripped = line.strip().strip("[]")
        if stripped in SECTION_MAP:
            if current_lines:
                sections.append((current_type, "\n".join(current_lines)))
                current_lines = []
            current_type = SECTION_MAP[stripped]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_type, "\n".join(current_lines)))
    return sections if sections else [("scenario", text)]


async def run_single_test(tc):
    reset_graph_service()
    filepath = os.path.join(CASE_DIR, tc["file"])
    with open(filepath, encoding="utf-8") as f:
        text = f.read()
    sections = split_sections(text)
    graph = InMemoryGraphService()
    for source_type, section_text in sections:
        if not section_text.strip():
            continue
        source_id = f"src-{tc['name']}-{source_type}"
        chunk = DocumentChunk(
            id=f"chunk-{source_id}-0", source_id=source_id, chunk_index=0,
            content=section_text,
            location=ChunkLocation(source_id=source_id, source_name=tc["file"]),
        )
        results = await ExtractionService().extract_from_chunks([chunk], source_type=source_type)
        normalized = await NormalizationService().normalize(results)
        source = Source(source_id=source_id, source_type=SourceType(source_type),
                        name=tc["file"], file_path=filepath)
        graph.materialize(normalized, source)
    response = await DetectionService().full_scan(graph)
    return response, graph.get_stats()


def parse_expected(tc):
    with open(os.path.join(CASE_DIR, tc["expectation"]), encoding="utf-8") as f:
        return len([l for l in f.read().strip().splitlines() if l.strip()])


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
    print("  wss1000 (case21~24) E2E 검증")
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
