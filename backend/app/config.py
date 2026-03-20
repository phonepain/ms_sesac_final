# backend/app/config.py
import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App Settings
    app_name: str = "ContiCheck API"
    debug: bool = True

    # [CHANGED][PHASE0-3] IDE/CI 환경에서 DEBUG=release 같은 문자열도 bool로 안전 변환
    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if lowered in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value

    # Flags based on claude code guide
    use_local_graph: bool = os.getenv("USE_LOCAL_GRAPH", "true").lower() == "true"
    use_mock_extraction: bool = os.getenv("USE_MOCK_EXTRACTION", "false").lower() == "true"
    use_mock_search: bool = os.getenv("USE_MOCK_SEARCH", "false").lower() == "true"

    # Azure Cosmos DB (Gremlin)
    cosmos_endpoint: str = os.getenv("COSMOS_ENDPOINT", "wss://localhost:8901/gremlin")
    cosmos_key: str = os.getenv("COSMOS_KEY", "local_key")
    cosmos_database: str = os.getenv("COSMOS_DATABASE", "conticheck_db")
    # cosmos_container1: str = os.getenv("COSMOS_CONTAINER", "graph")
    # cosmos_container2: str = os.getenv("COSMOS_CONTAINER", "graph2")
    cosmos_graph_ws: str = os.getenv("COSMOS_GRAPH_WS", "ws-graph")
    cosmos_graph_sc: str = os.getenv("COSMOS_GRAPH_SC", "scenario-graph")

    # Azure AI Search
    search_endpoint: str = os.getenv("SEARCH_ENDPOINT", "https://localhost")
    search_key: str = os.getenv("SEARCH_KEY", "")

    # === [추가] Azure Foundry (LLM) Settings ===
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_EXTRACTION_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_EXTRACTION_DEPLOYMENT", "gpt-5-mini")
    AZURE_OPENAI_NORMALIZATION_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_NORMALIZATION_DEPLOYMENT", "gpt-5-mini")
    AZURE_OPENAI_DETECTION_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DETECTION_DEPLOYMENT", "gpt-5.3-chat")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")  # 최신 API 버전 지원

    class Config:
        # [CHANGED][PHASE0-3] 실행 위치가 backend/여도 저장소 루트 .env를 읽도록 경로 보강
        env_file = (
            str(Path(__file__).resolve().parents[1] / ".env"),  # backend/.env
            str(Path(__file__).resolve().parents[2] / ".env"),  # repo_root/.env
            ".env",  # 기존 동작 보존
        )
        extra = "ignore"  # 정의하지 않은 환경변수는 무시


settings = Settings()
