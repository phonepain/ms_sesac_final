from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_bool_like(value: object) -> bool:
    """bool / 문자열 플래그를 안전하게 bool로 파싱한다.

    NOTE: 환경에 DEBUG=release 같은 값이 들어와도 동작하도록 보완.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "t", "yes", "y", "on", "debug", "dev"}:
            return True
        if v in {"0", "false", "f", "no", "n", "off", "release", "prod", "production"}:
            return False
    raise ValueError(f"Cannot parse boolean value from: {value!r}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # App Settings
    app_name: str = "ContiCheck API"
    debug: bool = True
<<<<<<< Updated upstream
    
    # Flags based on claude code guide
    use_local_graph: bool = os.getenv("USE_LOCAL_GRAPH", "true").lower() == "true"
    use_mock_extraction: bool = os.getenv("USE_MOCK_EXTRACTION", "false").lower() == "true"
    use_mock_search: bool = os.getenv("USE_MOCK_SEARCH", "false").lower() == "true"
    
    # Azure Cosmos DB (Gremlin)
    cosmos_endpoint: str = os.getenv("COSMOS_ENDPOINT", "wss://localhost:8901/gremlin")
    cosmos_key: str = os.getenv("COSMOS_KEY", "local_key")
    cosmos_database: str = os.getenv("COSMOS_DATABASE", "conticheck_db")
    #cosmos_container1: str = os.getenv("COSMOS_CONTAINER", "graph")
    #cosmos_container2: str = os.getenv("COSMOS_CONTAINER", "graph2")
    cosmos_graph_ws: str = os.getenv("COSMOS_GRAPH_WS", "ws-graph")
    cosmos_graph_sc: str = os.getenv("COSMOS_GRAPH_SC", "scenario-graph")
    
    # Azure AI Search
    search_endpoint: str = os.getenv("SEARCH_ENDPOINT", "https://localhost")
    search_key: str = os.getenv("SEARCH_KEY", "")
    
    # === [추가됨] Azure Foundry (LLM) Settings ===
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_EXTRACTION_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_EXTRACTION_DEPLOYMENT", "gpt-5-mini")
    AZURE_OPENAI_NORMALIZATION_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_NORMALIZATION_DEPLOYMENT", "gpt-5-mini")
    AZURE_OPENAI_DETECTION_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DETECTION_DEPLOYMENT", "gpt-5.3-chat")
    AZURE_OPENAI_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview") # 최신 API 버전 지정
    
    class Config:
        env_file = ".env"
        extra = "ignore" # 정의되지 않은 환경변수는 무시
=======
    host: str = "0.0.0.0"
    port: int = 8000
>>>>>>> Stashed changes

    # Runtime Flags
    use_local_graph: bool = True
    use_mock_extraction: bool = False
    use_mock_search: bool = False

    # Azure Cosmos DB (Gremlin)
    cosmos_endpoint: str = "wss://localhost:8901/gremlin"
    cosmos_key: str = "local_key"
    cosmos_database: str = "conticheck_db"
    cosmos_container: str = "graph"

    # Azure AI Search
    search_endpoint: str = "https://localhost"
    search_key: str = ""

    # Azure OpenAI (Foundry)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_extraction_deployment: str = "gpt-5-mini"
    azure_openai_normalization_deployment: str = "gpt-5-mini"
    azure_openai_detection_deployment: str = "gpt-5.3-chat"
    azure_openai_api_version: str = "2024-08-01-preview"

    @field_validator("debug", "use_local_graph", "use_mock_extraction", "use_mock_search", mode="before")
    @classmethod
    def _coerce_bool_flags(cls, value: object) -> bool:
        return _parse_bool_like(value)


settings = Settings()
