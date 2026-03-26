"""Variation Pack (variation) 5종 일괄 E2E 검증 스크립트.

각 테스트 케이스: 세계관 + 설정집 + 시나리오 3파일 분리 처리.

실행: python scripts/variation_e2e_test.py
단일 케이스: python scripts/variation_e2e_test.py --case 0
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
    "data", "sample", "variation"
)

TEST_CASES = [
    {"name": "1. 화성기지_적색폭풍", "prefix": "화성기지_적색폭풍"},
    {"name": "2. 마도학원_은빛봉인", "prefix": "마도학원_은빛봉인"},
    {"name": "3. 사이버시티_네온추적", "prefix": "사이버시티_네온추적"},
    {"name": "4. 조선궁중_비단암호", "prefix": "조선궁중_비단암호"},
    {"name": "5. 그림자저택_안개섬", "prefix": "그림자저택_안개섬"},
]

FILE_TYPES = [
    ("세계관", "worldview", SourceType.WORLDVIEW),
    ("설정집", "settings", SourceType.SETTINGS),
    ("시나리오", "scenario", SourceType.SCENARIO),
]


async def run_single_test(test_case):
    prefix = test_case["prefix"]
    extraction_svc = ExtractionService()
    norm_svc = NormalizationService()

    all_extraction_results = []

    for file_label, source_type_str, source_type_enum in FILE_TYPES:
        filename = f"{file_label}_{prefix}.txt"
        filepath = os.path.join(SAMPLE_DIR, filename)

        if not os.path.exists(filepath):
            print(f"    [WARN] 파일 없음: {filename}", file=sys.stderr)
            continue

        with open(filepath, encoding="utf-8") as f:
            text = f.read()

        chunk = DocumentChunk(
            id=f"chunk-{file_label}-0",
            source_id=f"src-{file_label}",
            chunk_index=0,
            content=text,
            location=ChunkLocation(source_id=f"src-{file_label}", source_name=filename),
        )
        results = await extraction_svc.extract_from_chunks([chunk], source_type=source_type_str)
        all_extraction_results.extend(results)
        print(f"    추출 완료: {filename} ({source_type_str})", file=sys.stderr)

    normalized = await norm_svc.normalize(all_extraction_results)

    reset_graph_service()
    graph = InMemoryGraphService()

    scenario_file = f"시나리오_{prefix}.txt"
    source = Source(
        source_id="test-src",
        source_type=SourceType.SCENARIO,
        name=scenario_file,
        file_path=os.path.join(SAMPLE_DIR, scenario_file),
    )
    graph.materialize(normalized, source)

    # full_scan: 구조적 + LLM 세계 규칙 + cross-dedup
    detection_svc = DetectionService()
    response = await detection_svc.full_scan(graph)

    return response


async def run_case(idx):
    tc = TEST_CASES[idx]
    name = tc["name"]
    try:
        response = await run_single_test(tc)
        hard = response.hard_count
        soft = response.soft_count
        conf = len(response.confirmations)
        total = len(response.contradictions) + conf
        details = []
        for r in response.contradictions:
            hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
            tval = r.type.value if hasattr(r.type, "value") else str(r.type)
            details.append({"severity": hs, "type": tval, "description": r.description})
        for c in response.confirmations:
            ctype = c.confirmation_type.value if hasattr(c.confirmation_type, "value") else str(c.confirmation_type)
            details.append({"severity": "CONF", "type": ctype, "description": (c.question or c.context_summary or "")})
        print(json.dumps({
            "name": name,
            "hard": hard,
            "soft": soft,
            "conf": conf,
            "total": total,
            "expected": 0,
            "details": details,
        }, ensure_ascii=False))
    except Exception as e:
        import traceback
        print(traceback.format_exc(), file=sys.stderr)
        print(json.dumps({
            "name": name,
            "error": str(e),
            "expected": 0,
        }, ensure_ascii=False))


async def main_all():
    print("=" * 80, file=sys.stderr)
    print("  Variation Pack — 5종 E2E 모순 탐지 (세계관+설정집+시나리오 분리)", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    grand_total = 0

    for tc in TEST_CASES:
        print(f"\n{'─' * 80}", file=sys.stderr)
        print(f"  {tc['name']}", file=sys.stderr)
        print(f"{'─' * 80}", file=sys.stderr)

        try:
            response = await run_single_test(tc)
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            continue

        n_hard = response.hard_count
        n_soft = response.soft_count
        n_conf = len(response.confirmations)
        n_total = len(response.contradictions) + n_conf
        grand_total += n_total

        print(f"\n  탐지 결과: HARD={n_hard}, SOFT={n_soft}, 확인요청={n_conf}, 합계={n_total}", file=sys.stderr)
        print(file=sys.stderr)

        for i, r in enumerate(response.contradictions, 1):
            hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
            tval = r.type.value if hasattr(r.type, "value") else r.type
            print(f"    {i:2d}. [{hs}] {tval}: {r.description[:100]}", file=sys.stderr)
        for j, c in enumerate(response.confirmations, len(response.contradictions) + 1):
            print(f"    {j:2d}. [CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:100]}", file=sys.stderr)

    print(f"\n{'=' * 80}", file=sys.stderr)
    print(f"  전체 합계: {grand_total}건", file=sys.stderr)
    print(f"{'=' * 80}", file=sys.stderr)


if __name__ == "__main__":
    if "--case" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--case") + 1])
        asyncio.run(run_case(idx))
    else:
        asyncio.run(main_all())
