#!/usr/bin/env python3
"""
Autonomous Cycle Command - CHECKPOINT C / E3

This script is a thin CLI wrapper around the AutonomousCycleService.
The actual autonomous cycle logic is in backend/services/autonomous_cycle/service.py.

This script runs the complete autonomous job application cycle by calling the existing
services in sequence with the required constraints:
discovery -> hard filters -> AI queue -> Gemini -> final safety gate -> ApplicationRunner

It supports:
- --max-applications N: limit on real applications (default 1)
- --dry-run: discovery and analysis only, no Apply clicks or application records
- --max-jobs N: cap on jobs inspected per run
- --max-cards N: cap on cards scanned per run (default 150)

No input() prompts. Exit code 0 on normal completion, non-zero on AUTH/SECURITY/critical stop.
"""

import argparse
import asyncio
import sys
from typing import Optional

from backend.services.autonomous_cycle import AutonomousCycle


def main():
    parser = argparse.ArgumentParser(description="Run autonomous job application cycle")
    parser.add_argument(
        "--max-applications",
        type=int,
        default=1,
        help="Maximum number of real applications to perform (default: 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discovery and analysis only, no Apply clicks or application records"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap on jobs inspected per run (default: unlimited)"
    )
    parser.add_argument(
        "--max-cards",
        type=int,
        default=150,
        help="Maximum number of search cards to scan (default: 150)",
    )

    args = parser.parse_args()

    # Create AutonomousCycle instance with CLI output enabled
    cycle = AutonomousCycle(
        max_applications=args.max_applications,
        dry_run=args.dry_run,
        max_jobs=args.max_jobs,
        max_cards=args.max_cards,
        enable_cli_output=True,
    )

    # Run the cycle and get the result
    result = asyncio.run(cycle.run())
    exit_code = result.get("exit_code", 3)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
