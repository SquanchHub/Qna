from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"

    DATABASE_URL: str = "mysql+asyncmy://app_user:password@mysql:3306/qna"
    REDIS_URL: str = "redis://redis:6379/0"

    JWT_PRIVATE_KEY: str = ""
    JWT_PUBLIC_KEY: str = ""

    # Required for /auth/oauth2-callback to accept X-Auth-Request-* identity
    # headers. Unset (the default) means the callback refuses every request —
    # fail closed, since those headers are otherwise a trivial impersonation
    # vector for anyone with network access to this service. Set this to a
    # random secret and configure the same value in the OAuth2 reverse proxy
    # sitting in front of this service, which must strip any client-supplied
    # copy of this header and set its own.
    OAUTH2_PROXY_SHARED_SECRET: str = ""

    CORS_ORIGINS: str = (
        "http://localhost:8080,http://localhost:8000,http://localhost:5173"
    )
    FRONTEND_URL: str = "http://localhost:8080"

    # Bootstrap — set once to create the first admin; ignored once an admin exists
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""

    # Course grader account — base64 of a bcrypt hash published by course staff.
    # When set, startup keeps an ADMIN user named "grader" with this hash, so
    # staff can sign in to your deployment without you sharing a password.
    GRADER_PASSWORD_HASH: str = ""

    # RAG (design-rag.md §4.3.2). "Initial" values there are tuned later;
    # RAG_DEFAULT_THRESHOLD is replaced by the §11.2 calibration.
    RAG_LIVE_ENABLED: bool = True
    OLLAMA_URL: str = "http://ollama:11434"
    INFINITY_URL: str = "http://infinity:7997"
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000
    RAG_DEFAULT_PROFILE: str = "sliding-window"
    RAG_DEFAULT_THRESHOLD: float = 0.50
    RAG_DEFAULT_MODEL: str = "qwen2.5:1.5b"
    RAG_TOP_K: int = 4
    RAG_LIVE_GENERATION_TIMEOUT_S: float = 120
    RAG_LIVE_LOCK_WAIT_S: float = 600
    RAG_MAX_PENDING_PER_COURSE: int = 3
    RAG_COMPARE_LOCK_WAIT_S: float = 30
    RAG_COMPARE_EMBED_TIMEOUT_S: float = 15
    RAG_COMPARE_GENERATION_TIMEOUT_S: float = 100
    RAG_INGEST_EMBED_TIMEOUT_S: float = 120
    GITLAB_HOST: str = "git.doit.wisc.edu"
    # read_repository + read_api. A runtime secret: only ever in each machine's
    # .env, never logged, returned, stored in MySQL or set as a CI variable.
    GITLAB_TOKEN: str = ""
    UPLOAD_DIR: str = "/data/uploads"
    CLONE_TMP_DIR: str = "/tmp"
    MAX_UPLOAD_MB: int = 20
    MAX_ZIP_MB: int = 50
    MAX_FETCH_MB: int = 10

    @property
    def chroma_url(self) -> str:
        return f"http://{self.CHROMA_HOST}:{self.CHROMA_PORT}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"


settings = Settings()
