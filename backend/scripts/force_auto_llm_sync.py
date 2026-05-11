"""Force an immediate Auto mode LLM model sync.

Bypasses the periodic poller's "updated_at" cache so providers in Auto mode
get reconciled with the merged (bundled + GitHub) recommendations right now.
Use this after upgrading to a release that adds new providers/models so
existing rows for zai, google_ai_studio, etc. get pruned and refreshed
without waiting for the next poll cycle.

Usage (docker):
    docker exec -it onyx-api_server-1 python -m scripts.force_auto_llm_sync

Usage (kubernetes):
    kubectl exec -it <pod> -- python -m scripts.force_auto_llm_sync

Multi-tenant deployments: pass --tenant-id <id> to target one tenant, or
--all-tenants to iterate every tenant.
"""

import argparse
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.db.engine.sql_engine import get_session_with_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.engine.tenant_utils import get_all_tenant_ids  # noqa: E402
from onyx.llm.well_known_providers.auto_update_service import (  # noqa: E402
    reset_cache,
    sync_llm_models_from_github,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA  # noqa: E402


def _sync_for_tenant(tenant_id: str) -> None:
    print(f"[{tenant_id}] forcing auto LLM sync...")
    reset_cache()
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        results = sync_llm_models_from_github(db_session, force=True)
    if results:
        for provider_name, change_count in results.items():
            print(f"[{tenant_id}]   {provider_name}: {change_count} change(s)")
    else:
        print(f"[{tenant_id}]   no changes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Sync only this tenant. Defaults to the public schema.",
    )
    group.add_argument(
        "--all-tenants",
        action="store_true",
        help="Iterate every tenant in the deployment.",
    )
    args = parser.parse_args()

    SqlEngine.init_engine(pool_size=2, max_overflow=2)

    if args.all_tenants:
        tenant_ids = get_all_tenant_ids()
        if not tenant_ids:
            print("No tenants found.")
            return
        for tenant_id in tenant_ids:
            try:
                _sync_for_tenant(tenant_id)
            except Exception as e:
                print(f"[{tenant_id}] sync failed: {e}")
    else:
        tenant_id = args.tenant_id or POSTGRES_DEFAULT_SCHEMA
        _sync_for_tenant(tenant_id)


if __name__ == "__main__":
    main()
