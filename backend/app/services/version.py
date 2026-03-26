"""
version.py — 계층 5: 버전 관리 서비스 (StorageService 연동)

책임:
  1. stage_fix          — 수정 사항 스테이징 (contradiction_id + 텍스트 교체쌍)
  2. push_staged_fixes  — 일괄 반영 → 버전 스냅샷 저장 → 새 버전 생성
                           → 증분 재구축 → 모순 resolved 마킹
  3. list_versions      — 버전 이력 목록 조회
  4. get_version        — 특정 버전의 원고 내용 반환 (StorageService 위임)
  5. diff_versions      — 두 버전 간 텍스트 차이 반환 (StorageService 위임)

증분 재구축 파이프라인 (push_staged_fixes 내부):
  수정된 텍스트 영역 식별
    → 해당 청크만 계층1(Extraction) 재실행
    → 계층2(Normalization) 재실행
    → 계층3(Graph) 해당 노드/엣지만 교체
    → SearchService 재인덱싱
    → 반영된 contradiction_id들을 resolved로 마킹

스토리지 전략 (POC):
  - 스테이징 픽스: 인메모리 dict (push 후 자동 소거)
  - 버전 본문:     StorageService가 관리 (로컬 파일/Blob Storage)
  - 버전 메타:     VersionInfo Pydantic 모델 → 인메모리 dict/list
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog

from app.models.api import VersionInfo
from app.models.vertices import Source

if TYPE_CHECKING:
    from app.models.api import DocumentChunk
    from app.services.extraction import ExtractionService
    from app.services.graph import GraphService
    from app.services.ingest import IngestService
    from app.services.normalization import NormalizationService
    from app.services.search import SearchService
    from app.services.storage import StorageService

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
        원본 원고에서 교체될 텍스트 (정확히 일치해야 함, is_intentional=True면 빈 문자열 가능)
    fixed_text:
        교체 후 텍스트 (is_intentional=True면 빈 문자열 가능)
    is_intentional:
        True이면 작가 의도로 인정 — 텍스트 교체 없이 resolved 마킹만 수행
    intent_note:
        의도 인정 시 작가의 메모
    staged_at:
        스테이징 시각 (UTC)
    """

    contradiction_id: str
    original_text: str
    fixed_text: str
    is_intentional: bool = False
    intent_note: str = ""
    chunk_id: str = ""
    staged_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


@dataclass
class _StoredVersion:
    """
    버전 메타 저장소의 엔트리.

    원고 전문(content)은 StorageService가 관리합니다.
    VersionService는 VersionInfo + source_id + 해결된 모순 ID만 보관합니다.
    """

    info: VersionInfo
    source_id: str
    resolved_contradiction_ids: list[str]


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
    계층 5: 수정 스테이징 → 일괄 Push → 버전 스냅샷 저장 → 증분 재구축 → 버전 관리.

    사용 예::

        svc = VersionService(
            graph_service=graph,
            ingest_service=ingest,
            extraction_service=extraction,
            normalization_service=normalization,
            search_service=search,
            storage_service=storage,
        )

        await svc.stage_fix(
            contradiction_id="report-uuid-001",
            original_text="A는 B가 범인이라고 말했다.",
            fixed_text="A는 B가 용의자라고 생각했다.",
        )

        version_info = await svc.push_staged_fixes(
            source_id="source-uuid-abc",
            fixes=None,
            description="정보 비대칭 모순 2건 수정",
        )

        versions = await svc.list_versions()
        content = await svc.get_version(version_info.id)
        diff = await svc.diff_versions(versions[1].id, versions[0].id)
    """

    def __init__(
        self,
        graph_service: "GraphService",
        ingest_service: "IngestService",
        extraction_service: "ExtractionService",
        normalization_service: "NormalizationService",
        search_service: "SearchService",
        storage_service: "StorageService",
        confirmation_service: "ConfirmationService | None" = None,
    ) -> None:
        self._graph = graph_service
        self._ingest = ingest_service
        self._extraction = extraction_service
        self._normalization = normalization_service
        self._search = search_service
        self._storage = storage_service
        self._confirmation = confirmation_service
        self._log = logger.bind(service="VersionService")

        # 스테이징 큐: contradiction_id → StagedFix
        self._staging: dict[str, StagedFix] = {}

        # 버전 메타 저장소: version_id → _StoredVersion
        self._versions: dict[str, _StoredVersion] = {}

        # 버전 순서 보존 리스트 (과거 → 최신 append)
        self._version_order: list[str] = []

        # 버전 카운터 (v1, v2, …)
        self._version_counter: int = 0

    # ──────────────────────────────────────────────────────────────
    # 내부 유틸: sync 그래프 호출을 thread pool에서 실행
    # ──────────────────────────────────────────────────────────────

    async def _run_graph(self, func, *args, **kwargs):
        """동기 GraphService 메서드를 ThreadPoolExecutor에서 실행한다.
        async 컨텍스트에서 Gremlin sync 호출 시 이벤트 루프 충돌을 방지한다.
        """
        loop = asyncio.get_event_loop()
        if kwargs:
            return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
        return await loop.run_in_executor(None, func, *args)

    # ──────────────────────────────────────────────────────────────
    # 1. 수정 스테이징
    # ──────────────────────────────────────────────────────────────

    async def stage_fix(
        self,
        contradiction_id: str,
        original_text: str = "",
        fixed_text: str = "",
        is_intentional: bool = False,
        intent_note: str = "",
        chunk_id: str = "",
    ) -> StagedFix:
        """
        수정 사항을 스테이징 큐에 등록합니다.

        push_staged_fixes를 호출하기 전까지 원본 원고에는 변경이 없습니다.
        같은 contradiction_id로 중복 스테이징 시 DuplicateStagedFixError.
        is_intentional=True이면 original_text/fixed_text 검증을 건너뜁니다.
        """
        if not is_intentional:
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
            is_intentional=is_intentional,
            intent_note=intent_note,
            chunk_id=chunk_id,
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
        """스테이징 큐에서 특정 픽스를 제거합니다."""
        if contradiction_id not in self._staging:
            raise VersionError(f"스테이징 큐에 없는 ID입니다: {contradiction_id}")
        del self._staging[contradiction_id]
        self._log.info("staged_fix_cancelled", contradiction_id=contradiction_id)

    # ──────────────────────────────────────────────────────────────
    # 2. 일괄 Push → 스냅샷 저장 → 증분 재구축 → 새 버전 생성
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
        1. 적용할 픽스 결정 (파라미터 or 큐 전체)
        2. 현재 원고 텍스트 로드 (StorageService.get_file_text)
        3. 텍스트 교체 적용
        4. 버전 스냅샷 저장 (StorageService.save_version_snapshot)
        5. Source vertex의 file_path를 최신 스냅샷 경로로 업데이트
        6. 변경된 청크 식별
        7. 변경 청크만 계층1~3 재실행 + Search 재인덱싱
        8. 반영된 contradiction_id들을 resolved로 마킹
        9. 새 VersionInfo 생성 + 저장
        10. 스테이징 큐 소거
        """
        target_fixes = fixes if fixes is not None else list(self._staging.values())
        if not target_fixes:
            raise NoStagedFixesError(
                "적용할 픽스가 없습니다. 먼저 stage_fix()로 수정 사항을 등록하세요."
            )

        log = self._log.bind(
            source_id=source_id,
            fixes_count=len(target_fixes),
        )
        log.info("push_started")

        # Step 2: 현재 원고 로드 (StorageService)
        original_content = await self._load_source_content(source_id, log)

        # Step 3: 텍스트 교체
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

        # Step 4: 버전 스냅샷 저장
        self._version_counter += 1
        version_id = str(uuid.uuid4())
        version_name = f"v{self._version_counter}"

        try:
            snapshot_path = await self._storage.save_version_snapshot(
                source_id=source_id,
                version=version_name,
                content=new_content,
            )
        except Exception as exc:
            raise VersionError(f"버전 스냅샷 저장 실패: {exc}") from exc

        log.info(
            "version_snapshot_saved",
            version_id=version_id,
            version=version_name,
            snapshot_path=snapshot_path,
        )

        # Step 5: Source vertex의 file_path를 최신 스냅샷 경로로 업데이트
        try:
            await self._run_graph(
                self._graph.patch_vertex,
                source_id,
                "source",
                {"file_path": snapshot_path},
            )
        except Exception as exc:
            raise VersionError(
                f"Source.file_path 업데이트 실패 (source_id={source_id}): {exc}"
            ) from exc

        log.info("source_file_path_updated", source_id=source_id, file_path=snapshot_path)

        # Step 6: 변경 청크 식별
        changed_chunks, all_chunks = await self._identify_changed_chunks(
            source_id=source_id,
            new_content=new_content,
            applied_fixes=applied_fixes,
            log=log,
        )
        log.info("changed_chunks_identified", changed=len(changed_chunks), total=len(all_chunks))

        # Step 7: 증분 재구축 (그래프: changed_chunks, Search: all_chunks)
        rebuild_errors = await self._run_incremental_rebuild(
            source_id=source_id,
            changed_chunks=changed_chunks,
            all_chunks=all_chunks,
            log=log,
        )

        # Step 8-a: is_intentional 픽스 → ConfirmationService.resolve() 호출
        # (Step 8-b의 _mark_contradictions_resolved보다 먼저 실행 —
        #  resolve()가 status를 confirmed_intentional로 변경하므로)
        intentional_ids: set[str] = set()
        if self._confirmation:
            for fix in applied_fixes:
                if fix.is_intentional:
                    try:
                        await self._confirmation.resolve(
                            confirmation_id=str(fix.contradiction_id),
                            user_response=fix.intent_note or "의도된 설정으로 인정",
                            decision="confirmed_intentional",
                        )
                        intentional_ids.add(str(fix.contradiction_id))
                        log.info("intentional_confirmation_resolved",
                                 confirmation_id=fix.contradiction_id)
                    except Exception as _exc:
                        # Hard contradiction ID이거나 이미 resolved된 경우 스킵
                        log.debug("confirmation_resolve_skipped",
                                  id=fix.contradiction_id, error=str(_exc))

        # Step 8-b: 나머지 contradiction_id들을 resolved로 마킹
        # (intentional 처리된 것은 이미 ConfirmationService가 처리했으므로 제외)
        resolved_ids = [
            f.contradiction_id for f in applied_fixes
            if str(f.contradiction_id) not in intentional_ids
        ]
        if resolved_ids:
            await self._mark_contradictions_resolved(
                contradiction_ids=resolved_ids,
                log=log,
            )

        # Step 9: 버전 메타 생성 + 저장
        source_vertex = await self._run_graph(self._graph.get_vertex, source_id, "source")
        source_name = (source_vertex or {}).get("name", "")

        version_info = self._create_version(
            version_id=version_id,
            version_name=version_name,
            source_id=source_id,
            fixes_count=len(applied_fixes),
            description=description or _auto_description(applied_fixes),
            resolved_contradiction_ids=resolved_ids,
            snapshot_path=snapshot_path,
            src=source_name,
            pipeline_errors=rebuild_errors,
        )

        # Step 10: 스테이징 큐 소거
        for cid in {fix.contradiction_id for fix in applied_fixes}:
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

        실제 본문은 StorageService가 보관하므로,
        VersionService는 source_id 조회 후 StorageService에 위임합니다.
        """
        stored = self._versions.get(version_id)
        if stored is None:
            raise VersionNotFoundError(f"버전을 찾을 수 없습니다: id={version_id}")

        self._log.debug(
            "get_version",
            version_id=version_id,
            version=stored.info.version,
            source_id=stored.source_id,
        )

        try:
            return await self._storage.get_version_content(
                source_id=stored.source_id,
                version=stored.info.version,
            )
        except Exception as exc:
            raise VersionError(
                f"버전 내용 조회 실패 (version_id={version_id}): {exc}"
            ) from exc

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
        두 버전 간의 텍스트 차이를 반환합니다.

        diff 생성은 StorageService에 위임합니다.
        context_lines는 기존 시그니처 호환용으로 남겨두며,
        현재 StorageService 구현이 내부 기본값을 사용한다고 가정합니다.
        """
        stored_a = self._versions.get(version_id_a)
        stored_b = self._versions.get(version_id_b)

        if stored_a is None:
            raise VersionNotFoundError(f"버전을 찾을 수 없습니다: id={version_id_a}")
        if stored_b is None:
            raise VersionNotFoundError(f"버전을 찾을 수 없습니다: id={version_id_b}")

        if stored_a.source_id != stored_b.source_id:
            raise VersionError("서로 다른 source의 버전은 비교할 수 없습니다.")

        if context_lines != 3:
            self._log.debug(
                "diff_context_lines_ignored",
                version_a=version_id_a,
                version_b=version_id_b,
                context_lines=context_lines,
            )

        try:
            diff_text = await self._storage.diff_version_content(
                version_a=stored_a.info.version,
                version_b=stored_b.info.version,
                source_id=stored_a.source_id,
            )
        except Exception as exc:
            raise VersionError(
                f"버전 diff 조회 실패 ({version_id_a} vs {version_id_b}): {exc}"
            ) from exc

        self._log.info(
            "diff_versions",
            version_a=stored_a.info.version,
            version_b=stored_b.info.version,
        )
        return diff_text

    # ──────────────────────────────────────────────────────────────
    # Private: 현재 원고 내용 로드
    # ──────────────────────────────────────────────────────────────

    async def _load_source_content(
        self,
        source_id: str,
        log: structlog.BoundLogger,
    ) -> str:
        """
        StorageService를 통해 현재 원고 텍스트를 불러옵니다.
        """
        try:
            source_vertex = await self._run_graph(self._graph.get_vertex, source_id, "source")
            if source_vertex is None:
                raise VersionError(f"Source vertex를 찾을 수 없습니다: source_id={source_id}")
            file_path = source_vertex.get("file_path", "")
            if not file_path:
                raise VersionError(f"Source vertex에 file_path가 없습니다: source_id={source_id}")
            content = await self._storage.get_file_text(file_path)
        except VersionError:
            raise
        except Exception as exc:
            raise VersionError(f"원고 로드 실패 (source_id={source_id}): {exc}") from exc

        if not content:
            raise VersionError(f"원고 내용이 비어 있습니다: source_id={source_id}")

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
    ) -> tuple[list["DocumentChunk"], list["DocumentChunk"]]:
        """
        수정이 적용된 텍스트 영역이 포함된 청크만 선별합니다.

        Returns (changed_chunks, all_chunks):
        - changed_chunks: 그래프 증분 재구축 대상
        - all_chunks: Search 전체 재인덱싱 대상
        """
        try:
            source_vertex = await self._run_graph(self._graph.get_vertex, source_id, "source")
            filename = (source_vertex or {}).get("name", f"{source_id}.txt")
            all_chunks = self._ingest.chunk_text(
                text=new_content,
                source_id=source_id,
                source_name=filename,
            )
        except Exception as exc:
            raise VersionError(f"재청킹 실패 (source_id={source_id}): {exc}") from exc

        # is_intentional 픽스는 텍스트 변경 없음
        fixed_texts = {fix.fixed_text for fix in applied_fixes if not fix.is_intentional and fix.fixed_text}

        # 모든 픽스가 is_intentional=True — 텍스트 변경 없으므로 재구축 불필요
        if not fixed_texts:
            log.info("all_fixes_intentional_no_rebuild_needed")
            return [], all_chunks

        changed: list["DocumentChunk"] = []

        for chunk in all_chunks:
            if any(fixed_text in chunk.content for fixed_text in fixed_texts):
                changed.append(chunk)

        if not changed:
            log.warning(
                "no_changed_chunks_detected",
                detail=(
                    "fixed_text를 포함하는 청크를 찾지 못했습니다. "
                    "안전하게 전체 청크를 변경 대상으로 처리합니다."
                ),
            )
            return all_chunks, all_chunks

        return changed, all_chunks

    # ──────────────────────────────────────────────────────────────
    # Private: 증분 재구축 (계층1 → 계층2 → 계층3 → 재인덱싱)
    # ──────────────────────────────────────────────────────────────

    async def _run_incremental_rebuild(
        self,
        source_id: str,
        changed_chunks: list["DocumentChunk"],
        log: structlog.BoundLogger,
        all_chunks: list["DocumentChunk"] | None = None,
    ) -> list:
        """
        변경된 청크에 대해서만 계층1~3을 순차 재실행합니다.

        Parameters:
            changed_chunks: 그래프 증분 재구축 대상 청크
            all_chunks: Search 전체 재인덱싱 대상 청크 (None이면 changed_chunks 사용)

        Returns:
            list[PipelineError]: 발생한 오류 목록 (빈 리스트 = 전부 성공)
        """
        from app.models.api import PipelineError
        errors: list[PipelineError] = []

        if not changed_chunks:
            log.debug("no_changed_chunks_skip_rebuild")
            return errors

        log.info("incremental_rebuild_start", chunk_count=len(changed_chunks))

        # source_type 조회 (계층1 추출에 필요)
        source_vertex = await self._run_graph(self._graph.get_vertex, source_id, "source")
        source_type = (source_vertex or {}).get("source_type", "scenario")

        # 계층1: Extraction (변경된 청크만)
        log.info("rebuild_layer1_extraction")
        extraction_results = []
        try:
            extraction_results = await self._extraction.extract_from_chunks(changed_chunks, source_type)
        except Exception as exc:
            log.error("rebuild_extraction_failed", error=str(exc))
            errors.append(PipelineError(layer="extraction", message=f"계층1 재추출 실패: {exc}", recoverable=False))
            return errors  # 추출 실패 시 이후 단계 불가

        # 해당 source_id의 기존 vertex/edge 전부 삭제 (Source vertex 제외)
        # 재청킹 시 chunk_id가 변경되므로 chunk_id 기반 삭제 대신 source_id 기반 삭제
        log.info("removing_old_source_data", source_id=source_id)
        try:
            removed = await self._run_graph(self._graph.remove_source, source_id)
            log.info("old_source_data_removed", removed=removed)
        except Exception as exc:
            log.warning("remove_old_source_data_failed", error=str(exc))
            errors.append(PipelineError(layer="graph_cleanup", message=f"이전 데이터 삭제 실패: {exc}", recoverable=True))

        # 계층2: Normalization
        log.info("rebuild_layer2_normalization")
        normalization_result = None
        try:
            normalization_result = await self._normalization.normalize(extraction_results)
        except Exception as exc:
            log.error("rebuild_normalization_failed", error=str(exc))
            errors.append(PipelineError(layer="normalization", message=f"계층2 정규화 실패: {exc}", recoverable=False))
            return errors

        # 계층3: Graph Materialization
        log.info("rebuild_layer3_graph")
        try:
            if source_vertex is None:
                raise VersionError(f"Source Vertex를 찾을 수 없습니다: source_id={source_id}")

            from app.models.enums import SourceType as _ST
            source_obj = Source(
                source_id=source_id,
                source_type=_ST(source_vertex.get("source_type", "scenario")),
                name=str(source_vertex.get("name", source_id)),
                file_path=str(source_vertex.get("file_path", "")),
                original_file_path=str(source_vertex.get("original_file_path", "")),
                metadata=str(source_vertex.get("metadata", "{}")),
            )
            # remove_source()가 Source vertex도 삭제하므로 재생성 필요
            await self._run_graph(
                self._graph.materialize,
                normalization_result,
                source_obj,
                skip_source_vertex=False,
            )
        except Exception as exc:
            log.error("rebuild_materialize_failed", error=str(exc))
            errors.append(PipelineError(layer="materialize", message=f"계층3 그래프 재적재 실패: {exc}", recoverable=False))

        # Search 재인덱싱: 기존 인덱스 삭제 후 전체 청크 재인덱싱 (정합성 보장)
        reindex_chunks = all_chunks if all_chunks else changed_chunks
        log.info("rebuild_search_reindex", chunks=len(reindex_chunks))
        try:
            await self._search.remove_source(source_id)
        except Exception as exc:
            log.warning("search_remove_old_failed", error=str(exc))
            errors.append(PipelineError(layer="search", message=f"검색 인덱스 삭제 실패: {exc}", recoverable=True))
        try:
            await self._search.index_chunks(source_id=source_id, chunks=reindex_chunks)
        except Exception as exc:
            log.warning("search_reindex_failed", error=str(exc))
            errors.append(PipelineError(layer="search", message=f"검색 재인덱싱 실패: {exc}", recoverable=True))

        log.info("incremental_rebuild_complete", errors=len(errors))
        return errors

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

        마킹 실패 시 전체 push를 중단하지 않고 경고만 기록합니다.
        """
        for contradiction_id in contradiction_ids:
            try:
                await self._run_graph(
                    self._graph.patch_vertex,
                    contradiction_id,
                    "contradiction",
                    {"status": "resolved"},
                )
                log.info("contradiction_resolved", contradiction_id=contradiction_id)
            except Exception as exc:
                log.warning(
                    "contradiction_mark_failed",
                    contradiction_id=contradiction_id,
                    error=str(exc),
                )

    # ──────────────────────────────────────────────────────────────
    # Private: 버전 생성 + 저장
    # ──────────────────────────────────────────────────────────────

    def _create_version(
        self,
        version_id: str,
        version_name: str,
        source_id: str,
        fixes_count: int,
        description: str,
        resolved_contradiction_ids: list[str],
        snapshot_path: str,
        src: str = "",
        pipeline_errors: list = None,
    ) -> VersionInfo:
        """
        새 VersionInfo를 생성하고 인메모리 메타 저장소에 등록합니다.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        info = VersionInfo(
            id=version_id,
            version=version_name,
            date=now_iso,
            fixes_count=fixes_count,
            description=description,
            snapshot_path=snapshot_path,
            src=src,
            pipeline_errors=pipeline_errors or [],
        )

        stored = _StoredVersion(
            info=info,
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
            snapshot_path=snapshot_path,
        )
        return info


# ──────────────────────────────────────────────────────────────────────────────
# 모듈 레벨 순수 함수 (테스트 용이성)
# ──────────────────────────────────────────────────────────────────────────────


def _apply_text_fixes(
    content: str,
    fixes: list[StagedFix],
    log: structlog.BoundLogger,
    chunk_contents: dict[str, str] | None = None,
) -> tuple[str, list[StagedFix], list[StagedFix]]:
    """
    원고 텍스트에 픽스를 순차 적용합니다.

    적용 순서:
    - staged_at 오름차순(선입선출)
    - chunk_id가 있으면 해당 청크 범위 내에서만 치환 (위치 안전)
    - chunk_id가 없으면 첫 번째 일치 항목만 치환 (기존 방식)

    chunk_contents: chunk_id → 청크 텍스트 맵 (있으면 범위 제한 치환에 사용)
    """
    # \r\n → \n 정규화 (Windows 줄바꿈 호환)
    current = content.replace("\r\n", "\n").replace("\r", "\n")
    applied: list[StagedFix] = []
    failed: list[StagedFix] = []

    for fix in sorted(fixes, key=lambda item: item.staged_at):
        if fix.is_intentional:
            applied.append(fix)
            continue
        # original_text도 줄바꿈 정규화
        normalized_ot = fix.original_text.replace("\r\n", "\n").replace("\r", "\n")
        if normalized_ot not in current:
            log.warning(
                "fix_original_not_found",
                contradiction_id=fix.contradiction_id,
                original_preview=fix.original_text[:80],
            )
            failed.append(fix)
            continue

        # chunk_id 기반 위치 제한 치환
        if fix.chunk_id and chunk_contents and fix.chunk_id in chunk_contents:
            chunk_text = chunk_contents[fix.chunk_id].replace("\r\n", "\n").replace("\r", "\n")
            chunk_start = current.find(chunk_text)
            if chunk_start >= 0:
                chunk_end = chunk_start + len(chunk_text)
                chunk_region = current[chunk_start:chunk_end]
                idx_in_chunk = chunk_region.find(normalized_ot)
                if idx_in_chunk >= 0:
                    abs_start = chunk_start + idx_in_chunk
                    abs_end = abs_start + len(normalized_ot)
                    current = current[:abs_start] + fix.fixed_text + current[abs_end:]
                    applied.append(fix)
                    log.debug("fix_applied_chunk_scoped", contradiction_id=fix.contradiction_id, chunk_id=fix.chunk_id)
                    continue
            log.debug("chunk_scope_fallback", contradiction_id=fix.contradiction_id, chunk_id=fix.chunk_id)

        current = current.replace(normalized_ot, fix.fixed_text, 1)
        applied.append(fix)
        log.debug("fix_applied", contradiction_id=fix.contradiction_id)

    return current, applied, failed


def _auto_description(applied_fixes: list[StagedFix]) -> str:
    """
    description이 없을 때 자동으로 버전 설명을 생성합니다.
    """
    if not applied_fixes:
        return "수정 사항 없음"

    ids = [fix.contradiction_id for fix in applied_fixes]
    if len(ids) == 1:
        return f"contradiction {ids[0]} 수정 반영"

    id_summary = ", ".join(ids[:3])
    suffix = f" 외 {len(ids) - 3}건" if len(ids) > 3 else ""
    return f"모순 {len(ids)}건 수정 반영 ({id_summary}{suffix})"