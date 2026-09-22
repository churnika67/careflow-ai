import psycopg

from app.core.config import Settings


async def connect(settings: Settings) -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(settings.database_url.get_secret_value())
