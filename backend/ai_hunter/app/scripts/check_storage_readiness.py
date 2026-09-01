"""Run the read-only external storage readiness probe."""

from __future__ import annotations

import json

from ai_hunter.app.services.storage_readiness import check_storage_readiness


def main() -> None:
    print(json.dumps(check_storage_readiness(), sort_keys=True))


if __name__ == "__main__":
    main()
