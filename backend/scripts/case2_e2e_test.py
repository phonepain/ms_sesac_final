"""case2 테스트 데이터 (test_1~8) 일괄 E2E 검증 스크립트.

test_1~6: 세계관 + 설정집 + 시나리오 분리 업로드
test_7~8: 시나리오 단독 (세계관/설정집 없음)

실행: python scripts/case2_e2e_test.py
단일 케이스: python scripts/case2_e2e_test.py --case 0
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

CASE2_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "case2"
)

TEST_CASES = [
    {
        "name": "test_1: 심해 관측기지 아비스-9",
        "files": [
            ("test_1_world.txt", "worldview"),
            ("test_1_config.txt", "settings"),
            ("test_1_scenario.txt", "scenario"),
        ],
        "expectation": "test_1_expectation.txt",
    },
    {
        "name": "test_2: 공중도시 루멘 아크",
        "files": [
            ("test_2_world.txt", "worldview"),
            ("test_2_config.txt", "settings"),
            ("test_2_scenario.txt", "scenario"),
        ],
        "expectation": "test_2_expectation.txt",
    },
    {
        "name": "test_3: 중앙지방법원 12호 법정",
        "files": [
            ("test_3_world.txt", "worldview"),
            ("test_3_config.txt", "settings"),
            ("test_3_scenario.txt", "scenario"),
        ],
        "expectation": "test_3_expectation.txt",
    },
    {
        "name": "test_4: 사막왕국 아샤르",
        "files": [
            ("test_4_world.txt", "worldview"),
            ("test_4_config.txt", "settings"),
            ("test_4_scenario.txt", "scenario"),
        ],
        "expectation": "test_4_expectation.txt",
    },
    {
        "name": "test_5: e스포츠 아레나 제로돔",
        "files": [
            ("test_5_world.txt", "worldview"),
            ("test_5_config.txt", "settings"),
            ("test_5_scenario.txt", "scenario"),
        ],
        "expectation": "test_5_expectation.txt",
    },
    {
        "name": "test_6: 수도원 은종회랑",
        "files": [
            ("test_6_world.txt", "worldview"),
            ("test_6_config.txt", "settings"),
            ("test_6_scenario.txt", "scenario"),
        ],
        "expectation": "test_6_expectation.txt",
    },
    {
        "name": "test_7: 궤도 교도소 헬릭스 (시나리오 단독)",
        "files": [
            ("test_7_scenario.txt", "scenario"),
        ],
        "expectation": "test_7_expectation.txt",
    },
    {
        "name": "test_8: 격리 병원 화이트돔 (시나리오 단독)",
        "files": [
            ("test_8_scenario.txt", "scenario"),
        ],
        "expectation": "test_8_expectation.txt",
    },
]


async def upload_and_build_graph(files):
    graph = InMemoryGraphService()

    for filename, source_type in files:
        filepath = os.path.join(CASE2_DIR, filename)
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

    # full_scan: 구조적 + LLM 세계 규칙 + cross-dedup
    detection_svc = DetectionService()
    response = await detection_svc.full_scan(graph)

    return response, graph.get_stats()


def load_expectation(filename):
    filepath = os.path.join(CASE2_DIR, filename)
    with open(filepath, encoding="utf-8") as f:
        return f.read()


def parse_expected(tc):
    expectation_text = load_expectation(tc["expectation"])
    match = re.search(r'총\s*(\d+)\s*건', expectation_text)
    return int(match.group(1)) if match else "?"


async def run_case(idx):
    tc = TEST_CASES[idx]
    expected = parse_expected(tc)

    print(f"[run_case] idx={idx} name={tc['name']}", file=sys.stderr)

    try:
        response, stats = await run_single_test(tc)
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        result = {
            "name": tc["name"],
            "error": str(e),
            "expected": expected,
        }
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return

    n_hard = response.hard_count
    n_soft = response.soft_count
    n_conf = len(response.confirmations)
    n_total = len(response.contradictions) + n_conf

    details = []
    for r in response.contradictions:
        hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
        tval = r.type.value if hasattr(r.type, "value") else r.type
        details.append({
            "kind": hs,
            "confidence": round(r.confidence, 2),
            "type": tval,
            "description": r.description[:90],
        })
    for c in response.confirmations:
        details.append({
            "kind": "CONF",
            "type": c.confirmation_type.value,
            "description": (c.question or c.context_summary or "")[:90],
        })

    result = {
        "name": tc["name"],
        "hard": n_hard,
        "soft": n_soft,
        "conf": n_conf,
        "total": n_total,
        "expected": expected,
        "details": details,
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def main_all():
    print("=" * 70)
    print("  case2 테스트 데이터 (test_1~8) 일괄 E2E 검증")
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

        # 기대값
        print()
        expected_count = parse_expected(tc)
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
        case_idx = int(sys.argv[sys.argv.index("--case") + 1])
        asyncio.run(run_case(case_idx))
    else:
        asyncio.run(main_all())
