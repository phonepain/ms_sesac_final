import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App Settings
    app_name: str = "ContiCheck API"
    debug: bool = True
    
    # Flags based on claude code guide
    use_local_graph: bool = os.getenv("USE_LOCAL_GRAPH", "true").lower() == "true"
    use_mock_extraction: bool = os.getenv("USE_MOCK_EXTRACTION", "false").lower() == "true"
    use_mock_search: bool = os.getenv("USE_MOCK_SEARCH", "false").lower() == "true"
    
    # Azure Cosmos DB (Gremlin)
    cosmos_endpoint: str = os.getenv("COSMOS_ENDPOINT", "wss://localhost:8901/gremlin")
    cosmos_key: str = os.getenv("COSMOS_KEY", "local_key")
    cosmos_database: str = os.getenv("COSMOS_DATABASE", "conticheck_db")
    cosmos_container: str = os.getenv("COSMOS_CONTAINER", "graph")
    
    # Azure AI Search
    search_endpoint: str = os.getenv("SEARCH_ENDPOINT", "https://localhost")
    search_key: str = os.getenv("SEARCH_KEY", "")
    
    # LLM (Azure Foundry)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    
    class Config:
        env_file = ".env"

settings = Settings()
