"""
계층 5 — 버전 관리 서비스 (VersionService)

역할:
  - 모순 수정 스테이징 (stage_fix)
  - 스테이징된 수정 일괄 반영 → 원본 업데이트 + 증분 재구축 + 버전 생성 (push_staged_fixes)
  - 버전 이력 조회 (list_versions)
  - 특정 버전 원고 내용 조회 (get_version)
  - 버전 간 diff 비교 (diff_versions)
"""

from __future__ import annotations

import difflib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

import structlog

from app.models.api import VersionInfo

if TYPE_CHECKING:
    from app.services.graph import InMemoryGraphService  # noqa: F401

logger = structlog.get_logger().bind(service="version_service")

# 버전 데이터를 저장하는 기본 디렉토리 (실제 운영 시 설정으로 교체)
_VERSION_STORE_DIR = Path(os.environ.get("VERSION_STORE_DIR", "/tmp/conticheck_versions"))


# ─────────────────────────────────────────────────────────────
# 내부 데이터 구조
# ─────────────────────────────────────────────────────────────

class StagedFix:
    """단일 수정 스테이징 항목"""

    def __init__(
        self,
        contradiction_id: str,
        original_text: str,
        fixed_text: str,
    ) -> None:
        self.id: str = str(uuid.uuid4())
        self.contradiction_id: str = contradiction_id
        self.original_text: str = original_text
        self.fixed_text: str = fixed_text
        self.staged_at: datetime = datetime.utcnow()

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "contradiction_id": self.contradiction_id,
            "original_text": self.original_text,
            "fixed_text": self.fixed_text,
            "staged_at": self.staged_at.isoformat(),
        }


class VersionRecord:
    """하나의 버전 스냅샷"""

    def __init__(
        self,
        version_number: int,
        fixes: List[StagedFix],
        content_snapshot: str,
        description: str = "",
    ) -> None:
        self.id: str = str(uuid.uuid4())
        self.version: str = f"v{version_number}"
        self.date: str = datetime.utcnow().isoformat()
        self.fixes_count: int = len(fixes)
        self.description: str = description
        self.content_snapshot: str = content_snapshot
        self.resolved_contradiction_ids: List[str] = [f.contradiction_id for f in fixes]

    def to_version_info(self) -> VersionInfo:
        return VersionInfo(
            id=self.id,
            version=self.version,
            date=self.date,
            fixes_count=self.fixes_count,
            description=self.description,
        )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "version": self.version,
            "date": self.date,
            "fixes_count": self.fixes_count,
            "description": self.description,
            "content_snapshot": self.content_snapshot,
            "resolved_contradiction_ids": self.resolved_contradiction_ids,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "VersionRecord":
        rec = object.__new__(cls)
        rec.id = d["id"]
        rec.version = d["version"]
        rec.date = d["date"]
        rec.fixes_count = d["fixes_count"]
        rec.description = d["description"]
        rec.content_snapshot = d["content_snapshot"]
        rec.resolved_contradiction_ids = d.get("resolved_contradiction_ids", [])
        return rec


# ─────────────────────────────────────────────────────────────
# VersionService
# ─────────────────────────────────────────────────────────────

class VersionService:
    """
    버전 관리 서비스.

    Parameters
    ----------
    graph_service : GremlinGraphService | InMemoryGraphService
        계층 3 그래프 서비스.
    extraction_service : ExtractionService | MockExtractionService, optional
        계층 1 — 증분 재구축에 사용.
    normalization_service : NormalizationService | MockNormalizationService, optional
        계층 2 — 증분 재구축에 사용.
    store_dir : Path | str, optional
        버전 파일 저장 경로. 기본값은 환경변수 VERSION_STORE_DIR.
    """

    def __init__(
        self,
        graph_service,
        extraction_service=None,
        normalization_service=None,
        store_dir: Optional[Path] = None,
    ) -> None:
        self.graph = graph_service
        self.extraction_svc = extraction_service
        self.normalization_svc = normalization_service
        self._store_dir: Path = Path(store_dir) if store_dir else _VERSION_STORE_DIR
        self._store_dir.mkdir(parents=True, exist_ok=True)

        # 인메모리 스토어 (싱글턴 범위에서 유지)
        self._staged: Dict[str, StagedFix] = {}       # fix_id → StagedFix
        self._versions: List[VersionRecord] = []       # 오래된 순
        self._version_counter: int = 0
        self._current_content: str = ""               # 최신 원고 전체 텍스트

        self._load_from_store()

    # ── 스테이징 ────────────────────────────────────────────

    def stage_fix(
        self,
        contradiction_id: str,
        original_text: str,
        fixed_text: str,
    ) -> StagedFix:
        """
        모순 수정을 스테이징합니다.

        Parameters
        ----------
        contradiction_id : str
            ContradictionReport.id 또는 UserConfirmation.id.
        original_text : str
            수정 전 원문 발췌.
        fixed_text : str
            수정 후 텍스트.

        Returns
        -------
        StagedFix
            스테이징된 수정 항목.
        """
        fix = StagedFix(
            contradiction_id=contradiction_id,
            original_text=original_text,
            fixed_text=fixed_text,
        )
        self._staged[fix.id] = fix
        logger.info(
            "Fix staged",
            fix_id=fix.id,
            contradiction_id=contradiction_id,
        )
        return fix

    def list_staged(self) -> List[StagedFix]:
        """스테이징된 수정 목록 반환"""
        return list(self._staged.values())

    def unstage_fix(self, fix_id: str) -> bool:
        """특정 스테이징 항목을 취소합니다."""
        if fix_id in self._staged:
            del self._staged[fix_id]
            logger.info("Fix unstaged", fix_id=fix_id)
            return True
        return False

    # ── 반영 ────────────────────────────────────────────────

    def push_staged_fixes(
        self,
        fixes: Optional[List[StagedFix]] = None,
        description: str = "",
    ) -> VersionInfo:
        """
        스테이징된 수정사항을 일괄 반영하고 새 버전을 생성합니다.

        Steps
        -----
        1. 원본 텍스트에 수정사항 적용 (순서대로 치환)
        2. 새 버전 레코드 생성
        3. 변경 영역만 계층1~3 증분 재구축 (서비스가 주입된 경우)
        4. 반영된 모순을 그래프에서 resolved로 마킹
        5. 스테이징 큐 초기화

        Parameters
        ----------
        fixes : list[StagedFix] | None
            반영할 수정 목록. None이면 전체 staged 항목을 사용.
        description : str
            버전 설명 (선택).

        Returns
        -------
        VersionInfo
        """
        if fixes is None:
            fixes = list(self._staged.values())

        if not fixes:
            logger.warning("push_staged_fixes called with no fixes")
            # 빈 버전이라도 생성하여 반환
            return self._create_version([], description or "Empty push")

        # 1. 원본 텍스트에 수정 적용
        updated_content = self._apply_fixes_to_content(self._current_content, fixes)
        self._current_content = updated_content

        # 2. 버전 레코드 생성
        version_record = self._create_version(fixes, description)

        # 3. 증분 재구축 (변경된 텍스트 영역만)
        if self.extraction_svc and self.normalization_svc:
            self._incremental_rebuild(fixes)
        else:
            logger.info(
                "Skipping incremental rebuild (extraction/normalization services not injected)"
            )

        # 4. 모순 resolved 마킹
        for fix in fixes:
            self._mark_contradiction_resolved(fix.contradiction_id)

        # 5. 스테이징 큐에서 제거
        applied_ids = {f.id for f in fixes}
        self._staged = {k: v for k, v in self._staged.items() if k not in applied_ids}

        # 파일 저장
        self._persist_version(version_record)

        logger.info(
            "Staged fixes pushed",
            version=version_record.version,
            fixes_count=len(fixes),
        )
        return version_record.to_version_info()

    # ── 조회 ────────────────────────────────────────────────

    def list_versions(self) -> List[VersionInfo]:
        """버전 이력 목록 반환 (최신 순)"""
        return [v.to_version_info() for v in reversed(self._versions)]

    def get_version(self, version_id: str) -> Optional[str]:
        """
        특정 버전의 원고 내용 반환.

        Parameters
        ----------
        version_id : str
            VersionInfo.id

        Returns
        -------
        str | None
            원고 전체 텍스트. 버전이 없으면 None.
        """
        rec = self._find_version(version_id)
        if rec is None:
            logger.warning("Version not found", version_id=version_id)
            return None
        return rec.content_snapshot

    def diff_versions(self, version_id_a: str, version_id_b: str) -> str:
        """
        두 버전 간 unified diff 반환.

        Parameters
        ----------
        version_id_a : str
            기준 버전 id (이전).
        version_id_b : str
            비교 버전 id (이후).

        Returns
        -------
        str
            unified diff 텍스트. 버전을 찾지 못하면 빈 문자열.
        """
        rec_a = self._find_version(version_id_a)
        rec_b = self._find_version(version_id_b)

        if rec_a is None or rec_b is None:
            missing = []
            if rec_a is None:
                missing.append(version_id_a)
            if rec_b is None:
                missing.append(version_id_b)
            logger.warning("Version(s) not found for diff", missing=missing)
            return ""

        lines_a = rec_a.content_snapshot.splitlines(keepends=True)
        lines_b = rec_b.content_snapshot.splitlines(keepends=True)

        diff = difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=f"{rec_a.version} ({rec_a.date[:10]})",
            tofile=f"{rec_b.version} ({rec_b.date[:10]})",
            lineterm="",
        )
        return "\n".join(diff)

    # ── 내부: 수정 적용 ──────────────────────────────────────

    def _apply_fixes_to_content(self, content: str, fixes: List[StagedFix]) -> str:
        """
        원본 텍스트에 수정사항을 순서대로 적용합니다.

        각 fix의 original_text를 fixed_text로 치환.
        같은 original_text가 여러 번 나타날 경우 첫 번째만 치환합니다.
        """
        result = content
        for fix in fixes:
            if fix.original_text in result:
                result = result.replace(fix.original_text, fix.fixed_text, 1)
                logger.debug(
                    "Applied fix to content",
                    contradiction_id=fix.contradiction_id,
                    original_len=len(fix.original_text),
                    fixed_len=len(fix.fixed_text),
                )
            else:
                logger.warning(
                    "original_text not found in current content — fix skipped",
                    contradiction_id=fix.contradiction_id,
                    original_preview=fix.original_text[:80],
                )
        return result

    # ── 내부: 증분 재구축 ────────────────────────────────────

    def _incremental_rebuild(self, fixes: List[StagedFix]) -> None:
        """
        수정된 텍스트 영역만 계층1~3 재실행합니다.

        전략:
        - 각 fix의 fixed_text를 DocumentChunk로 래핑
        - ExtractionService → NormalizationService → graph.materialize()
        - 기존 소스(source_id="incremental_rebuild")의 데이터를 먼저 삭제 후 재적재
        """
        from app.models.api import DocumentChunk, SourceLocation
        from app.models.enums import SourceType
        from app.models.vertices import Source

        rebuild_source_id = f"rebuild_{uuid.uuid4().hex[:8]}"

        chunks = []
        for idx, fix in enumerate(fixes):
            chunk = DocumentChunk(
                id=f"{rebuild_source_id}_chunk_{idx}",
                source_id=rebuild_source_id,
                chunk_index=idx,
                content=fix.fixed_text,
                location=SourceLocation(
                    source_id=rebuild_source_id,
                    source_name="incremental_rebuild",
                ),
            )
            chunks.append(chunk)

        if not chunks:
            return

        try:
            # 계층 1: 추출
            import asyncio

            extraction_results = asyncio.get_event_loop().run_until_complete(
                self.extraction_svc.extract_from_chunks(chunks)
            )

            # 계층 2: 정규화
            normalized = self.normalization_svc.normalize(extraction_results)

            # 계층 3: 그래프 적재
            source = Source(
                source_id=rebuild_source_id,
                source_type=SourceType.MANUSCRIPT,
                name="incremental_rebuild",
                metadata=json.dumps({"rebuild": True}),
            )
            self.graph.materialize(normalized, source)

            logger.info(
                "Incremental rebuild complete",
                source_id=rebuild_source_id,
                chunks=len(chunks),
            )
        except Exception as e:
            logger.error("Incremental rebuild failed", error=str(e))

    # ── 내부: resolved 마킹 ───────────────────────────────────

    def _mark_contradiction_resolved(self, contradiction_id: str) -> None:
        """
        그래프에서 contradiction_id에 해당하는 vertex/edge를 resolved로 마킹합니다.

        InMemoryGraphService와 GremlinGraphService 모두 지원합니다.
        """
        props = {"resolved": True, "resolved_at": datetime.utcnow().isoformat()}

        # InMemoryGraphService
        if hasattr(self.graph, "vertices"):
            v = self.graph.vertices.get(contradiction_id)
            if v:
                v.update(props)
                logger.info("Contradiction marked resolved (in-memory)", cid=contradiction_id)
                return

        # GremlinGraphService
        try:
            t = self.graph.g.V(contradiction_id)
            for k, val in props.items():
                t = t.property(k, val)
            t.toList()
            logger.info("Contradiction marked resolved (gremlin)", cid=contradiction_id)
        except Exception as e:
            logger.warning(
                "Could not mark contradiction resolved in graph",
                contradiction_id=contradiction_id,
                error=str(e),
            )

    # ── 내부: 버전 레코드 관리 ──────────────────────────────

    def _create_version(self, fixes: List[StagedFix], description: str) -> VersionRecord:
        self._version_counter += 1
        rec = VersionRecord(
            version_number=self._version_counter,
            fixes=fixes,
            content_snapshot=self._current_content,
            description=description or f"Version {self._version_counter}",
        )
        self._versions.append(rec)
        return rec

    def _find_version(self, version_id: str) -> Optional[VersionRecord]:
        for v in self._versions:
            if v.id == version_id:
                return v
        return None

    # ── 내부: 파일 영속화 ────────────────────────────────────

    def _persist_version(self, rec: VersionRecord) -> None:
        """버전 레코드를 JSON 파일로 저장합니다."""
        path = self._store_dir / f"{rec.id}.json"
        try:
            path.write_text(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to persist version record", version_id=rec.id, error=str(e))

    def _load_from_store(self) -> None:
        """시작 시 저장된 버전 파일들을 로드합니다."""
        if not self._store_dir.exists():
            return
        records = []
        for path in sorted(self._store_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                records.append(VersionRecord.from_dict(data))
            except Exception as e:
                logger.warning("Failed to load version file", path=str(path), error=str(e))

        # version 번호 순으로 정렬
        records.sort(key=lambda r: r.version)
        self._versions = records

        if records:
            self._version_counter = len(records)
            self._current_content = records[-1].content_snapshot
            logger.info(
                "Loaded version history from store",
                count=len(records),
                latest=records[-1].version,
            )

    def set_current_content(self, content: str) -> None:
        """
        현재 원고 내용을 초기화합니다.

        원고 업로드 직후 또는 첫 번째 버전 생성 전에 호출합니다.
        """
        self._current_content = content
        logger.info("Current content updated", length=len(content))


# ─────────────────────────────────────────────────────────────
# 싱글턴 팩토리
# ─────────────────────────────────────────────────────────────

_version_service: Optional[VersionService] = None


def get_version_service(
    graph_service=None,
    extraction_service=None,
    normalization_service=None,
) -> VersionService:
    """
    VersionService 싱글턴을 반환합니다.
    처음 호출 시 graph_service를 반드시 전달해야 합니다.
    """
    global _version_service
    if _version_service is None:
        if graph_service is None:
            raise RuntimeError(
                "graph_service must be provided on first call to get_version_service()"
            )
        _version_service = VersionService(
            graph_service=graph_service,
            extraction_service=extraction_service,
            normalization_service=normalization_service,
        )
    return _version_service
