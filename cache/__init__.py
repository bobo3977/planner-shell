from .base import BasePlanCache
from .sqlite import SQLitePlanCache
from .singlestore import SingleStorePlanCache
import config

def create_plan_cache():
    """Factory to create the appropriate cache based on configuration."""
    backend = getattr(config, 'CACHE_BACKEND', 'sqlite').lower()
    if backend == 'singlestore':
        cache = SingleStorePlanCache(
            host=getattr(config, 'SINGLESTORE_HOST', 'localhost'),
            port=getattr(config, 'SINGLESTORE_PORT', 3306),
            user=getattr(config, 'SINGLESTORE_USER', 'root'),
            password=getattr(config, 'SINGLESTORE_PASSWORD', ''),
            database=getattr(config, 'SINGLESTORE_DATABASE', 'inst_agent'),
            ttl_days=getattr(config, 'PLAN_CACHE_TTL_DAYS', 30)
        )
    else:
        cache = SQLitePlanCache(
            db_path=getattr(config, 'PLAN_CACHE_DB_PATH', '.plan_cache.db'),
            ttl_days=getattr(config, 'PLAN_CACHE_TTL_DAYS', 30)
        )

    # Wire up hybrid search configs
    cache.ALPHA = getattr(config, 'PLAN_CACHE_ALPHA', 0.6)
    cache.MAX_CANDIDATES = getattr(config, 'PLAN_CACHE_MAX_CANDIDATES', 3)
    cache.SCORE_THRESHOLD = getattr(config, 'PLAN_CACHE_SCORE_THRESHOLD', 0.0)

    return cache

__all__ = ['BasePlanCache', 'SQLitePlanCache', 'SingleStorePlanCache', 'create_plan_cache']
