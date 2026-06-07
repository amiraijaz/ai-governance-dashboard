"""Push governance-bench-v1 + its dataset card to the HuggingFace Hub.

Requires `pip install huggingface_hub` and an HF token with `write` scope.

Manual steps (run once before first push):

    pip install huggingface_hub
    huggingface-cli login                  # paste your token (write scope)

    # Or set the env var instead:
    export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx

Usage:

    # Default: push to amiraijaz/governance-bench-v1
    python upload_to_hf.py

    # Override the destination repo
    python upload_to_hf.py --repo your-org/governance-bench-v1

    # Dry run: print what would be uploaded
    python upload_to_hf.py --dry-run

The script is idempotent — re-running pushes only the changed files.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_REPO = "amiraijaz/governance-bench-v1"
ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "governance_bench_v1.jsonl"
CARD_FILE = ROOT / "README.md"


def _require_data() -> None:
    if not DATA_FILE.exists():
        sys.exit(
            f"error: {DATA_FILE} not found. Run `python build_dataset.py` "
            "first to generate it."
        )
    if not CARD_FILE.exists():
        sys.exit(f"error: {CARD_FILE} not found. Create the dataset card first.")


def _get_token() -> str:
    tok = (os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or "").strip()
    if tok:
        return tok
    # huggingface_hub will fall back to the cached token from
    # `huggingface-cli login`. We let it; only raise if nothing's available.
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Hub repo id (default: {DEFAULT_REPO}).",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create the repo as private. Default is public (a benchmark).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the upload plan and exit. No network calls.",
    )
    args = parser.parse_args()

    _require_data()

    files = [
        (CARD_FILE, "README.md"),
        (DATA_FILE, "data/governance_bench_v1.jsonl"),
    ]

    if args.dry_run:
        print(f"[dry-run] would push to: {args.repo} (private={args.private})")
        for local, remote in files:
            print(f"[dry-run]   {local}  ->  {remote}  ({local.stat().st_size:,} bytes)")
        return

    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        sys.exit(
            "error: huggingface_hub is not installed. "
            "Run: pip install huggingface_hub"
        )

    token = _get_token() or None

    print(f"[hf] ensuring dataset repo {args.repo} exists ...")
    create_repo(
        repo_id=args.repo,
        repo_type="dataset",
        token=token,
        private=args.private,
        exist_ok=True,
    )

    api = HfApi(token=token)
    for local, remote in files:
        print(f"[hf] uploading {local.name} -> {remote}")
        api.upload_file(
            path_or_fileobj=str(local),
            path_in_repo=remote,
            repo_id=args.repo,
            repo_type="dataset",
        )

    print(
        f"[hf] done. View at https://huggingface.co/datasets/{args.repo}"
    )


if __name__ == "__main__":
    main()
