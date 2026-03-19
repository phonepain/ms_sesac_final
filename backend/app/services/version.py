
"""
version.py — 계층 5: 버전 관리 서비스

책임:
  1. stage_fix          — 수정 사항 스테이징 (contradiction_id + 텍스트 교체쌍)
  2. push_staged_fixes  — 일괄 반영 → 새 버전 생성 → 증분 재구축 → 모순 resolved 마킹
  3. list_versions      — 버전 이력 목록 조회
  4. get_version        — 특정 버전의 원고 내용 반환
  5. diff_versions      — 두 버전 간 텍스트 차이 (unified diff)

증분 재구축 파이프라인 (push_staged_fixes 내부):
  수정된 텍스트 영역 식별
    → 해당 청크만 계층1(Extraction) 재실행
    → 계층2(Normalization) 재실행
    → 계층3(Graph) 해당 노드/엣지만 교체
    → SearchService 재인덱싱
    → 반영된 contradiction_id들을 resolved로 마킹

스토리지 전략 (POC):
  - 스테이징 픽스: 인메모리 dict (push 후 자동 소거)
  - 버전 내용:     인메모리 dict (production은 Blob Storage로 전환)
  - 버전 메타:     VersionInfo Pydantic 모델 → 인메모리 list
"""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog

from app.models.api import VersionInfo

if TYPE_CHECKING:
    from app.models.api import DocumentChunk
    from app.services.extraction import ExtractionService
    from app.services.graph import GraphService
    from app.services.ingest import IngestService
    from app.services.normalization import NormalizationService
    from app.services.search import SearchService

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 내부 데이터 모델
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class StagedFix:
    """
    push 전 대기 중인 수정 사항 1건.

    Attributes
    ----------
    contradiction_id:
        이 수정이 해결하는 ContradictionReport의 ID
    original_text:
        원본 원고에서 교체될 텍스트 (정확히 일치해야 함)
    fixed_text:
        교체 후 텍스트
    staged_at:
        스테이징 시각 (UTC)
    """
    contradiction_id: str
    original_text: str
    fixed_text: str
    staged_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


@dataclass
class _StoredVersion:
    """
    인메모리 버전 저장소의 엔트리.
    VersionInfo(메타) + 원고 전문(content)을 함께 보관합니다.
    """
    info: VersionInfo
    content: str                    # 이 버전의 원고 전문
    source_id: str                  # 대상 Source Vertex ID
    resolved_contradiction_ids: list[str]   # 이 버전에서 해결된 모순 ID 목록


# ──────────────────────────────────────────────────────────────────────────────
# 예외
# ──────────────────────────────────────────────────────────────────────────────


class VersionError(Exception):
    """버전 관리 서비스 관련 오류의 기반 클래스."""


class NoStagedFixesError(VersionError):
    """push_staged_fixes 호출 시 fixes가 비어 있을 때."""


class VersionNotFoundError(VersionError):
    """주어진 version_id에 해당하는 버전이 없을 때."""


class OriginalTextNotFoundError(VersionError):
    """stage_fix 시 original_text가 현재 원고에서 발견되지 않을 때."""


class DuplicateStagedFixError(VersionError):
    """같은 contradiction_id로 두 번 stage_fix를 호출할 때."""


# ──────────────────────────────────────────────────────────────────────────────
# VersionService
# ──────────────────────────────────────────────────────────────────────────────


class VersionService:
    """
    계층 5: 수정 스테이징 → 일괄 Push → 증분 재구축 → 버전 관리.

    사용 예::

        svc = VersionService(graph, ingest, extraction, normalization, search)

        # 1단계: 수정 스테이징
        await svc.stage_fix(
            contradiction_id="report-uuid-001",
            original_text="A는 B가 범인이라고 말했다.",
            fixed_text="A는 B가 용의자라고 생각했다.",
        )

        # 2단계: 일괄 Push
        version_info = await svc.push_staged_fixes(
            fixes=None,   # None이면 현재 스테이징 큐 전부 사용
            source_id="source-uuid-abc",
            description="정보 비대칭 모순 2건 수정",
        )

        # 조회
        versions = await svc.list_versions()
        content  = await svc.get_version(version_info.id)
        diff     = await svc.diff_versions(versions[0].id, versions[1].id)
    """

    def __init__(
        self,
        graph_service: "GraphService",
        ingest_service: "IngestService",
        extraction_service: "ExtractionService",
        normalization_service: "NormalizationService",
        search_service: "SearchService",
    ) -> None:
        self._graph = graph_service
        self._ingest = ingest_service
        self._extraction = extraction_service
        self._normalization = normalization_service
        self._search = search_service
        self._log = logger.bind(service="VersionService")

        # 스테이징 큐: contradiction_id → StagedFix
        self._staging: dict[str, StagedFix] = {}

        # 버전 저장소: version_id → _StoredVersion
        self._versions: dict[str, _StoredVersion] = {}

        # 버전 순서 보존 리스트 (최신 → 과거 정렬용)
        self._version_order: list[str] = []

        # 버전 카운터 (v1, v2, …)
        self._version_counter: int = 0

    # ──────────────────────────────────────────────────────────────
    # 1. 수정 스테이징
    # ──────────────────────────────────────────────────────────────

    async def stage_fix(
        self,
        contradiction_id: str,
        original_text: str,
        fixed_text: str,
    ) -> StagedFix:
        """
        수정 사항을 스테이징 큐에 등록합니다.

        push_staged_fixes를 호출하기 전까지 원본 원고에는 변경이 없습니다.
        같은 contradiction_id로 중복 스테이징 시 DuplicateStagedFixError.

        Parameters
        ----------
        contradiction_id:
            이 수정이 해결하는 ContradictionReport의 ID
        original_text:
            원고에서 교체될 정확한 텍스트 문자열
        fixed_text:
            교체 후 텍스트 문자열

        Returns
        -------
        StagedFix
            등록된 스테이징 픽스 객체

        Raises
        ------
        DuplicateStagedFixError
            같은 contradiction_id가 이미 스테이징 큐에 있을 때
        ValueError
            original_text 또는 fixed_text가 빈 문자열인 경우
        """
        if not original_text.strip():
            raise ValueError("original_text는 비어 있을 수 없습니다.")
        if not fixed_text.strip():
            raise ValueError("fixed_text는 비어 있을 수 없습니다.")
        if contradiction_id in self._staging:
            raise DuplicateStagedFixError(
                f"이미 스테이징된 contradiction_id입니다: {contradiction_id}. "
                "먼저 push_staged_fixes를 실행하거나 기존 항목을 취소하세요."
            )

        fix = StagedFix(
            contradiction_id=contradiction_id,
            original_text=original_text,
            fixed_text=fixed_text,
        )
        self._staging[contradiction_id] = fix

        self._log.info(
            "fix_staged",
            contradiction_id=contradiction_id,
            original_len=len(original_text),
            fixed_len=len(fixed_text),
            queue_size=len(self._staging),
        )
        return fix

    def get_staging_queue(self) -> list[StagedFix]:
        """현재 스테이징 큐의 픽스 목록을 반환합니다 (스테이징 시각 오름차순)."""
        return sorted(self._staging.values(), key=lambda f: f.staged_at)

    def cancel_staged_fix(self, contradiction_id: str) -> None:
        """
        스테이징 큐에서 특정 픽스를 제거합니다.
        push 전에만 호출 가능합니다.
        """
        if contradiction_id not in self._staging:
            raise VersionError(f"스테이징 큐에 없는 ID입니다: {contradiction_id}")
        del self._staging[contradiction_id]
        self._log.info("staged_fix_cancelled", contradiction_id=contradiction_id)

    # ──────────────────────────────────────────────────────────────
    # 2. 일괄 Push → 증분 재구축 → 새 버전 생성
    # ──────────────────────────────────────────────────────────────

    async def push_staged_fixes(
        self,
        source_id: str,
        fixes: Optional[list[StagedFix]] = None,
        description: str = "",
    ) -> VersionInfo:
        """
        스테이징된 수정 사항을 원고에 일괄 반영하고 새 버전을 생성합니다.

        실행 순서:
        ┌─────────────────────────────────────────────────────────┐
        │ 1. 적용할 픽스 결정 (파라미터 or 큐 전체)               │
        │ 2. 원본 원고 내용 로드 (GraphService)                   │
        │ 3. 텍스트 교체 적용 (original → fixed, 순차)            │
        │ 4. 변경된 청크 식별 (IngestService 재청킹)               │
        │ 5. 변경 청크만 계층1(Extraction) 재실행                 │
        │ 6. 계층2(Normalization) 재실행                          │
        │ 7. 계층3(Graph) 해당 노드/엣지 교체                     │
        │ 8. SearchService 재인덱싱                               │
        │ 9. 반영된 contradiction_id들을 resolved로 마킹          │
        │10. 새 VersionInfo 생성 + 저장                           │
        │11. 스테이징 큐 소거                                     │
        └─────────────────────────────────────────────────────────┘

        Parameters
        ----------
        source_id:
            수정 대상 Source Vertex ID (원고 식별자)
        fixes:
            명시적 픽스 목록. None이면 현재 스테이징 큐 전부 사용.
        description:
            버전 설명 (커밋 메시지 역할)

        Returns
        -------
        VersionInfo
            새로 생성된 버전 정보

        Raises
        ------
        NoStagedFixesError
            적용할 픽스가 하나도 없을 때
        VersionError
            원고 로드, 텍스트 교체, 재구축, 마킹 중 오류 발생 시
        """
        # ── 적용할 픽스 결정 ──────────────────────────────────────
        target_fixes = fixes if fixes is not None else list(self._staging.values())
        if not target_fixes:
            raise NoStagedFixesError(
                "적용할 픽스가 없습니다. "
                "먼저 stage_fix()로 수정 사항을 등록하세요."
            )

        log = self._log.bind(
            source_id=source_id,
            fixes_count=len(target_fixes),
        )
        log.info("push_started")

        # ── Step 2: 원본 원고 내용 로드 ──────────────────────────
        original_content = await self._load_source_content(source_id, log)

        # ── Step 3: 텍스트 교체 순차 적용 ────────────────────────
        new_content, applied_fixes, failed_fixes = _apply_text_fixes(
            content=original_content,
            fixes=target_fixes,
            log=log,
        )

        if not applied_fixes:
            raise VersionError(
                "모든 픽스가 원고에서 original_text를 찾지 못해 적용에 실패했습니다. "
                f"실패 목록: {[f.contradiction_id for f in failed_fixes]}"
            )

        if failed_fixes:
            log.warning(
                "some_fixes_failed",
                failed_ids=[f.contradiction_id for f in failed_fixes],
                applied_ids=[f.contradiction_id for f in applied_fixes],
            )

        # ── Step 4: 변경된 청크 식별 ─────────────────────────────
        changed_chunks = await self._identify_changed_chunks(
            source_id=source_id,
            new_content=new_content,
            applied_fixes=applied_fixes,
            log=log,
        )
        log.info("changed_chunks_identified", count=len(changed_chunks))

        # ── Step 5~8: 증분 재구축 (계층1 → 계층2 → 계층3 → 재인덱싱) ─
        await self._run_incremental_rebuild(
            source_id=source_id,
            changed_chunks=changed_chunks,
            log=log,
        )

        # ── Step 9: contradiction_id들을 resolved로 마킹 ─────────
        resolved_ids = [f.contradiction_id for f in applied_fixes]
        await self._mark_contradictions_resolved(
            contradiction_ids=resolved_ids,
            log=log,
        )

        # ── Step 10: 새 버전 생성 ─────────────────────────────────
        version_info = self._create_version(
            source_id=source_id,
            content=new_content,
            fixes_count=len(applied_fixes),
            description=description or _auto_description(applied_fixes),
            resolved_contradiction_ids=resolved_ids,
        )

        # ── Step 11: 스테이징 큐 소거 ────────────────────────────
        applied_ids_set = {f.contradiction_id for f in applied_fixes}
        for cid in applied_ids_set:
            self._staging.pop(cid, None)

        log.info(
            "push_completed",
            version_id=version_info.id,
            version=version_info.version,
            resolved_count=len(resolved_ids),
        )
        return version_info

    # ──────────────────────────────────────────────────────────────
    # 3. 버전 목록 조회
    # ──────────────────────────────────────────────────────────────

    async def list_versions(self) -> list[VersionInfo]:
        """
        생성된 버전 이력을 최신 순으로 반환합니다.

        Returns
        -------
        list[VersionInfo]
            최신 버전이 앞, 최초 버전이 뒤에 위치
        """
        result = [
            self._versions[vid].info
            for vid in reversed(self._version_order)
            if vid in self._versions
        ]
        self._log.debug("list_versions", total=len(result))
        return result

    # ──────────────────────────────────────────────────────────────
    # 4. 특정 버전 원고 내용 조회
    # ──────────────────────────────────────────────────────────────

    async def get_version(self, version_id: str) -> str:
        """
        version_id에 해당하는 원고 전문을 반환합니다.

        Parameters
        ----------
        version_id:
            조회할 버전 ID

        Returns
        -------
        str
            해당 버전의 원고 텍스트 전문

        Raises
        ------
        VersionNotFoundError
            해당 ID의 버전이 없을 때
        """
        stored = self._versions.get(version_id)
        if stored is None:
            raise VersionNotFoundError(f"버전을 찾을 수 없습니다: id={version_id}")
        self._log.debug("get_version", version_id=version_id, version=stored.info.version)
        return stored.content

    # ──────────────────────────────────────────────────────────────
    # 5. 두 버전 간 diff
    # ──────────────────────────────────────────────────────────────

    async def diff_versions(
        self,
        version_id_a: str,
        version_id_b: str,
        context_lines: int = 3,
    ) -> str:
        """
        두 버전 간의 텍스트 차이를 unified diff 형식으로 반환합니다.

        Parameters
        ----------
        version_id_a:
            비교 기준 버전 (구 버전)
        version_id_b:
            비교 대상 버전 (신 버전)
        context_lines:
            diff 컨텍스트 줄 수 (기본 3)

        Returns
        -------
        str
            unified diff 문자열.
            두 버전이 동일하면 빈 문자열 반환.

        Raises
        ------
        VersionNotFoundError
            두 ID 중 하나라도 존재하지 않을 때
        """
        content_a = await self.get_version(version_id_a)
        content_b = await self.get_version(version_id_b)

        info_a = self._versions[version_id_a].info
        info_b = self._versions[version_id_b].info

        lines_a = content_a.splitlines(keepends=True)
        lines_b = content_b.splitlines(keepends=True)

        diff_lines = list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=f"{info_a.version} ({version_id_a})",
                tofile=f"{info_b.version} ({version_id_b})",
                fromfiledate=info_a.date,
                tofiledate=info_b.date,
                n=context_lines,
            )
        )

        diff_text = "".join(diff_lines)
        self._log.info(
            "diff_versions",
            version_a=info_a.version,
            version_b=info_b.version,
            changed_lines=len(diff_lines),
        )
        return diff_text

    # ──────────────────────────────────────────────────────────────
    # Private: 원고 내용 로드
    # ──────────────────────────────────────────────────────────────

    async def _load_source_content(
        self,
        source_id: str,
        log: structlog.BoundLogger,
    ) -> str:
        """
        GraphService를 통해 Source Vertex의 원고 내용을 불러옵니다.

        VersionService는 원본 파일에 직접 접근하지 않습니다.
        항상 GraphService를 경유하여 Source 메타데이터에서 내용을 획득합니다.
        이를 통해 Azure Blob Storage, 로컬 파일, 인메모리를 동일 인터페이스로 처리합니다.
        """
        try:
            raw = await self._graph.get_vertex(
                vertex_id=source_id,
                partition_key="source",
            )
        except Exception as exc:
            raise VersionError(f"원고 로드 실패 (source_id={source_id}): {exc}") from exc

        if raw is None:
            raise VersionError(f"Source Vertex를 찾을 수 없습니다: source_id={source_id}")

        content = raw.get("content") or raw.get("raw_content") or ""
        if not content:
            raise VersionError(
                f"Source에 원고 내용이 없습니다 (source_id={source_id}). "
                "ingest 시 content 필드가 저장되어 있어야 합니다."
            )

        log.debug("source_content_loaded", chars=len(content))
        return content

    # ──────────────────────────────────────────────────────────────
    # Private: 변경 청크 식별
    # ──────────────────────────────────────────────────────────────

    async def _identify_changed_chunks(
        self,
        source_id: str,
        new_content: str,
        applied_fixes: list[StagedFix],
        log: structlog.BoundLogger,
    ) -> list["DocumentChunk"]:
        """
        수정이 적용된 텍스트 영역이 포함된 청크만 선별합니다.

        전략:
        - IngestService로 new_content를 재청킹
        - 각 청크가 fixed_text를 포함하면 '변경된 청크'로 분류
        - 오버랩(100토큰) 때문에 인접 청크도 함께 포함될 수 있으나,
          이는 의도된 동작입니다 (맥락 유지).

        완전 재처리 대비 장점:
        - 변경 없는 청크의 계층1~3을 건너뛰어 처리 비용 절감
        - 원고 규모가 클수록 효과가 커집니다.
        """
        try:
            all_chunks: list["DocumentChunk"] = await self._ingest.rechunk_content(
                source_id=source_id,
                content=new_content,
            )
        except Exception as exc:
            log.warning(
                "rechunk_failed_fallback_all",
                error=str(exc),
                detail="재청킹 실패. 전체 청크를 변경 대상으로 처리합니다.",
            )
            return all_chunks if "all_chunks" in dir() else []

        # fixed_text를 포함하는 청크만 선별
        fixed_texts = {fix.fixed_text for fix in applied_fixes}
        changed: list["DocumentChunk"] = []
        for chunk in all_chunks:
            if any(ft in chunk.content for ft in fixed_texts):
                changed.append(chunk)

        # 변경 청크가 하나도 없으면 전체 반환 (안전 장치)
        if not changed:
            log.warning(
                "no_changed_chunks_detected",
                detail="fixed_text를 포함하는 청크를 찾지 못했습니다. "
                       "전체 청크를 변경 대상으로 처리합니다.",
            )
            return all_chunks

        return changed

    # ──────────────────────────────────────────────────────────────
    # Private: 증분 재구축 (계층1 → 계층2 → 계층3 → 재인덱싱)
    # ──────────────────────────────────────────────────────────────

    async def _run_incremental_rebuild(
        self,
        source_id: str,
        changed_chunks: list["DocumentChunk"],
        log: structlog.BoundLogger,
    ) -> None:
        """
        변경된 청크에 대해서만 계층1~3을 순차 재실행합니다.

        계층1 (Extraction):
          변경 청크별로 LLM 추출 재실행.
          이전에 해당 청크에서 추출된 엔티티는 GraphService를 통해 제거 후 재적재.

        계층2 (Normalization):
          재추출된 RawEntity를 정규화·통합.
          기존 canonical graph와 병합 (중복 제거).

        계층3 (Graph):
          NormalizationResult를 그래프에 반영.
          변경된 청크 기반의 이전 Vertex/Edge를 먼저 삭제하고 새로 적재.
          discourse_order는 원래 값 유지 (텍스트 순서 변동 없음).

        SearchService:
          변경 청크를 재인덱싱하여 원본 발췌 검색 정확도 유지.
        """
        if not changed_chunks:
            log.debug("no_changed_chunks_skip_rebuild")
            return

        chunk_ids = [c.id for c in changed_chunks]
        log.info("incremental_rebuild_start", chunk_count=len(changed_chunks))

        # ── 계층1: Extraction ─────────────────────────────────────
        log.info("rebuild_layer1_extraction")
        try:
            extraction_results = await self._extraction.extract_from_chunks(changed_chunks)
        except Exception as exc:
            raise VersionError(f"계층1 재추출 실패: {exc}") from exc

        # ── 이전 청크 기반 그래프 데이터 제거 ─────────────────────
        # 재추출 전에 기존 엔티티를 지워야 중복 적재를 방지합니다.
        log.info("removing_old_chunk_data")
        try:
            await self._graph.remove_vertices_by_chunk_ids(chunk_ids)
        except Exception as exc:
            log.warning("remove_old_vertices_failed", error=str(exc))

        # ── 계층2: Normalization ──────────────────────────────────
        log.info("rebuild_layer2_normalization")
        try:
            normalization_result = await self._normalization.normalize(extraction_results)
        except Exception as exc:
            raise VersionError(f"계층2 정규화 실패: {exc}") from exc

        # ── 계층3: Graph Materialization ──────────────────────────
        log.info("rebuild_layer3_graph")
        try:
            # Source Vertex를 가져와 materialize에 전달
            source_raw = await self._graph.get_vertex(
                vertex_id=source_id, partition_key="source"
            )
            await self._graph.materialize(
                normalized=normalization_result,
                source=source_raw,
            )
        except Exception as exc:
            raise VersionError(f"계층3 그래프 재적재 실패: {exc}") from exc

        # ── SearchService 재인덱싱# ── SearchService 재인덱싱 ────────────────────────────────
        log.info("rebuild_search_reindex")
        try:
            await self._search.index_chunks(source_id=source_id, chunks=changed_chunks)
        except Exception as exc:
            # 재인덱싱 실패는 그래프 무결성에 영향 없음 → 경고만
            log.warning("search_reindex_failed", error=str(exc))

        log.info("incremental_rebuild_complete")

    # ──────────────────────────────────────────────────────────────
    # Private: 모순 resolved 마킹
    # ──────────────────────────────────────────────────────────────

    async def _mark_contradictions_resolved(
        self,
        contradiction_ids: list[str],
        log: structlog.BoundLogger,
    ) -> None:
        """
        수정이 반영된 ContradictionReport들을 resolved로 마킹합니다.

        ContradictionReport는 Source Vertex와 별개로 그래프에 저장된
        Vertex입니다. patch_vertex로 status 필드만 교체합니다.

        마킹 실패 시 전체 push를 중단하지 않고 경고만 기록합니다.
        (버전 자체는 이미 생성됐으므로 원고 수정은 유효합니다.)
        """
        for cid in contradiction_ids:
            try:
                await self._graph.patch_vertex(
                    vertex_id=cid,
                    partition_key="contradiction",
                    fields={"status": "resolved"},
                )
                log.info("contradiction_resolved", contradiction_id=cid)
            except Exception as exc:
                log.warning(
                    "contradiction_mark_failed",
                    contradiction_id=cid,
                    error=str(exc),
                )

    # ──────────────────────────────────────────────────────────────
    # Private: 버전 생성 + 저장
    # ──────────────────────────────────────────────────────────────

    def _create_version(
        self,
        source_id: str,
        content: str,
        fixes_count: int,
        description: str,
        resolved_contradiction_ids: list[str],
    ) -> VersionInfo:
        """
        새 VersionInfo를 생성하고 인메모리 저장소에 등록합니다.

        version 문자열은 "v1", "v2" … 형식으로 단조 증가합니다.
        """
        self._version_counter += 1
        version_id = str(uuid.uuid4())
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        info = VersionInfo(
            id=version_id,
            version=f"v{self._version_counter}",
            date=now_iso,
            fixes_count=fixes_count,
            description=description,
        )

        stored = _StoredVersion(
            info=info,
            content=content,
            source_id=source_id,
            resolved_contradiction_ids=resolved_contradiction_ids,
        )

        self._versions[version_id] = stored
        self._version_order.append(version_id)

        self._log.info(
            "version_created",
            version_id=version_id,
            version=info.version,
            fixes_count=fixes_count,
        )
        return info


# ──────────────────────────────────────────────────────────────────────────────
# 모듈 레벨 순수 함수 (테스트 용이성)
# ──────────────────────────────────────────────────────────────────────────────


def _apply_text_fixes(
    content: str,
    fixes: list[StagedFix],
    log: structlog.BoundLogger,
) -> tuple[str, list[StagedFix], list[StagedFix]]:
    """
    원고 텍스트에 픽스를 순차 적용합니다.

    적용 순서:
    - 픽스 간 충돌 방지를 위해 staged_at 오름차순(선입선출)으로 적용합니다.
    - 한 픽스의 fixed_text가 다음 픽스의 original_text와 겹치는 경우는
      POC 범위에서 사용자 책임으로 처리합니다.

    Parameters
    ----------
    content:
        원본 원고 텍스트
    fixes:
        적용할 StagedFix 목록
    log:
        structlog 바운드 로거

    Returns
    -------
    (새 원고 텍스트, 성공한 픽스 목록, 실패한 픽스 목록)
    """
    current = content
    applied: list[StagedFix] = []
    failed: list[StagedFix] = []

    # 선입선출: staged_at 오름차순
    for fix in sorted(fixes, key=lambda f: f.staged_at):
        if fix.original_text not in current:
            log.warning(
                "fix_original_not_found",
                contradiction_id=fix.contradiction_id,
                original_preview=fix.original_text[:80],
            )
            failed.append(fix)
            continue

        # 첫 번째 일치 항목만 교체 (의도치 않은 전역 교체 방지)
        current = current.replace(fix.original_text, fix.fixed_text, 1)
        applied.append(fix)
        log.debug(
            "fix_applied",
            contradiction_id=fix.contradiction_id,
        )

    return current, applied, failed


def _auto_description(applied_fixes: list[StagedFix]) -> str:
    """
    description이 없을 때 자동으로 버전 설명을 생성합니다.

    Examples
    --------
    >>> _auto_description([fix1])
    'contradiction report-001 수정 반영'

    >>> _auto_description([fix1, fix2, fix3])
    '모순 3건 수정 반영 (report-001, report-002, report-003)'
    """
    if not applied_fixes:
        return "수정 사항 없음"

    ids = [f.contradiction_id for f in applied_fixes]
    if len(ids) == 1:
        return f"contradiction {ids[0]} 수정 반영"

    id_summary = ", ".join(ids[:3])
    suffix = f" 외 {len(ids) - 3}건" if len(ids) > 3 else ""
    return f"모순 {len(ids)}건 수정 반영 ({id_summary}{suffix})"
