# backend/app/config.py
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    # App Settings
    app_name: str = "ContiCheck API"
    debug: bool = True

    # Flags
    use_local_graph: bool = True
    use_mock_extraction: bool = False
    use_mock_search: bool = False
    use_local_storage: bool = True

    # Azure Cosmos DB (Gremlin)
    cosmos_endpoint: str = "wss://localhost:8901/gremlin"
    cosmos_key: str = "local_key"
    cosmos_database: str = "conticheck_db"
    cosmos_graph_ws: str = "ws-graph"
    cosmos_graph_sc: str = "scenario-graph"

    # Azure AI Search
    search_endpoint: str = "https://localhost"
    search_key: str = ""

    # Azure Blob Storage
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_STORAGE_CONTAINER_UPLOADS: str = "conticheck-uploads"
    AZURE_STORAGE_CONTAINER_VERSIONS: str = "conticheck-versions"

    # Azure OpenAI (LLM)
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_EXTRACTION_DEPLOYMENT: str = "gpt-5.4-mini"
    AZURE_OPENAI_NORMALIZATION_DEPLOYMENT: str = "gpt-5.4-mini"
    AZURE_OPENAI_DETECTION_DEPLOYMENT: str = "gpt-5.3-chat"
    AZURE_OPENAI_API_VERSION: str = "2024-08-01-preview"

    model_config = ConfigDict(env_file=".env", extra="ignore")

settings = Settings()