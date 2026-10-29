from neo4j import AsyncDriver

# architecture §5.1. IF NOT EXISTS makes this safe to run before every write.
STATEMENTS = [
    "CREATE CONSTRAINT service_id IF NOT EXISTS FOR (s:Service) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT dep_key IF NOT EXISTS FOR (d:Dep) REQUIRE (d.service_id, d.key) IS UNIQUE",
    # "Which services hold this package version?" by normalised version, so 1.0 finds 1.0.0.
    # Replaces phase 2's dep_package index on the raw version.
    "DROP INDEX dep_package IF EXISTS",
    "CREATE INDEX dep_package_norm IF NOT EXISTS"
    " FOR (d:Dep) ON (d.ecosystem, d.name, d.norm_version)",
    # Every "all of this service's Dep nodes" lookup. dep_key can't serve it: Neo4j only uses a
    # two-property index when the query names both properties.
    "CREATE INDEX dep_service IF NOT EXISTS FOR (d:Dep) ON (d.service_id)",
    # Finding a repo's stale services.
    "CREATE INDEX service_repo IF NOT EXISTS FOR (s:Service) ON (s.repo_id)",
]


async def ensure_schema(driver: AsyncDriver) -> None:
    for statement in STATEMENTS:
        await driver.execute_query(statement)
