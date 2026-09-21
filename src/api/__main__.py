import uvicorn

from src.api.app import app
from src.api.settings import Settings


if __name__ == '__main__':
    settings = Settings.from_env()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level='info')
