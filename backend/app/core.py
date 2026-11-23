from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "VYOM Mission Intelligence"
    app_version: str = "2.0.0"
    database_url: str = "sqlite:///./vyom.db"
    dataset_dir: str = "../data/esa_adb/mission1/ESA-Mission1"
    telemetry_store_dir: str = "../artifacts/milestone12/telemetry"
    artifact_dir: str = "../artifacts/final"
    cors_origins: str = "http://localhost:5173"
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    nebius_api_key: str = ""
    nebius_model: str = ""
    tavily_api_key: str = ""
    langsmith_api_key: str = ""
    langsmith_project: str = "VYOM"
    api_key: str = ""
    benchmark_batch_rows: int = 5000
    max_training_rows: int = 10000
    default_plot_points: int = 1400

    # Legacy M1 configuration names retained so the original pipeline/tests
    # remain valid after the final-product upgrade.
    ingestion_row_group_size: int = 250000
    analysis_batch_size: int = 25000
    analysis_max_train_rows: int = 20000
    unlabelled_policy: str = "exclude"
    experiment_dir: str = "../artifacts/experiments"

    @property
    def origins(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    def resolve(self, value: str) -> Path:
        p = Path(value).expanduser()
        if p.is_absolute():
            return p
        return (Path.cwd() / p).resolve()

@lru_cache
def settings() -> Settings:
    return Settings()
