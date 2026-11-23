from pydantic_settings import BaseSettings
from functools import lru_cache
class Settings(BaseSettings):
    database_url: str = "sqlite:///./vyom.db"
    dataset_dir: str = "../data/esa_adb/mission1/ESA-Mission1"
    cors_origins: str = "http://localhost:5173"
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    nebius_api_key: str = ""
    nebius_model: str = ""
    tavily_api_key: str = ""
    telemetry_store_dir: str = "../artifacts/telemetry"
    experiment_dir: str = "../artifacts/experiments"
    ingestion_row_group_size: int = 250000
    analysis_batch_size: int = 25000
    analysis_max_train_rows: int = 20000
    unlabelled_policy: str = "exclude"
    class Config: env_file = ".env"
    @property
    def origins(self): return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
@lru_cache
def settings(): return Settings()
