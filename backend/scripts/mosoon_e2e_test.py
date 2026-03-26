"""Mosoon_test.txt LLM 파이프라인 E2E 검증 스크립트.

실행: python scripts/mosoon_e2e_test.py
"""
import asyncio
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

MOSOON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "sample", "Mosoon_test.txt"
)


async def run():
    print("=" * 60)
    print("Mosoon_test.txt E2E 파이프라인 검증")
    print("=" * 60)

    with open(MOSOON_PATH, encoding="utf-8") as f:
        text = f.read()
    print(f"[1] 파일 로드 완료 ({len(text)} chars)")

    # Extract
    extraction_svc = ExtractionService()
    chunk = DocumentChunk(
        id="mosoon-chunk-0",
        source_id="mosoon-src",
        chunk_index=0,
        content=text,
        location=ChunkLocation(source_id="mosoon-src", source_name="Mosoon_test.txt"),
    )
    print("[2] LLM 추출 시작...")
    results = await extraction_svc.extract_from_chunks([chunk], source_type="scenario")
    ext = results[0]

    print(f"    characters   : {len(ext.characters)}")
    print(f"    facts        : {len(ext.facts)}")
    print(f"    events       : {[e.description[:40] for e in ext.events]}")
    print(f"    traits       : {len(ext.traits)}")
    print(f"    knowledge_ev : {len(ext.knowledge_events)}")
    print(f"    item_events  : {len(ext.item_events)}")

    # Normalize
    norm_svc = NormalizationService()
    print("[3] 정규화 시작...")
    normalized = await norm_svc.normalize(results)
    print(f"    chars        : {[c.canonical_name for c in normalized.characters]}")
    print(f"    facts        : {[f.content[:50] for f in normalized.facts]}")
    print(f"    events       : {len(normalized.events)}")

    # Graph
    reset_graph_service()
    graph = InMemoryGraphService()
    source = Source(
        source_id="mosoon-src",
        source_type=SourceType.SCENARIO,
        name="Mosoon_test.txt",
        file_path=MOSOON_PATH,
    )
    print("[4] 그래프 적재 시작...")
    graph.materialize(normalized, source)

    stats = graph.get_stats()
    print(f"    vertices - char:{stats.characters}, fact:{stats.facts}, "
          f"event:{stats.events}")

    # Detect (full_scan: 구조적 + LLM 세계 규칙 + cross-dedup)
    print("[5] 모순 탐지 시작 (full_scan)...")
    detection_svc = DetectionService()
    response = await detection_svc.full_scan(graph)

    n_hard = response.hard_count
    n_soft = response.soft_count
    n_conf = len(response.confirmations)

    print(f"\n{'=' * 60}")
    print(f"  탐지 결과: HARD={n_hard}, SOFT={n_soft}, 확인요청={n_conf}, "
          f"합계={len(response.contradictions) + n_conf}")
    print(f"{'=' * 60}")

    print("\n[탐지된 모순]")
    for r in response.contradictions:
        hs = r.hard_or_soft.upper() if r.hard_or_soft else "?"
        tval = r.type.value if hasattr(r.type, "value") else r.type
        print(f"  [{hs}] {tval}: {r.description[:70]}")
    for c in response.confirmations:
        print(f"  [CONF] {c.confirmation_type.value}: {(c.question or c.context_summary)[:70]}")

    # 커버리지 체크
    all_text = ""
    for r in response.contradictions:
        all_text += r.description + " "
    for c in response.confirmations:
        all_text += (c.question or "") + " " + (c.context_summary or "") + " "

    print("\n[커버리지 체크 (결과.txt 기준 5개)]")
    checks = [
        ("커피 혐오 vs 커피 주문", "커피" in all_text),
        ("15분 vs 5분 이동", "15" in all_text or "5분" in all_text),
        ("10시 봉쇄 vs 11시 이동", "봉쇄" in all_text or "락다운" in all_text or "10시" in all_text),
        ("박영호 사망 후 재등장", "박영호" in all_text and ("사망" in all_text or "재등장" in all_text)),
        ("마스터키 정보 비대칭", "마스터키" in all_text),
    ]

    detected = sum(1 for _, ok in checks if ok)
    for name, ok in checks:
        status = "OK" if ok else "MISS"
        print(f"  [{status}] {name}")

    print(f"\n  탐지율: {detected}/5")
    print("=" * 60)

    return response


if __name__ == "__main__":
    asyncio.run(run())
