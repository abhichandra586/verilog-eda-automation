"""
automate.py — EDA Automation Framework CLI

Entry point for all framework commands. This file is intentionally thin:
it parses arguments, sets up logging, then delegates to core/ modules.
No business logic lives here.

Commands:
  run      [--module MOD | --all | --tag TAG]   compile + simulate
  watch    [--module MOD]                        file-watch mode
  report   --json / --html                       generate reports from last run
  vivado   --util FILE --timing FILE             parse Vivado reports
  list                                           list registered modules
  validate                                       check all source files exist

Usage examples:
  python automate.py run --module alu_16bit
  python automate.py run --all
  python automate.py run --tag combinational
  python automate.py watch
  python automate.py vivado --util reports/utilization.txt --timing reports/timing.txt
  python automate.py list
  python automate.py validate
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging — configured before any core imports so all modules inherit it
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool = False) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
    datefmt = "%H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / "eda_automation.log", encoding="utf-8"),
        ],
    )
    # Quieten watchdog's internal INFO spam
    logging.getLogger("watchdog").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


def _resolve_project_root(root: Path) -> Path:
    """
    Find the actual RTL project root within this repository.

    The framework assumes a `src/` and `src/tb/` layout under the project root.
    If the current root does not expose that structure, but a nested
    `Project/` directory does, use it automatically.
    """
    if (root / "src").exists() and (root / "src" / "tb").exists():
        return root

    candidate = root / "Project"
    if (candidate / "src").exists() and (candidate / "src" / "tb").exists():
        logger.debug("Auto-resolved project root to %s", candidate)
        return candidate

    return root

# ---------------------------------------------------------------------------
# Core imports (after logging is configured)
# ---------------------------------------------------------------------------

from modules import REGISTRY
from runner import RegressionRunner
from parser import SimulationParser
from reporter import JsonReporter, HtmlReporter
from watcher import VerilogWatcher
from vivado import VivadoParser


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED   = "\033[31m"
_AMBER = "\033[33m"
_CYAN  = "\033[36m"
_BOLD  = "\033[1m"
_RESET = "\033[0m"

def _ok(msg: str)   -> None: print(f"{_GREEN}✓{_RESET}  {msg}")
def _fail(msg: str) -> None: print(f"{_RED}✗{_RESET}  {msg}")
def _info(msg: str) -> None: print(f"{_CYAN}→{_RESET}  {msg}")
def _warn(msg: str) -> None: print(f"{_AMBER}⚠{_RESET}  {msg}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_list(_args) -> int:
    """List all registered modules."""
    print(f"\n{_BOLD}Registered modules:{_RESET}\n")
    print(REGISTRY.summary())
    print()
    return 0


def cmd_validate(args) -> int:
    """Check that all registered source files exist on disk."""
    root = _resolve_project_root(Path(args.root))
    _info(f"Validating files under: {root.resolve()}")
    issues = REGISTRY.validate(root)
    if not issues:
        _ok("All source files present.")
        return 0
    for module, missing in issues.items():
        _fail(f"Module '{module}' has {len(missing)} missing file(s):")
        for f in missing:
            print(f"      {_RED}{f}{_RESET}")
    return 1


def cmd_run(args) -> int:
    """Compile and simulate one or more modules, then generate reports."""
    root = _resolve_project_root(Path(args.root))

    # Resolve which modules to run
    if args.module:
        try:
            configs = [REGISTRY.get(args.module)]
        except KeyError as e:
            _fail(str(e))
            return 1
    elif args.tag:
        configs = REGISTRY.filter_by_tag(args.tag)
        if not configs:
            _fail(f"No modules found with tag '{args.tag}'")
            return 1
    else:
        configs = REGISTRY.all()   # --all (default when neither flag given)

    runner  = RegressionRunner(project_root=root, timeout=args.timeout)
    parser  = SimulationParser()
    results = []

    total = len(configs)
    print(f"\n{_BOLD}Running {total} module(s)…{_RESET}\n")

    for i, config in enumerate(configs, 1):
        print(f"[{i}/{total}] {_BOLD}{config.name}{_RESET}")
        run_result = runner.run(config)
        parsed     = parser.parse(run_result)
        results.append(parsed)

        if parsed.status == "PASS":
            _ok(f"PASS  — {parsed.passed} tests  ({parsed.total_time:.2f}s)")
        elif parsed.status == "FAIL":
            _fail(f"FAIL  — {parsed.passed} pass / {parsed.failed} fail  ({parsed.total_time:.2f}s)")
            for line in parsed.fail_lines[:3]:
                print(f"         {_RED}{line}{_RESET}")
            if len(parsed.fail_lines) > 3:
                print(f"         {_RED}… and {len(parsed.fail_lines) - 3} more (see report){_RESET}")
        else:
            _warn(f"ERROR — {parsed.error_detail[:80]}")
        print()

    # Summary line
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errors = sum(1 for r in results if r.status == "ERROR")
    total_time = sum(r.total_time for r in results)

    sep = "─" * 44
    print(sep)
    status_color = _GREEN if failed == 0 and errors == 0 else _RED
    print(f"{status_color}{_BOLD}{'PASS' if failed == 0 and errors == 0 else 'FAIL'}{_RESET}  "
          f"{passed}/{total} modules  |  {total_time:.2f}s total")
    print(sep)

    # Generate reports
    if not args.no_json:
        json_path = JsonReporter().write(results)
        _info(f"JSON report → {json_path}")

    if not args.no_html:
        html_path = HtmlReporter().write(results)
        _info(f"HTML report → {html_path}")

    print()
    # Return non-zero exit code on any failure (useful for CI)
    return 0 if (failed == 0 and errors == 0) else 1


def cmd_watch(args) -> int:
    """Start file-watch mode."""
    root = _resolve_project_root(Path(args.root))
    watcher = VerilogWatcher(
        project_root=root,
        registry=REGISTRY,
        timeout=args.timeout,
    )
    try:
        watcher.start()
    except ImportError as e:
        _fail(str(e))
        return 1
    return 0


def cmd_vivado(args) -> int:
    """Parse Vivado utilization and timing reports."""
    util_file   = Path(args.util)   if args.util   else None
    timing_file = Path(args.timing) if args.timing else None

    if util_file is None and timing_file is None:
        _fail("Provide at least --util or --timing (or both)")
        return 1

    parser  = VivadoParser(output_dir=Path("reports"))
    summary = parser.parse(
        utilization_file=util_file,
        timing_file=timing_file,
        clock_period_ns=args.clock_period,
    )
    parser.print_summary(summary)
    out_path = parser.write_summary(summary)
    _info(f"Vivado summary → {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="automate.py",
        description="EDA Automation Framework — compile, simulate, report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root",    default=".", metavar="DIR",
                   help="Project root directory (default: current directory)")
    p.add_argument("--verbose", action="store_true",
                   help="Enable DEBUG logging")

    sub = p.add_subparsers(dest="command", required=True)

    # --- list ---
    sub.add_parser("list", help="List all registered modules")

    # --- validate ---
    sub.add_parser("validate", help="Check all source files exist on disk")

    # --- run ---
    run_p = sub.add_parser("run", help="Compile and simulate module(s)")
    group = run_p.add_mutually_exclusive_group()
    group.add_argument("--module", metavar="NAME",
                       help="Run a single module by name")
    group.add_argument("--all",    action="store_true",
                       help="Run all registered modules (default)")
    group.add_argument("--tag",    metavar="TAG",
                       help="Run all modules with this tag")
    run_p.add_argument("--timeout",  type=int, default=60, metavar="SEC",
                       help="Simulation timeout in seconds (default: 60)")
    run_p.add_argument("--no-json",  action="store_true",
                       help="Skip JSON report generation")
    run_p.add_argument("--no-html",  action="store_true",
                       help="Skip HTML report generation")

    # --- watch ---
    watch_p = sub.add_parser("watch", help="Watch src/ and tb/ for changes")
    watch_p.add_argument("--timeout", type=int, default=60, metavar="SEC",
                         help="Simulation timeout in seconds (default: 60)")

    # --- vivado ---
    viv_p = sub.add_parser("vivado", help="Parse Vivado synthesis reports")
    viv_p.add_argument("--util",   metavar="FILE", help="Path to utilization.txt")
    viv_p.add_argument("--timing", metavar="FILE", help="Path to timing.txt")
    viv_p.add_argument("--clock-period", type=float, metavar="NS",
                       help="Clock period in ns (used to compute Fmax)")

    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()

    _setup_logging(verbose=args.verbose)
    logger.debug("Args: %s", args)

    dispatch = {
        "list":     cmd_list,
        "validate": cmd_validate,
        "run":      cmd_run,
        "watch":    cmd_watch,
        "vivado":   cmd_vivado,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
