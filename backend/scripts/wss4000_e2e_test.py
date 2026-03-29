"""wss4000 (case29) E2E 검증.

세계관/설정집/시나리오 파일이 각각 분리된 형태.

실행:
  python scripts/wss4000_e2e_test.py
  python scripts/wss4000_e2e_test.py --case 0
"""
import asyncio
import os
import sys
import io
import json
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.graph import InMemoryGraphService, reset_graph_service
from app.services.detection import DetectionService
from app.services.ingest import IngestService
from app.models.api import DocumentChunk, ChunkLocation
from app.models.vertices import Source
from app.models.enums import SourceType

CASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "wss4000"
)

TEST_CASES = [
    {
        "name": "case29",
        "files": [
            ("case29_world.txt", "worldview"),
            ("case29_setting.txt", "settings"),
            ("case29_scenario.txt", "scenario"),
        ],
        "expectation": "expectation29.txt",
    },
    {
        "name": "case30",
        "files": [
            ("case30_world.txt", "worldview"),
            ("case30_setting.txt", "settings"),
            ("case30_scenario.txt", "scenario"),
        ],
        "expectation": "expectation30.txt",
    },
    {
        "name": "case31",
        "files": [
            ("case31_world.txt", "worldview"),
            ("case31_setting.txt", "settings"),
            ("case31_scenario.txt", "scenario"),
        ],
        "expectation": "expectation31.txt",
    },
    {
        "name": "case32",
        "files": [
            ("case32_world.txt", "worldview"),
            ("case32_setting.txt", "settings"),
            ("case32_scenario.txt", "scenario"),
        ],
        "expectation": "expectation32.txt",
    },
]


async def run_single_test(tc):
    reset_graph_service()
    graph = InMemoryGraphService()
    ingest = IngestService()
    all_extraction_results = []

    for filename, source_type in tc["files"]:
        filepath = os.path.join(CASE_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  WARN: {filepath} not found, skipping", file=sys.stderr)
            continue
        with open(filepath, encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            continue

        source_id = f"src-{tc['name']}-{source_type}"
        chunks = ingest.chunk_text(text=text, source_id=source_id, source_name=filename)
        if not chunks:
            chunks = [DocumentChunk(
                id=f"chunk-{source_id}-0", source_id=source_id, chunk_index=0,
                content=text,
                location=ChunkLocation(source_id=source_id, source_name=filename),
            )]
        print(f"    {filename}: {len(text)}자, {len(chunks)}청크", file=sys.stderr)

        results = await ExtractionService().extract_from_chunks(
            chunks, source_type=source_type
        )
        all_extraction_results.extend(results)

    # 정규화
    normalized = await NormalizationService().normalize(all_extraction_results)

    # 그래프 적재
    scenario_file = tc["files"][-1][0]  # scenario file
    source = Source(
        source_id=f"src-{tc['name']}-scenario",
        source_type=SourceType.SCENARIO,
        name=scenario_file,
        file_path=os.path.join(CASE_DIR, scenario_file),
    )
    graph.materialize(normalized, source)

    # 탐지
    response = await DetectionService().full_scan(graph)
    return response, graph.get_stats()


def parse_expected(tc):
    exp_path = os.path.join(CASE_DIR, tc["expectation"])
    with open(exp_path, encoding="utf-8") as f:
        return len([l for l in f.read().strip().splitlines() if l.strip()])


async def run_case(idx):
    tc = TEST_CASES[idx]
    start = time.time()
    try:
        response, stats = await run_single_test(tc)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(json.dumps({"name": tc["name"], "error": str(e),
                           "expected": parse_expected(tc)}, ensure_ascii=False))
        return
    elapsed = round(time.time() - start, 1)
    n_conf = len(response.confirmations)
    n_total = len(response.contradictions) + n_conf
    details = []
    for r in response.contradictions:
        hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
        tval = r.type.value if hasattr(r.type, "value") else r.type
        details.append({
            "kind": hs, "confidence": round(r.confidence, 2),
            "type": tval, "description": r.description[:200],
        })
    for c in response.confirmations:
        details.append({
            "kind": "CONF", "confidence": 0,
            "type": c.confirmation_type.value,
            "description": (c.question or c.context_summary)[:200],
        })
    print(json.dumps({
        "name": tc["name"], "hard": response.hard_count, "soft": response.soft_count,
        "conf": n_conf, "total": n_total, "expected": parse_expected(tc),
        "processing_time_ms": elapsed, "details": details,
    }, ensure_ascii=False))


async def main_all():
    print("=" * 70)
    print("  wss4000 (case29) E2E 검증")
    print("=" * 70)
    all_results = []
    for tc in TEST_CASES:
        print(f"\n{'─' * 70}\n  {tc['name']}\n{'─' * 70}")
        start = time.time()
        try:
            response, stats = await run_single_test(tc)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ERROR: {e}")
            all_results.append({"name": tc["name"], "error": str(e)})
            continue
        elapsed = round(time.time() - start, 1)
        n_total = len(response.contradictions) + len(response.confirmations)
        expected = parse_expected(tc)
        print(f"  탐지: HARD={response.hard_count}, SOFT={response.soft_count}, 합계={n_total}")
        print(f"  기대: {expected}건")
        print(f"  소요: {elapsed}초")
        print(f"\n  상세:")
        for r in response.contradictions:
            hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
            tval = r.type.value if hasattr(r.type, "value") else r.type
            print(f"    [{hs}] ({r.confidence:.2f}) {tval}: {r.description[:120]}")
        for c in response.confirmations:
            print(f"    [CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:120]}")
        all_results.append({"name": tc["name"], "total": n_total, "expected": expected})

    te = sum(r.get("expected", 0) for r in all_results if "error" not in r)
    td = sum(r.get("total", 0) for r in all_results if "error" not in r)
    print(f"\n{'=' * 70}\n  합계: 기대={te} 탐지={td}\n{'=' * 70}")


if __name__ == "__main__":
    if "--case" in sys.argv:
        asyncio.run(run_case(int(sys.argv[sys.argv.index("--case") + 1])))
    else:
        asyncio.run(main_all())
