"""cases3 테스트 데이터 (c500_13~16, c1000_17~20) 일괄 E2E 검증 스크립트.

세계관 + 설정집 + 시나리오 분리 업로드.

실행: python scripts/cases3_e2e_test.py
단일 케이스: python scripts/cases3_e2e_test.py --case 0
"""
import asyncio
import json
import os
import sys
import io
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

CASES3_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "cases3"
)

TEST_CASES = [
    {
        "name": "test_c500_13",
        "files": [
            ("test_c500_13_world.txt", "worldview"),
            ("test_c500_13_config.txt", "settings"),
            ("test_c500_13_scenario.txt", "scenario"),
        ],
        "expectation": "test_c500_13_expectation.txt",
    },
    {
        "name": "test_c500_14",
        "files": [
            ("test_c500_14_world.txt", "worldview"),
            ("test_c500_14_config.txt", "settings"),
            ("test_c500_14_scenario.txt", "scenario"),
        ],
        "expectation": "test_c500_14_expectation.txt",
    },
    {
        "name": "test_c500_15",
        "files": [
            ("test_c500_15_world.txt", "worldview"),
            ("test_c500_15_config.txt", "settings"),
            ("test_c500_15_scenario.txt", "scenario"),
        ],
        "expectation": "test_c500_15_expectation.txt",
    },
    {
        "name": "test_c500_16",
        "files": [
            ("test_c500_16_world.txt", "worldview"),
            ("test_c500_16_config.txt", "settings"),
            ("test_c500_16_scenario.txt", "scenario"),
        ],
        "expectation": "test_c500_16_expectation.txt",
    },
    {
        "name": "test_c1000_17",
        "files": [
            ("test_c1000_17_world.txt", "worldview"),
            ("test_c1000_17_config.txt", "settings"),
            ("test_c1000_17_scenario.txt", "scenario"),
        ],
        "expectation": "test_c1000_17_expectation.txt",
    },
    {
        "name": "test_c1000_18",
        "files": [
            ("test_c1000_18_world.txt", "worldview"),
            ("test_c1000_18_config.txt", "settings"),
            ("test_c1000_18_scenario.txt", "scenario"),
        ],
        "expectation": "test_c1000_18_expectation.txt",
    },
    {
        "name": "test_c1000_19",
        "files": [
            ("test_c1000_19_world.txt", "worldview"),
            ("test_c1000_19_config.txt", "settings"),
            ("test_c1000_19_scenario.txt", "scenario"),
        ],
        "expectation": "test_c1000_19_expectation.txt",
    },
    {
        "name": "test_c1000_20",
        "files": [
            ("test_c1000_20_world.txt", "worldview"),
            ("test_c1000_20_config.txt", "settings"),
            ("test_c1000_20_scenario.txt", "scenario"),
        ],
        "expectation": "test_c1000_20_expectation.txt",
    },
]


async def upload_and_build_graph(files):
    graph = InMemoryGraphService()

    for filename, source_type in files:
        filepath = os.path.join(CASES3_DIR, filename)
        with open(filepath, encoding="utf-8") as f:
            text = f.read()

        source_id = f"src-{filename.replace('.txt', '')}"

        chunk = DocumentChunk(
            id=f"chunk-{filename}-0",
            source_id=source_id,
            chunk_index=0,
            content=text,
            location=ChunkLocation(source_id=source_id, source_name=filename),
        )

        extraction_svc = ExtractionService()
        results = await extraction_svc.extract_from_chunks([chunk], source_type=source_type)

        norm_svc = NormalizationService()
        normalized = await norm_svc.normalize(results)

        source = Source(
            source_id=source_id,
            source_type=SourceType(source_type),
            name=filename,
            file_path=filepath,
        )
        graph.materialize(normalized, source)

    return graph


async def run_single_test(tc):
    reset_graph_service()

    graph = await upload_and_build_graph(tc["files"])

    detection_svc = DetectionService()
    response = await detection_svc.full_scan(graph)

    return response, graph.get_stats()


def load_expectation(filename):
    filepath = os.path.join(CASES3_DIR, filename)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def parse_expected(tc):
    expectation_text = load_expectation(tc["expectation"])
    match = re.search(r'총\s*(\d+)\s*건', expectation_text)
    return int(match.group(1)) if match else "?"


async def run_case(idx):
    tc = TEST_CASES[idx]
    expected = parse_expected(tc)

    print(f"  케이스: {tc['name']}", file=sys.stderr)

    try:
        response, stats = await run_single_test(tc)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"name": tc["name"], "error": str(e), "expected": expected}, ensure_ascii=False))
        return

    n_hard = response.hard_count
    n_soft = response.soft_count
    n_conf = len(response.confirmations)
    n_total = len(response.contradictions) + n_conf

    print(f"  그래프: 캐릭터={stats.characters}, 사실={stats.facts}, "
          f"이벤트={stats.events}, 특성={stats.traits}", file=sys.stderr)
    print(f"  탐지: HARD={n_hard}, SOFT={n_soft}, 확인요청={n_conf}, 합계={n_total}", file=sys.stderr)

    details = []
    for r in response.contradictions:
        hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
        tval = r.type.value if hasattr(r.type, "value") else r.type
        details.append({"kind": hs, "confidence": round(r.confidence, 2), "type": tval, "desc": r.description[:90]})
    for c in response.confirmations:
        details.append({"kind": "CONF", "type": c.confirmation_type.value,
                        "desc": (c.question or c.context_summary or "")[:90]})

    print(json.dumps({
        "name": tc["name"],
        "hard": n_hard,
        "soft": n_soft,
        "conf": n_conf,
        "total": n_total,
        "expected": expected,
        "details": details,
    }, ensure_ascii=False))


async def main_all():
    print("=" * 70)
    print("  cases3 테스트 (c500_13~16, c1000_17~20) 일괄 E2E 검증")
    print("=" * 70)

    all_results = []

    for tc in TEST_CASES:
        print(f"\n{'─' * 70}")
        print(f"  {tc['name']}")
        print(f"  파일: {[f[0] for f in tc['files']]}")
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
        match = re.search(r'총\s*(\d+)\s*건', expectation_text)
        expected_count = int(match.group(1)) if match else "?"
        print(f"  기대 모순: {expected_count}건 | 실제 탐지: {n_total}건")

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
        exp = r["expected"] if isinstance(r["expected"], int) else 0
        total_expected += exp
        total_detected += r["total"]
        print(f"  {r['name']:<40} {exp:>4} {r['total']:>4} {r['hard']:>4} {r['soft']:>4} {r['conf']:>4}")

    print(f"  {'─' * 66}")
    print(f"  {'합계':<40} {total_expected:>4} {total_detected:>4}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    if "--case" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--case") + 1])
        asyncio.run(run_case(idx))
    else:
        asyncio.run(main_all())
