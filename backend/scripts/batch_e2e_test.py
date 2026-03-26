"""테스트 데이터 01~04 일괄 E2E 검증 스크립트.

실행: python scripts/batch_e2e_test.py
단일 케이스: python scripts/batch_e2e_test.py --case 0
"""
import asyncio
import json
import os
import sys
import io

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

SAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "batch"
)

TEST_CASES = [
    {
        "name": "테스트 01: 화성 연구 기지",
        "file": "테스트 데이터 01.txt",
        "expectation": "테스트 데이터 01 기대값.txt",
    },
    {
        "name": "테스트 02: 마법 왕국",
        "file": "테스트 데이터 02.txt",
        "expectation": "테스트 데이터 02 기대값.txt",
    },
    {
        "name": "테스트 03: 심해 잠수정",
        "file": "테스트 데이터 03.txt",
        "expectation": "테스트 데이터 03 기대값.txt",
    },
    {
        "name": "테스트 04: 시간 연구소",
        "file": "테스트 데이터 04.txt",
        "expectation": "테스트 데이터 04 기대값.txt",
    },
]


async def run_single_test(tc):
    reset_graph_service()

    filepath = os.path.join(SAMPLE_DIR, tc["file"])
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    source_id = "test-src"

    # Extract
    extraction_svc = ExtractionService()
    chunk = DocumentChunk(
        id="test-chunk-0",
        source_id=source_id,
        chunk_index=0,
        content=text,
        location=ChunkLocation(source_id=source_id, source_name=tc["file"]),
    )
    results = await extraction_svc.extract_from_chunks([chunk], source_type="scenario")

    # Normalize
    norm_svc = NormalizationService()
    normalized = await norm_svc.normalize(results)

    # Graph
    graph = InMemoryGraphService()
    source = Source(
        source_id=source_id,
        source_type=SourceType.SCENARIO,
        name=tc["file"],
        file_path=filepath,
    )
    graph.materialize(normalized, source)

    # Detect (full_scan: 구조적 + LLM 세계 규칙 + cross-dedup)
    detection_svc = DetectionService()
    response = await detection_svc.full_scan(graph)

    return response, graph.get_stats()


def load_expectation(filename):
    filepath = os.path.join(SAMPLE_DIR, filename)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def parse_expected(tc):
    """expectation 파일을 읽어 비어 있지 않은 줄 수를 반환한다."""
    filepath = os.path.join(SAMPLE_DIR, tc["expectation"])
    with open(filepath, encoding="utf-8") as f:
        lines = f.read().splitlines()
    return sum(1 for line in lines if line.strip())


async def run_case(idx):
    """단일 테스트 케이스를 실행하고 JSON 한 줄을 stdout에 출력한다. 로그는 stderr."""
    tc = TEST_CASES[idx]
    expected = parse_expected(tc)

    try:
        print(f"[run_case] {tc['name']} 시작", file=sys.stderr)
        response, stats = await run_single_test(tc)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        result = {
            "name": tc["name"],
            "error": str(e),
            "expected": expected,
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    n_hard = response.hard_count
    n_soft = response.soft_count
    n_conf = len(response.confirmations)
    n_total = len(response.contradictions) + n_conf

    details = []
    for r in response.contradictions:
        details.append(r.description)
    for c in response.confirmations:
        details.append(c.question or c.context_summary or "")

    print(
        f"[run_case] {tc['name']} 완료 — HARD={n_hard}, SOFT={n_soft}, CONF={n_conf}, "
        f"total={n_total}, expected={expected}",
        file=sys.stderr,
    )

    result = {
        "name": tc["name"],
        "hard": n_hard,
        "soft": n_soft,
        "conf": n_conf,
        "total": n_total,
        "expected": expected,
        "details": details,
    }
    print(json.dumps(result, ensure_ascii=False))


async def main_all():
    print("=" * 70)
    print("  테스트 데이터 01~04 일괄 E2E 검증")
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

        # 기대값
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

    # 전체 요약
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
        case_idx = int(sys.argv[sys.argv.index("--case") + 1])
        asyncio.run(run_case(case_idx))
    else:
        asyncio.run(main_all())
