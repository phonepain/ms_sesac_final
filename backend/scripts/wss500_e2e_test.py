"""wss500 (case17~20) E2E 검증.

단일 파일에 [세계관]/[설정집]/[시나리오] 섹션 포함.
섹션을 분리해서 각 source_type으로 추출.

실행:
  python scripts/wss500_e2e_test.py
  python scripts/wss500_e2e_test.py --case 0
"""
import asyncio
import os
import sys
import io
import re
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
    "data", "sample", "wss500"
)

TEST_CASES = [
    {"name": "case17", "file": "case17.txt", "expectation": "expectation17.txt"},
    {"name": "case18", "file": "case18.txt", "expectation": "expectation18.txt"},
    {"name": "case19", "file": "case19.txt", "expectation": "expectation19.txt"},
    {"name": "case20", "file": "case20.txt", "expectation": "expectation20.txt"},
]

SECTION_MAP = {
    "세계관": "worldview",
    "설정집": "settings",
    "시나리오": "scenario",
}


def split_sections(text):
    """[세계관]/[설정집]/[시나리오] 섹션으로 분리."""
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
        extraction_svc = ExtractionService()
        results = await extraction_svc.extract_from_chunks([chunk], source_type=source_type)

        norm_svc = NormalizationService()
        normalized = await norm_svc.normalize(results)

        source = Source(
            source_id=source_id, source_type=SourceType(source_type),
            name=tc["file"], file_path=filepath,
        )
        graph.materialize(normalized, source)

    detection_svc = DetectionService()
    response = await detection_svc.full_scan(graph)
    return response, graph.get_stats()


def load_expectation(filename):
    filepath = os.path.join(CASE_DIR, filename)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def parse_expected(tc):
    text = load_expectation(tc["expectation"])
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return len(lines)


async def run_case(idx):
    tc = TEST_CASES[idx]
    try:
        response, stats = await run_single_test(tc)
    except Exception as e:
        print(json.dumps({"name": tc["name"], "error": str(e), "expected": parse_expected(tc)}, ensure_ascii=False))
        return

    n_hard = response.hard_count
    n_soft = response.soft_count
    n_conf = len(response.confirmations)
    n_total = len(response.contradictions) + n_conf

    details = []
    for r in response.contradictions:
        hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
        tval = r.type.value if hasattr(r.type, "value") else r.type
        details.append(f"[{hs}] ({r.confidence:.2f}) {tval}: {r.description[:100]}")
    for c in response.confirmations:
        details.append(f"[CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:100]}")

    print(json.dumps({
        "name": tc["name"], "hard": n_hard, "soft": n_soft, "conf": n_conf,
        "total": n_total, "expected": parse_expected(tc), "details": details,
    }, ensure_ascii=False))


async def main_all():
    print("=" * 70)
    print("  wss500 (case17~20) E2E 검증")
    print("=" * 70)
    all_results = []
    for tc in TEST_CASES:
        print(f"\n{'─' * 70}\n  {tc['name']} ({tc['file']})\n{'─' * 70}")
        try:
            response, stats = await run_single_test(tc)
        except Exception as e:
            print(f"  ERROR: {e}"); import traceback; traceback.print_exc()
            all_results.append({"name": tc["name"], "error": str(e)}); continue
        n_total = len(response.contradictions) + len(response.confirmations)
        print(f"  탐지: HARD={response.hard_count}, SOFT={response.soft_count}, "
              f"확인요청={len(response.confirmations)}, 합계={n_total}")
        for r in response.contradictions:
            hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
            tval = r.type.value if hasattr(r.type, "value") else r.type
            print(f"    [{hs}] ({r.confidence:.2f}) {tval}: {r.description[:90]}")
        for c in response.confirmations:
            print(f"    [CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:90]}")
        expected = parse_expected(tc)
        print(f"\n  기대 모순: {expected}건 | 실제 탐지: {n_total}건")
        all_results.append({"name": tc["name"], "hard": response.hard_count, "soft": response.soft_count,
                            "conf": len(response.confirmations), "total": n_total, "expected": expected})
    print(f"\n{'=' * 70}\n  전체 요약\n{'=' * 70}")
    te, td = 0, 0
    for r in all_results:
        if "error" in r: continue
        te += r["expected"]; td += r["total"]
    print(f"  합계: 기대={te} 탐지={td}\n{'=' * 70}")


if __name__ == "__main__":
    if "--case" in sys.argv:
        asyncio.run(run_case(int(sys.argv[sys.argv.index("--case") + 1])))
    else:
        asyncio.run(main_all())
