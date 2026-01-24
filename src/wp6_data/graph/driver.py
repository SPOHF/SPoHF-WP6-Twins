"""Neo4j async driver management."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

logger = structlog.get_logger()


class Neo4jConnection:
    """Async Neo4j connection manager for Aura."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ):
        self._driver: AsyncDriver | None = None
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database

    async def connect(self) -> None:
        """Initialize driver connection."""
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
            max_connection_lifetime=300,
        )
        # Verify connectivity
        await self._driver.verify_connectivity()
        logger.info("neo4j_connected", uri=self._safe_uri)

    async def close(self) -> None:
        """Close driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("neo4j_disconnected")

    @property
    def _safe_uri(self) -> str:
        """URI without credentials for logging."""
        # bolt+s://xxx.databases.neo4j.io -> xxx.databases.neo4j.io
        return self._uri.split("://")[-1].split("@")[-1]

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Get async session for queries."""
        if not self._driver:
            raise RuntimeError("Driver not connected - call connect() first")
        async with self._driver.session(database=self._database) as session:
            yield session

    async def ensure_schema(self, constraints: list[str]) -> None:
        """Create constraints and indexes if they don't exist."""
        async with self.session() as session:
            for constraint in constraints:
                try:
                    await session.run(constraint)
                    logger.debug("schema_applied", query=constraint[:60])
                except Exception as e:
                    # Constraint already exists or other non-fatal error
                    logger.debug("schema_skip", error=str(e)[:100])
