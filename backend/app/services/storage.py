"""
storage.py — 횡단 서비스: 원본 파일 영구 저장 + 버전 스냅샷

책임:
  1. save_file              — 업로드 원본 파일을 영구 저장 → 저장 경로 반환
  2. get_file               — 저장된 파일 바이트 반환
  3. get_file_text          — 저장된 파일 텍스트 반환 (UTF-8 디코딩)
  4. delete_file            — 원본 파일 삭제
  5. save_version_snapshot  — Push 시 버전별 원고 스냅샷 저장
  6. get_version_content    — 특정 버전 원고 내용 반환
  7. diff_version_content   — 두 버전 간 unified diff 반환
  8. list_versions          — 버전 목록 반환

두 구현체:
  - LocalStorageService  : 로컬 파일시스템 (개발/POC 기본값)
  - BlobStorageService   : Azure Blob Storage (프로덕션)

환경변수:
  USE_LOCAL_STORAGE=true  (기본) → LocalStorageService
  USE_LOCAL_STORAGE=false         → BlobStorageService

디렉토리 구조 (로컬):
  data/
  ├── uploads/
  │   └── {source_id}/
  │       └── {filename}        ← 업로드 원본
  └── versions/
      └── {source_id}/
          ├── v1.txt            ← 버전 스냅샷
          └── v2.txt
"""

from __future__ import annotations

import difflib
import os
import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# 예외
# ─────────────────────────────────────────────────────────────

class StorageError(Exception):
    """StorageService 관련 오류의 기반 클래스."""


class FileNotFoundInStorageError(StorageError):
    """요청한 파일이 스토리지에 없을 때."""


class VersionNotFoundInStorageError(StorageError):
    """요청한 버전 스냅샷이 없을 때."""


# ─────────────────────────────────────────────────────────────
# 추상 인터페이스
# ─────────────────────────────────────────────────────────────

class StorageService(ABC):
    """
    StorageService 추상 인터페이스.

    IngestService와 VersionService가 이 인터페이스에만 의존합니다.
    LocalStorageService / BlobStorageService가 이를 구현합니다.
    """

    # ── 원본 파일 관리 ──────────────────────────────────

    @abstractmethod
    async def save_file(
        self,
        file_content: bytes,
        filename: str,
        source_id: str,
        source_type: str,
    ) -> str:
        """
        업로드된 원본 파일을 영구 저장합니다.

        Parameters
        ----------
        file_content : bytes
            파일 바이트
        filename : str
            원본 파일명 (예: "캐릭터_설정집_v2.pdf")
        source_id : str
            Source Vertex ID — 저장 폴더 구분자로 사용
        source_type : str
            "worldview" | "settings" | "scenario"

        Returns
        -------
        str
            저장된 파일의 경로/URL.
            Source.file_path 필드에 기록됩니다.

        Raises
        ------
        StorageError
            저장 실패 시
        """

    @abstractmethod
    async def get_file(self, file_path: str) -> bytes:
        """
        저장된 파일의 바이트를 반환합니다.

        Parameters
        ----------
        file_path : str
            save_file()이 반환한 경로/URL

        Raises
        ------
        FileNotFoundInStorageError
            해당 파일이 없을 때
        StorageError
            읽기 실패 시
        """

    @abstractmethod
    async def get_file_text(self, file_path: str, encoding: str = "utf-8") -> str:
        """
        저장된 파일을 텍스트로 반환합니다.
        VersionService가 원고 내용을 읽을 때 사용합니다.

        Parameters
        ----------
        file_path : str
            save_file() 또는 save_version_snapshot()이 반환한 경로
        encoding : str
            텍스트 인코딩 (기본 utf-8, 실패 시 cp949 fallback)

        Raises
        ------
        FileNotFoundInStorageError
        StorageError
        """

    @abstractmethod
    async def delete_file(self, file_path: str) -> None:
        """
        저장된 파일을 삭제합니다.
        Source 삭제 시 IngestService가 호출합니다.

        Parameters
        ----------
        file_path : str
            save_file()이 반환한 경로/URL

        Raises
        ------
        FileNotFoundInStorageError
        StorageError
        """

    # ── 버전 스냅샷 관리 ─────────────────────────────────

    @abstractmethod
    async def save_version_snapshot(
        self,
        source_id: str,
        version: str,
        content: str,
    ) -> str:
        """
        Push 시 수정된 원고를 버전 스냅샷으로 저장합니다.

        Parameters
        ----------
        source_id : str
            대상 Source ID
        version : str
            버전 문자열 (예: "v1", "v2")
        content : str
            수정 반영 후 원고 전문 (텍스트)

        Returns
        -------
        str
            저장된 스냅샷 경로/URL

        Raises
        ------
        StorageError
        """

    @abstractmethod
    async def get_version_content(self, source_id: str, version: str) -> str:
        """
        특정 버전의 원고 내용을 반환합니다.

        Parameters
        ----------
        source_id : str
            대상 Source ID
        version : str
            버전 문자열 (예: "v1")

        Returns
        -------
        str
            해당 버전의 원고 텍스트

        Raises
        ------
        VersionNotFoundInStorageError
        StorageError
        """

    @abstractmethod
    async def list_versions(self, source_id: str) -> list[str]:
        """
        특정 소스의 모든 버전 목록을 오름차순으로 반환합니다.

        Parameters
        ----------
        source_id : str
            대상 Source ID

        Returns
        -------
        list[str]
            버전 문자열 목록 (예: ["v1", "v2", "v3"])
        """

    # ── 공통 유틸 (구현체가 override 불필요) ─────────────

    async def diff_version_content(
        self,
        source_id: str,
        version_a: str,
        version_b: str,
        context_lines: int = 3,
    ) -> str:
        """
        두 버전 간의 unified diff를 반환합니다.

        Parameters
        ----------
        source_id : str
            대상 Source ID
        version_a : str
            기준 버전 (구 버전)
        version_b : str
            비교 대상 버전 (신 버전)
        context_lines : int
            diff 컨텍스트 줄 수 (기본 3)

        Returns
        -------
        str
            unified diff 문자열. 두 버전이 동일하면 빈 문자열.

        Raises
        ------
        VersionNotFoundInStorageError
            둘 중 하나라도 없을 때
        """
        content_a = await self.get_version_content(source_id, version_a)
        content_b = await self.get_version_content(source_id, version_b)

        diff_lines = list(
            difflib.unified_diff(
                content_a.splitlines(keepends=True),
                content_b.splitlines(keepends=True),
                fromfile=f"{source_id}/{version_a}",
                tofile=f"{source_id}/{version_b}",
                n=context_lines,
            )
        )
        return "".join(diff_lines)


# ─────────────────────────────────────────────────────────────
# LocalStorageService — 로컬 파일시스템 구현체
# ─────────────────────────────────────────────────────────────

class LocalStorageService(StorageService):
    """
    로컬 파일시스템 기반 스토리지. 개발 및 POC 환경에서 사용합니다.

    디렉토리 레이아웃::

        {base_dir}/
        ├── uploads/
        │   └── {source_id}/
        │       └── {filename}
        └── versions/
            └── {source_id}/
                ├── v1.txt
                └── v2.txt

    사용 예::

        storage = LocalStorageService(base_dir="data")
        path = await storage.save_file(content, "설정집.pdf", "src-001", "settings")
        text = await storage.get_file_text(path)
    """

    def __init__(self, base_dir: str = "data") -> None:
        self._base = Path(base_dir)
        self._uploads = self._base / "uploads"
        self._versions = self._base / "versions"
        self._uploads.mkdir(parents=True, exist_ok=True)
        self._versions.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageService initialized", base_dir=str(self._base))

    # ── 내부 헬퍼 ─────────────────────────────────────────

    def _upload_path(self, source_id: str, filename: str) -> Path:
        return self._uploads / source_id / filename

    def _version_path(self, source_id: str, version: str) -> Path:
        safe = version.replace("/", "_").replace("\\", "_")
        if not safe.endswith(".txt"):
            safe += ".txt"
        return self._versions / source_id / safe

    def _safe_decode(self, content: bytes, encoding: str) -> str:
        """UTF-8 실패 시 CP949(한국어)로 fallback합니다."""
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            fallback = "cp949" if encoding == "utf-8" else "utf-8"
            logger.warning(
                "decode_fallback",
                primary=encoding,
                fallback=fallback,
            )
            return content.decode(fallback, errors="replace")

    # ── 원본 파일 관리 ──────────────────────────────────

    async def save_file(
        self,
        file_content: bytes,
        filename: str,
        source_id: str,
        source_type: str,
    ) -> str:
        dest = self._upload_path(source_id, filename)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # 같은 이름 파일이 이미 있으면 타임스탬프 접미사 추가
        if dest.exists():
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
            stem, suffix = Path(filename).stem, Path(filename).suffix
            dest = self._upload_path(source_id, f"{stem}_{ts}{suffix}")

        try:
            dest.write_bytes(file_content)
            path_str = str(dest)
            logger.info(
                "file_saved",
                path=path_str,
                bytes=len(file_content),
                source_type=source_type,
            )
            return path_str
        except OSError as exc:
            raise StorageError(f"파일 저장 실패: {dest}") from exc

    async def get_file(self, file_path: str) -> bytes:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundInStorageError(f"파일을 찾을 수 없습니다: {file_path}")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageError(f"파일 읽기 실패: {file_path}") from exc

    async def get_file_text(self, file_path: str, encoding: str = "utf-8") -> str:
        content = await self.get_file(file_path)
        return self._safe_decode(content, encoding)

    async def delete_file(self, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundInStorageError(f"파일을 찾을 수 없습니다: {file_path}")
        try:
            path.unlink()
            # 빈 source_id 폴더도 정리
            parent = path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                shutil.rmtree(parent, ignore_errors=True)
            logger.info("file_deleted", path=file_path)
        except OSError as exc:
            raise StorageError(f"파일 삭제 실패: {file_path}") from exc

    # ── 버전 스냅샷 관리 ─────────────────────────────────

    async def save_version_snapshot(
        self,
        source_id: str,
        version: str,
        content: str,
    ) -> str:
        dest = self._version_path(source_id, version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(content, encoding="utf-8")
            path_str = str(dest)
            logger.info(
                "version_snapshot_saved",
                source_id=source_id,
                version=version,
                path=path_str,
                chars=len(content),
            )
            return path_str
        except OSError as exc:
            raise StorageError(f"버전 스냅샷 저장 실패: {dest}") from exc

    async def get_version_content(self, source_id: str, version: str) -> str:
        path = self._version_path(source_id, version)
        if not path.exists():
            raise VersionNotFoundInStorageError(
                f"버전을 찾을 수 없습니다: source_id={source_id}, version={version}"
            )
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"버전 스냅샷 읽기 실패: {path}") from exc

    async def list_versions(self, source_id: str) -> list[str]:
        version_dir = self._versions / source_id
        if not version_dir.exists():
            return []
        # 파일명(줄기)을 오름차순 정렬: v1, v2, v10 순서 보장
        return sorted(
            p.stem for p in version_dir.glob("*.txt")
        )


# ─────────────────────────────────────────────────────────────
# BlobStorageService — Azure Blob Storage 구현체
# ─────────────────────────────────────────────────────────────

class BlobStorageService(StorageService):
    """
    Azure Blob Storage 기반 스토리지. 프로덕션 환경에서 사용합니다.

    환경변수::

        AZURE_STORAGE_CONNECTION_STRING   Blob Storage 연결 문자열
        AZURE_STORAGE_CONTAINER_UPLOADS   업로드용 컨테이너 (기본: "uploads")
        AZURE_STORAGE_CONTAINER_VERSIONS  버전용 컨테이너 (기본: "versions")

    Blob 경로 규칙::

        업로드: {source_id}/{filename}
        버전:   {source_id}/{version}.txt

    설치::

        pip install azure-storage-blob --break-system-packages
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        uploads_container: str = "uploads",
        versions_container: str = "versions",
    ) -> None:
        self._conn_str = connection_string or os.getenv(
            "AZURE_STORAGE_CONNECTION_STRING", ""
        )
        self._uploads_container = uploads_container
        self._versions_container = versions_container

        if not self._conn_str:
            raise StorageError(
                "AZURE_STORAGE_CONNECTION_STRING 환경변수가 없습니다. "
                "개발 환경에서는 USE_LOCAL_STORAGE=true를 설정하세요."
            )

        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore
            self._client = BlobServiceClient.from_connection_string(self._conn_str)
            self._ensure_containers()
            logger.info(
                "BlobStorageService initialized",
                uploads=uploads_container,
                versions=versions_container,
            )
        except ImportError as exc:
            raise StorageError(
                "azure-storage-blob 패키지가 없습니다. "
                "pip install azure-storage-blob 또는 USE_LOCAL_STORAGE=true 설정."
            ) from exc

    def _ensure_containers(self) -> None:
        for name in (self._uploads_container, self._versions_container):
            try:
                self._client.create_container(name)
            except Exception:
                pass  # 이미 존재하면 무시

    def _blob_client(self, container: str, blob_name: str):
        return self._client.get_blob_client(container=container, blob=blob_name)

    def _url_to_blob_name(self, url_or_path: str, container: str) -> str:
        """
        Blob URL에서 blob 이름을 추출합니다.
        'uploads/src-001/file.pdf' 형식도 처리합니다.
        bc.url은 한글 파일명을 URL-encode하므로 unquote로 디코딩합니다.
        """
        if url_or_path.startswith("https://"):
            parts = url_or_path.split(f"/{container}/", 1)
            if len(parts) == 2:
                return unquote(parts[1])
        return url_or_path

    # ── 원본 파일 관리 ──────────────────────────────────

    async def save_file(
        self,
        file_content: bytes,
        filename: str,
        source_id: str,
        source_type: str,
    ) -> str:
        blob_name = f"{source_id}/{filename}"
        try:
            bc = self._blob_client(self._uploads_container, blob_name)
            bc.upload_blob(
                file_content,
                overwrite=True,
                metadata={"source_type": source_type},
            )
            url = bc.url
            logger.info("blob_file_saved", url=url, bytes=len(file_content))
            return url
        except Exception as exc:
            raise StorageError(f"Blob 저장 실패: {blob_name}") from exc

    async def get_file(self, file_path: str) -> bytes:
        # push 후 file_path가 versions 컨테이너 URL로 바뀔 수 있으므로 URL에서 컨테이너 감지
        if self._versions_container in file_path:
            container = self._versions_container
        else:
            container = self._uploads_container
        blob_name = self._url_to_blob_name(file_path, container)
        try:
            bc = self._blob_client(container, blob_name)
            return bc.download_blob().readall()
        except Exception as exc:
            raise FileNotFoundInStorageError(
                f"Blob 파일을 찾을 수 없습니다: {file_path}"
            ) from exc

    async def get_file_text(self, file_path: str, encoding: str = "utf-8") -> str:
        content = await self.get_file(file_path)
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            return content.decode("cp949", errors="replace")

    async def delete_file(self, file_path: str) -> None:
        blob_name = self._url_to_blob_name(file_path, self._uploads_container)
        try:
            self._blob_client(self._uploads_container, blob_name).delete_blob()
            logger.info("blob_file_deleted", blob=blob_name)
        except Exception as exc:
            raise StorageError(f"Blob 삭제 실패: {blob_name}") from exc

    # ── 버전 스냅샷 관리 ─────────────────────────────────

    async def save_version_snapshot(
        self,
        source_id: str,
        version: str,
        content: str,
    ) -> str:
        blob_name = f"{source_id}/{version}.txt"
        try:
            bc = self._blob_client(self._versions_container, blob_name)
            bc.upload_blob(content.encode("utf-8"), overwrite=True)
            logger.info("blob_version_saved", url=bc.url, version=version)
            return bc.url
        except Exception as exc:
            raise StorageError(f"버전 스냅샷 Blob 저장 실패: {blob_name}") from exc

    async def get_version_content(self, source_id: str, version: str) -> str:
        blob_name = f"{source_id}/{version}.txt"
        try:
            bc = self._blob_client(self._versions_container, blob_name)
            return bc.download_blob().readall().decode("utf-8")
        except Exception as exc:
            raise VersionNotFoundInStorageError(
                f"버전을 찾을 수 없습니다: source_id={source_id}, version={version}"
            ) from exc

    async def list_versions(self, source_id: str) -> list[str]:
        prefix = f"{source_id}/"
        try:
            cc = self._client.get_container_client(self._versions_container)
            blobs = cc.list_blobs(name_starts_with=prefix)
            return sorted(Path(b.name).stem for b in blobs if b.name.endswith(".txt"))
        except Exception as exc:
            raise StorageError(f"버전 목록 조회 실패: {source_id}") from exc


# ─────────────────────────────────────────────────────────────
# 팩토리 + 싱글턴
# ─────────────────────────────────────────────────────────────

def get_storage_service(base_dir: str = "data") -> StorageService:
    """
    환경변수 USE_LOCAL_STORAGE에 따라 적절한 StorageService를 반환합니다.

    USE_LOCAL_STORAGE=true  (기본) → LocalStorageService
    USE_LOCAL_STORAGE=false         → BlobStorageService

    Parameters
    ----------
    base_dir : str
        LocalStorageService의 루트 디렉토리 (기본: "data")

    Examples
    --------
    ::

        storage = get_storage_service()
        path = await storage.save_file(b"...", "script.txt", "src-001", "scenario")
        text = await storage.get_file_text(path)
    """
    use_local = settings.use_local_storage

    if use_local:
        logger.info("storage_mode", mode="local", base_dir=base_dir)
        return LocalStorageService(base_dir=base_dir)

    logger.info("storage_mode", mode="azure_blob")
    return BlobStorageService(
        connection_string=settings.AZURE_STORAGE_CONNECTION_STRING,
        uploads_container=settings.AZURE_STORAGE_CONTAINER_UPLOADS,
        versions_container=settings.AZURE_STORAGE_CONTAINER_VERSIONS,
    )


_storage_instance: Optional[StorageService] = None


def get_global_storage(base_dir: str = "data") -> StorageService:
    """
    앱 전역 싱글턴 StorageService를 반환합니다.
    FastAPI의 Depends() 또는 lifespan에서 사용하세요.

    Examples
    --------
    FastAPI Depends 패턴::

        from app.services.storage import get_global_storage
        from fastapi import Depends

        @app.post("/api/sources/upload")
        async def upload(
            file: UploadFile,
            storage: StorageService = Depends(get_global_storage),
        ):
            path = await storage.save_file(
                await file.read(), file.filename, source_id, source_type
            )
    """
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = get_storage_service(base_dir=base_dir)
    return _storage_instance