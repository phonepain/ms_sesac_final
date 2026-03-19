from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_bool_like(value: object) -> bool:
    """Parse bool-like values from env/user input safely."""
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

    # App
    app_name: str = "ContiCheck API"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # Runtime Flags
    use_local_graph: bool = True
    use_mock_extraction: bool = False
    use_mock_search: bool = False

    # Azure Cosmos DB (Gremlin)
    cosmos_endpoint: str = "wss://localhost:8901/gremlin"
    cosmos_key: str = "local_key"
    cosmos_database: str = "conticheck_db"
    cosmos_container: str = "graph"
    # Optional split-graph names used by some environments
    cosmos_graph_ws: str = "ws-graph"
    cosmos_graph_sc: str = "scenario-graph"

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

    # Backward-compat for legacy code still using uppercase config attributes.
    @property
    def AZURE_OPENAI_ENDPOINT(self) -> str:
        return self.azure_openai_endpoint

    @property
    def AZURE_OPENAI_API_KEY(self) -> str:
        return self.azure_openai_api_key

    @property
    def AZURE_OPENAI_EXTRACTION_DEPLOYMENT(self) -> str:
        return self.azure_openai_extraction_deployment

    @property
    def AZURE_OPENAI_NORMALIZATION_DEPLOYMENT(self) -> str:
        return self.azure_openai_normalization_deployment

    @property
    def AZURE_OPENAI_DETECTION_DEPLOYMENT(self) -> str:
        return self.azure_openai_detection_deployment

    @property
    def AZURE_OPENAI_API_VERSION(self) -> str:
        return self.azure_openai_api_version


settings = Settings()
