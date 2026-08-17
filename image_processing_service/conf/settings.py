from .db import DatabaseSettings


class Settings(DatabaseSettings):
    project_name: str = "image-processing-service"
    debug: bool = False
