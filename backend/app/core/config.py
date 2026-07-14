"""Central configuration. Locates the REAL datasets and runtime settings.

No values here fabricate data — they only point the pipeline at real dataset
files on disk and tune real detection/correlation parameters.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo layout:  <repo>/backend/app/core/config.py  -> repo root is parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent
# Datasets live OUTSIDE the repo (they are 24GB and git-ignored): TechM_Code/datasets
WORKSPACE_DIR = REPO_DIR.parent
DEFAULT_DATASETS = WORKSPACE_DIR / "datasets"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VAJRA_", env_file=".env", extra="ignore")

    # ---- paths ----
    datasets_dir: Path = DEFAULT_DATASETS
    var_dir: Path = BACKEND_DIR / "var"          # sqlite db, runtime state (git-ignored)
    config_repo_dir: Path = BACKEND_DIR / "var" / "demo-config"  # real git repo watched for config changes

    # ---- server ----
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # ---- target winner's stack infra ----
    postgres_url: str = "postgresql://postgres:postgres@localhost:5432/vajra_rca"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    kafka_bootstrap_servers: str = "localhost:9092"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"

    # ---- LLM (optional; deterministic fallback always works) ----
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.5-pro"

    # ---- detection ----
    # Isolation Forest contamination is estimated from the data, not hardcoded to a label ratio.
    iforest_contamination: float = 0.1
    iforest_max_train_rows: int = 40000   # cap training rows for fast, real fits

    # ---- correlation / RCA ----
    correlation_window_s: float = 300.0   # 5-minute incident window (per spec "time-window slicing")
    config_causal_window_s: float = 5.0   # config change within 5s => strong causal signal (+30)

    # ---- replay ----
    replay_speed: float = 60.0            # real dataset timestamps compressed by this factor for live demo

    @property
    def nsl_kdd_train(self) -> Path:
        return self.datasets_dir / "KDDTrain+" / "KDDTrain+.txt"

    @property
    def nsl_kdd_test(self) -> Path:
        return self.datasets_dir / "KDDTrain+" / "KDDTest+.txt"

    @property
    def unsw_features(self) -> Path:
        return self.datasets_dir / "UNSW_NB15" / "NUSW-NB15_features.csv"

    @property
    def unsw_raw_files(self) -> list[Path]:
        d = self.datasets_dir / "UNSW_NB15"
        return sorted(d.glob("UNSW-NB15_[1-4].csv"))

    @property
    def unsw_train(self) -> Path:
        return self.datasets_dir / "UNSW_NB15" / "UNSW_NB15_training-set.csv"

    @property
    def unsw_test(self) -> Path:
        return self.datasets_dir / "UNSW_NB15" / "UNSW_NB15_testing-set.csv"

    @property
    def hdfs_structured(self) -> Path:
        return self.datasets_dir / "HDFS" / "HDFS_2k" / "HDFS_2k.log_structured.csv"

    @property
    def hdfs_anomaly_labels(self) -> Path:
        return self.datasets_dir / "HDFS" / "HDFS_v1" / "preprocessed" / "anomaly_label.csv"

    @property
    def db_path(self) -> Path:
        return self.var_dir / "vajra_rca.sqlite"


settings = Settings()
settings.var_dir.mkdir(parents=True, exist_ok=True)
