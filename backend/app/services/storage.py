"""
storage.py — 파일/버전 스토리지 서비스 (임시 구현)

TODO: Phase 1 담당자가 LocalStorageService / BlobStorageService를 정식 구현으로 교체 예정.
      현재는 서버 시작 및 인터페이스 확정 목적의 stub.

클래스:
  StorageService       — 공통 인터페이스 (stub 기본 구현 제공)
  LocalStorageService  — 로컬 파일시스템 기반 (stub)
  BlobStorageService   — Azure Blob Storage 기반 (stub)
"""

from __future__ import annotations

import structlog
from typing import Optional

logger = structlog.get_logger(__name__)


class StorageService:
    """
    스토리지 서비스 공통 인터페이스.

    모든 메서드는 stub 구현으로, 오류 없이 빈 값을 반환합니다.
    Phase 1 담당자가 LocalStorageService / BlobStorageService로 교체하세요.
    """

    async def save_file(
        self,
        source_id: str,
        filename: str,
        content_bytes: bytes,
        source_type: str,
    ) -> str:
        """파일을 저장하고 저장 경로(또는 blob URL)를 반환합니다."""
        logger.debug("storage_stub_save_file", source_id=source_id, filename=filename)
        return ""

    async def get_file(self, source_id: str) -> bytes:
        """source_id에 해당하는 파일을 바이트로 반환합니다."""
        logger.debug("storage_stub_get_file", source_id=source_id)
        return b""

    async def get_file_text(self, source_id: str) -> str:
        """source_id에 해당하는 파일을 UTF-8 텍스트로 반환합니다."""
        logger.debug("storage_stub_get_file_text", source_id=source_id)
        return ""

    async def delete_file(self, source_id: str) -> None:
        """source_id에 해당하는 파일을 삭제합니다."""
        logger.debug("storage_stub_delete_file", source_id=source_id)

    async def save_version_snapshot(
        self,
        version_id: str,
        source_id: str,
        content_text: str,
    ) -> str:
        """버전 스냅샷을 저장하고 저장 경로(또는 blob URL)를 반환합니다."""
        logger.debug(
            "storage_stub_save_version_snapshot",
            version_id=version_id,
            source_id=source_id,
        )
        return ""

    async def get_version_content(self, version_id: str, source_id: str) -> str:
        """특정 버전의 원고 전문을 반환합니다."""
        logger.debug(
            "storage_stub_get_version_content",
            version_id=version_id,
            source_id=source_id,
        )
        return ""

    async def diff_version_content(
        self,
        version_a: str,
        version_b: str,
        source_id: str,
    ) -> str:
        """두 버전 간 텍스트 diff를 반환합니다."""
        logger.debug(
            "storage_stub_diff_version_content",
            version_a=version_a,
            version_b=version_b,
            source_id=source_id,
        )
        return ""

    async def list_versions(self, source_id: str) -> list[str]:
        """source_id에 저장된 버전 ID 목록을 반환합니다."""
        logger.debug("storage_stub_list_versions", source_id=source_id)
        return []


class LocalStorageService(StorageService):
    """
    로컬 파일시스템 기반 스토리지 서비스 (stub).

    TODO: Phase 1 담당자가 구현 예정.
          base_dir 경로에 source_id / version_id 단위로 파일을 저장하는 로직 필요.
    """

    def __init__(self, base_dir: str = "data/storage") -> None:
        self.base_dir = base_dir
        logger.info("LocalStorageService_stub_initialized", base_dir=base_dir)


class BlobStorageService(StorageService):
    """
    Azure Blob Storage 기반 스토리지 서비스 (stub).

    TODO: Phase 1 담당자가 구현 예정.
          azure-storage-blob SDK를 사용하여 uploads / versions 컨테이너에
          각각 원본 파일과 버전 스냅샷을 저장하는 로직 필요.

    환경변수:
      AZURE_STORAGE_CONNECTION_STRING
      AZURE_STORAGE_CONTAINER_UPLOADS   (기본: conticheck-uploads)
      AZURE_STORAGE_CONTAINER_VERSIONS  (기본: conticheck-versions)
    """

    def __init__(
        self,
        connection_string: str = "",
        container_uploads: str = "conticheck-uploads",
        container_versions: str = "conticheck-versions",
    ) -> None:
        self.connection_string = connection_string
        self.container_uploads = container_uploads
        self.container_versions = container_versions
        logger.info(
            "BlobStorageService_stub_initialized",
            container_uploads=container_uploads,
            container_versions=container_versions,
        )


# ──────────────────────────────────────────────────────────────────────────────
# 팩토리
# ──────────────────────────────────────────────────────────────────────────────

_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """
    설정에 따라 적절한 StorageService 인스턴스를 반환합니다.

    USE_LOCAL_GRAPH=true  → LocalStorageService
    그 외                 → BlobStorageService (AZURE_STORAGE_CONNECTION_STRING 필요)
    """
    global _storage_service
    if _storage_service is not None:
        return _storage_service

    try:
        from app.config import settings

        if getattr(settings, "use_local_graph", True):
            _storage_service = LocalStorageService()
        else:
            _storage_service = BlobStorageService(
                connection_string=getattr(settings, "AZURE_STORAGE_CONNECTION_STRING", ""),
                container_uploads=getattr(settings, "AZURE_STORAGE_CONTAINER_UPLOADS", "conticheck-uploads"),
                container_versions=getattr(settings, "AZURE_STORAGE_CONTAINER_VERSIONS", "conticheck-versions"),
            )
    except Exception:
        # config 로드 실패 시 로컬 기본값 사용
        _storage_service = LocalStorageService()

    return _storage_service
