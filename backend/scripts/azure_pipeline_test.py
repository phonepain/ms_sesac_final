"""
Azure 실제 파이프라인 테스트 — Phase 1~4
Blob Storage + Cosmos DB + AI Search + Azure OpenAI 전부 실제 연결
"""
import asyncio
import time
import sys
import os
import io
import concurrent.futures

# Windows 콘솔 UTF-8 강제
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# .env 그대로 사용 (mock 오버라이드 없음)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.services.storage import get_global_storage
from app.services.ingest import IngestService
from app.services.extraction import ExtractionService
from app.services.normalization import NormalizationService
from app.services.graph import get_graph_service
from app.services.search import get_search_service
from app.services.detection import DetectionService
from app.models.vertices import Source
from app.models.enums import SourceType

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "../../data/sample")

SAMPLES = [
    ("세계관_그림자의비밀.txt",  "worldview"),
    ("설정집_그림자의비밀.txt",  "settings"),
    ("시나리오_그림자의비밀.txt","scenario"),
]

SEP  = "=" * 65
DASH = "-" * 65

def log(msg=""):
    print(msg, flush=True)

def log_ok(label, elapsed):
    print(f"  OK  [{elapsed:.2f}s] {label}", flush=True)

def log_err(label, e):
    print(f"  ERR [{label}] {type(e).__name__}: {e}", flush=True)


async def run():
    log(SEP)
    log("Phase 1~4  Azure 실제 파이프라인 테스트")
    log(SEP)
    log(f"  Storage   : USE_LOCAL_STORAGE={settings.use_local_storage}  (False=Blob)")
    log(f"  Graph     : USE_LOCAL_GRAPH={settings.use_local_graph}    (False=Cosmos DB)")
    log(f"  Search    : USE_MOCK_SEARCH={settings.use_mock_search}    (False=AI Search)")
    log()

    storage       = get_global_storage()
    ingest        = IngestService(storage=storage)
    extraction    = ExtractionService()
    normalization = NormalizationService()
    graph         = get_graph_service()
    search        = get_search_service()
    detection     = DetectionService()

    log(f"  Storage   : {type(storage).__name__}")
    log(f"  Graph     : {type(graph).__name__}")
    log(f"  Search    : {type(search).__name__}")
    log(f"  Extraction: use_mock={extraction.use_mock}")
    log(f"  Normalize : use_mock={normalization.use_mock}")
    log()

    all_extractions = []
    source_objects  = []
    uploaded_meta   = []   # (source_id, stype, filename, file_path)

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 1-1] Blob Storage - 파일 업로드")
    log(DASH)

    for filename, stype in SAMPLES:
        path = os.path.join(SAMPLE_DIR, filename)
        with open(path, "rb") as f:
            content = f.read()

        source_id = f"azure-test-{stype}"
        log(f"  >> {filename}  ({len(content):,} bytes)  source_id={source_id}")
        t0 = time.time()
        try:
            file_path = await storage.save_file(content, filename, source_id, stype)
            log_ok(f"Blob 업로드 완료  path={file_path}", time.time() - t0)
            uploaded_meta.append((source_id, stype, filename, file_path, content))
        except Exception as e:
            log_err(filename, e)
            raise
    log()

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 1-2] IngestService - 파싱 / 청킹")
    log(DASH)

    all_chunks_map = {}
    for source_id, stype, filename, file_path, content in uploaded_meta:
        log(f"  >> {filename} [{stype}] 청킹 중...")
        t0 = time.time()
        try:
            ingest_res = await ingest.process_file(content, filename, source_id, stype)
            chunks = ingest_res.chunks
            log_ok(f"{len(chunks)}개 청크 생성", time.time() - t0)
            for i, chunk in enumerate(chunks):
                preview = chunk.content[:50].replace("\n", " ").strip()
                log(f"     chunk[{i}]  {len(chunk.content):>5}자  \"{preview}...\"")
            all_chunks_map[source_id] = (chunks, stype, filename, file_path)
        except Exception as e:
            log_err(filename, e)
            raise
    log()

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 1-3] ExtractionService - LLM 엔티티 추출")
    log(DASH)

    for source_id, (chunks, stype, filename, file_path) in all_chunks_map.items():
        log(f"  >> {filename} [{stype}]  {len(chunks)}개 청크 → LLM 추출 중...")
        t0 = time.time()
        try:
            extractions = await extraction.extract_from_chunks(chunks, stype)
            elapsed = time.time() - t0

            chars  = sum(len(e.characters)       for e in extractions)
            facts  = sum(len(e.facts)            for e in extractions)
            events = sum(len(e.events)           for e in extractions)
            traits = sum(len(e.traits)           for e in extractions)
            rels   = sum(len(e.relationships)    for e in extractions)
            emos   = sum(len(e.emotions)         for e in extractions)
            ke     = sum(len(e.knowledge_events) for e in extractions)
            ie     = sum(len(e.item_events)      for e in extractions)

            log_ok(f"추출 완료", elapsed)
            log(f"     chars={chars}  facts={facts}  events={events}  traits={traits}")
            log(f"     rels={rels}  emotions={emos}  knowledge_events={ke}  item_events={ie}")

            for e in extractions:
                if e.characters:
                    log(f"     캐릭터명: {[c.name for c in e.characters]}")
                if e.facts:
                    log(f"     사실(최대3): {[f.content[:35] for f in e.facts[:3]]}")
                if e.events:
                    log(f"     이벤트(최대3): {[ev.description[:35] for ev in e.events[:3]]}")
                if e.traits:
                    log(f"     특성(최대3): {[(t.character_name, t.key, t.value) for t in e.traits[:3]]}")
                if e.knowledge_events:
                    log(f"     지식이벤트(최대3): {[(k.character_name, k.fact_content[:25]) for k in e.knowledge_events[:3]]}")

            all_extractions.extend(extractions)
            source_objects.append(Source(
                source_id=source_id,
                source_type=SourceType[stype.upper()],
                name=filename,
                file_path=file_path,
            ))
        except Exception as e:
            log_err(filename, e)
            raise
    log()

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 1-4] SearchService - Azure AI Search 인덱싱")
    log(DASH)

    for source_id, (chunks, stype, filename, file_path) in all_chunks_map.items():
        log(f"  >> {filename}  {len(chunks)}개 청크 인덱싱 중...")
        t0 = time.time()
        try:
            await search.index_chunks(source_id, chunks)
            log_ok(f"인덱싱 완료", time.time() - t0)
        except Exception as e:
            log_err(filename, e)
            log("     (Search 실패는 비치명적 — 계속 진행)")
    log()

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 2] NormalizationService - 캐릭터 통합 / 사실 병합")
    log(DASH)

    log(f"  >> {len(all_extractions)}개 ExtractionResult 정규화 중...")
    t0 = time.time()
    try:
        norm = await normalization.normalize(all_extractions)
        log_ok("정규화 완료", time.time() - t0)
        log(f"     캐릭터   : {len(norm.characters)}명  → {[c.canonical_name for c in norm.characters]}")
        log(f"     사실     : {len(norm.facts)}건")
        log(f"     이벤트   : {len(norm.events)}건")
        log(f"     특성     : {len(norm.traits)}건")
        log(f"     관계     : {len(norm.relationships)}건")
        log(f"     감정     : {len(norm.emotions)}건")
        log(f"     소유이벤트: {len(norm.item_events)}건")
        log(f"     지식이벤트: {len(norm.knowledge_events)}건")
        log(f"     소스충돌  : {len(norm.source_conflicts)}건")
        if norm.source_conflicts:
            for sc in norm.source_conflicts:
                log(f"       충돌: {sc.entity_type}  {sc.conflicting_values}")
    except Exception as e:
        log_err("NormalizationService", e)
        raise
    log()

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 3] GraphService - Cosmos DB (Gremlin) 적재")
    log(DASH)

    # GremlinGraphService는 내부적으로 동기 Gremlin 클라이언트를 사용하므로
    # asyncio 루프 충돌을 피하기 위해 ThreadPoolExecutor로 분리 실행
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        for src in source_objects:
            log(f"  >> [{src.source_type.value}] {src.name} materialize 중...")
            t0 = time.time()
            try:
                created = await loop.run_in_executor(pool, graph.materialize, norm, src)
                elapsed = time.time() - t0
                total_items = sum(len(v) for v in created.values() if isinstance(v, list))
                log_ok(f"{total_items}개 항목 적재", elapsed)
                for category, items in created.items():
                    if isinstance(items, list) and items:
                        log(f"     {category:20s}: {len(items):3d}개")
            except Exception as e:
                log_err(src.name, e)
                raise
    log()

    log("  >> Cosmos DB 최종 통계 조회 중...")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        stats = await loop.run_in_executor(pool, graph.get_stats)
    log_ok("통계 조회 완료", time.time() - t0)
    log(f"     characters   : {stats.characters}")
    log(f"     facts        : {stats.facts}")
    log(f"     events       : {stats.events}")
    log(f"     traits       : {stats.traits}")
    log(f"     relationships: {stats.relationships}")
    log(f"     sources      : {stats.sources}")
    log()

    # ──────────────────────────────────────────────────────
    log(DASH)
    log("[PHASE 4] DetectionService - 모순 탐지 (스냅샷 격리)")
    log(DASH)

    log("  >> 스냅샷 격리 (canonical graph 보호)...")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        snapshot = await loop.run_in_executor(pool, graph.snapshot_graph)
    log_ok("스냅샷 완료", time.time() - t0)

    log("  >> 7가지 위반 쿼리 실행 중...")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        violations = await loop.run_in_executor(pool, snapshot.find_all_violations)
    total_v = sum(len(v) for v in violations.values())
    log_ok(f"위반 쿼리 완료  총 {total_v}건 감지", time.time() - t0)
    for vtype, items in violations.items():
        if items:
            log(f"     {vtype}: {len(items)}건")

    log()
    log("  >> LLM 검증 및 Hard/Soft 분류 중...")
    t0 = time.time()
    analysis = await detection.analyze(violations)
    elapsed = time.time() - t0

    hard = [c for c in analysis.contradictions if c.hard_or_soft == "hard"]
    soft = [c for c in analysis.contradictions if c.hard_or_soft == "soft"]
    log_ok("탐지 완료", elapsed)
    log(f"     HARD 모순        : {len(hard)}건")
    log(f"     SOFT 모순(자동)  : {len(soft)}건")
    log(f"     사용자 확인 필요 : {len(analysis.confirmations)}건")

    if analysis.contradictions:
        log()
        log("  [탐지된 모순 목록]")
        for c in analysis.contradictions:
            log(f"     [{c.hard_or_soft.upper()}][{c.severity}] {c.type}")
            log(f"       설명: {c.description[:70]}")
            if c.suggestion:
                log(f"       제안: {c.suggestion[:60]}")

    if analysis.confirmations:
        log()
        log("  [사용자 확인 필요 목록]")
        for conf in analysis.confirmations:
            log(f"     [{conf.confirmation_type}] {conf.question[:65]}")

    # ──────────────────────────────────────────────────────
    log()
    log(SEP)
    log("Phase 1~4 Azure 파이프라인 완료")
    log(SEP)
    log()
    log("  업로드된 source_id 목록 (정리 시 사용):")
    for source_id, stype, filename, file_path, _ in uploaded_meta:
        log(f"    source_id={source_id}  file_path={file_path}")


if __name__ == "__main__":
    asyncio.run(run())
