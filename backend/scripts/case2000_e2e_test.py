"""case2000 (case9~12) 일괄 E2E 검증 스크립트.

단일 파일 시나리오 (~2000자). 기대값 파일 포함.

실행:
  python scripts/case2000_e2e_test.py           # 전체
  python scripts/case2000_e2e_test.py --case 0   # case9만
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
from app.services.ingest import IngestService
from app.models.api import DocumentChunk, ChunkLocation
from app.models.vertices import Source
from app.models.enums import SourceType

CASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "case2000"
)

TEST_CASES = [
    {"name": "case9", "file": "case9.txt", "expectation": "expectation9.txt"},
    {"name": "case10", "file": "case10.txt", "expectation": "expectation10.txt"},
    {"name": "case11", "file": "case11.txt", "expectation": "expectation11.txt"},
    {"name": "case12", "file": "case12.txt", "expectation": "expectation12.txt"},
]


async def run_single_test(tc):
    reset_graph_service()

    filepath = os.path.join(CASE_DIR, tc["file"])
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    source_id = f"src-{tc['name']}"

    # 2000자급이라 청킹 적용
    ingest = IngestService()
    chunks = ingest.chunk_text(
        text=text,
        source_id=source_id,
        source_name=tc["file"],
    )
    if not chunks:
        chunks = [DocumentChunk(
            id=f"chunk-{tc['name']}-0",
            source_id=source_id,
            chunk_index=0,
            content=text,
            location=ChunkLocation(source_id=source_id, source_name=tc["file"]),
        )]

    print(f"    {tc['file']}: {len(text)}자, {len(chunks)}청크", file=sys.stderr)

    extraction_svc = ExtractionService()
    results = await extraction_svc.extract_from_chunks(chunks, source_type="scenario")

    norm_svc = NormalizationService()
    normalized = await norm_svc.normalize(results)

    graph = InMemoryGraphService()
    source = Source(
        source_id=source_id,
        source_type=SourceType.SCENARIO,
        name=tc["file"],
        file_path=filepath,
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
    print("  case2000 (case9~12) 일괄 E2E 검증")
    print("=" * 70)

    all_results = []

    for tc in TEST_CASES:
        print(f"\n{'─' * 70}")
        print(f"  {tc['name']} ({tc['file']})")
        print(f"{'─' * 70}")

        try:
            response, stats = await run_single_test(tc)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({"name": tc["name"], "error": str(e)})
            continue

        n_hard = response.hard_count
        n_soft = response.soft_count
        n_conf = len(response.confirmations)
        n_total = len(response.contradictions) + n_conf

        print(f"  그래프: 캐릭터={stats.characters}, 사실={stats.facts}, "
              f"이벤트={stats.events}, 특성={stats.traits}")
        print(f"  탐지: HARD={n_hard}, SOFT={n_soft}, 확인요청={n_conf}, 합계={n_total}")
        print()

        for r in response.contradictions:
            hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
            tval = r.type.value if hasattr(r.type, "value") else r.type
            print(f"    [{hs}] ({r.confidence:.2f}) {tval}: {r.description[:90]}")
        for c in response.confirmations:
            print(f"    [CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:90]}")

        print()
        expectation_text = load_expectation(tc["expectation"])
        exp_lines = [l.strip() for l in expectation_text.strip().splitlines() if l.strip()]
        expected_count = len(exp_lines)
        print(f"  기대 모순: {expected_count}건 | 실제 탐지: {n_total}건")
        print(f"  기대값:")
        for line in exp_lines:
            print(f"    {line}")

        all_results.append({
            "name": tc["name"],
            "hard": n_hard,
            "soft": n_soft,
            "conf": n_conf,
            "total": n_total,
            "expected": expected_count,
        })

    print(f"\n{'=' * 70}")
    print("  전체 요약")
    print(f"{'=' * 70}")
    print(f"  {'케이스':<40} {'기대':>4} {'탐지':>4} {'HARD':>4} {'SOFT':>4} {'CONF':>4}")
    print(f"  {'─' * 66}")

    total_expected = 0
    total_detected = 0
    for r in all_results:
        if "error" in r:
            print(f"  {r['name']:<40} {'ERR':>4}")
            continue
        total_expected += r["expected"]
        total_detected += r["total"]
        print(f"  {r['name']:<40} {r['expected']:>4} {r['total']:>4} {r['hard']:>4} {r['soft']:>4} {r['conf']:>4}")

    print(f"  {'─' * 66}")
    print(f"  {'합계':<40} {total_expected:>4} {total_detected:>4}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    if "--case" in sys.argv:
        asyncio.run(run_case(int(sys.argv[sys.argv.index("--case") + 1])))
    else:
        asyncio.run(main_all())
