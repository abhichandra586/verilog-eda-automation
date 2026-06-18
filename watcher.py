"""
core/watcher.py — VerilogWatcher

Responsibilities:
  - Monitor src/ and tb/ directories for .v file changes using watchdog
  - Debounce rapid saves (editors often write multiple times per save)
  - Map changed file → owning module via ModuleRegistry.find_by_path()
  - Trigger RegressionRunner + SimulationParser for the affected module
  - Print a compact PASS/FAIL summary to the terminal in real time
  - Never crash on errors — log and keep watching

Design decisions:
  - watchdog FileSystemEventHandler subclass keeps event logic encapsulated
  - Debounce uses a threading.Timer (cancel + restart on rapid events)
  - The watcher runs the full pipeline (compile → simulate → parse) so the
    terminal result is always fresh and reflects the current file state
  - Console output uses ANSI colours for fast visual scanning
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from parser import SimulationParser
from runner import RegressionRunner

logger = logging.getLogger(__name__)

# ANSI color codes
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_AMBER  = "\033[33m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


class VerilogWatcher:
    """
    Watches src/ and tb/ for .v changes and reruns the affected testbench.

    Usage:
        watcher = VerilogWatcher(project_root=Path("."), registry=REGISTRY)
        watcher.start()   # blocks until Ctrl+C
    """

    DEBOUNCE_SECONDS = 0.5      # wait this long after last event before running

    def __init__(
        self,
        project_root: Path,
        registry,
        timeout: int = 60,
        watch_dirs: list[str] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.registry = registry
        self.timeout = timeout
        self.watch_dirs = watch_dirs or ["src", "tb"]

        self._runner = RegressionRunner(project_root=self.project_root, timeout=self.timeout)
        self._parser = SimulationParser()
        self._debounce_timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start watching — blocks until KeyboardInterrupt."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
        except ImportError:
            raise ImportError(
                "watchdog is required for watch mode.\n"
                "Install with: pip install watchdog"
            )

        class _Handler(FileSystemEventHandler):
            def __init__(self_, outer: VerilogWatcher) -> None:
                self_._outer = outer

            def on_modified(self_, event) -> None:
                self_._outer._on_event(Path(event.src_path))

            def on_created(self_, event) -> None:
                self_._outer._on_event(Path(event.src_path))

        observer = Observer()
        handler = _Handler(self)

        watched_count = 0
        for d in self.watch_dirs:
            watch_path = self.project_root / d
            if watch_path.exists():
                observer.schedule(handler, str(watch_path), recursive=True)
                watched_count += 1
                logger.info("Watching: %s", watch_path)

        if watched_count == 0:
            print(f"{_AMBER}Warning: none of {self.watch_dirs} exist under {self.project_root}{_RESET}")
            print("Create them and re-run watch mode.")
            return

        observer.start()
        dirs_display = ", ".join(self.watch_dirs)
        print(f"\n{_CYAN}{_BOLD}⚡ EDA Watch Mode{_RESET}")
        print(f"  Watching: {dirs_display}/  |  root: {self.project_root}")
        print(f"  Debounce: {self.DEBOUNCE_SECONDS}s  |  Press Ctrl+C to stop\n")

        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print(f"\n{_CYAN}Watch mode stopped.{_RESET}")
        finally:
            observer.stop()
            observer.join()

    # ------------------------------------------------------------------
    # Event handling + debounce
    # ------------------------------------------------------------------

    def _on_event(self, path: Path) -> None:
        """Called on every filesystem event. Filter + debounce here."""
        if path.suffix != ".v":
            return

        path_key = str(path)
        with self._lock:
            # Cancel existing debounce timer for this path
            if path_key in self._debounce_timers:
                self._debounce_timers[path_key].cancel()

            timer = threading.Timer(
                self.DEBOUNCE_SECONDS,
                self._handle_change,
                args=[path],
            )
            self._debounce_timers[path_key] = timer
            timer.start()

    def _handle_change(self, path: Path) -> None:
        """Run after debounce period. Look up module and run testbench."""
        module_config = self.registry.find_by_path(path)
        if module_config is None:
            logger.debug("Changed file %s not in any registered module — skipping", path)
            return

        rel = path.relative_to(self.project_root) if path.is_absolute() else path
        print(f"\n{_CYAN}[{time.strftime('%H:%M:%S')}] Changed: {rel}{_RESET}")
        print(f"  → Running testbench for {_BOLD}{module_config.name}{_RESET}")

        t_start = time.perf_counter()
        try:
            run_result = self._runner.run(module_config)
            parsed = self._parser.parse(run_result)
            elapsed = time.perf_counter() - t_start
            self._print_result(parsed, elapsed)
        except Exception as exc:
            logger.exception("Unexpected error running %s", module_config.name)
            print(f"  {_RED}✗ Internal error: {exc}{_RESET}")

    def _print_result(self, parsed, elapsed: float) -> None:
        """Print a compact terminal result."""
        if parsed.status == "PASS":
            icon  = f"{_GREEN}✓{_RESET}"
            color = _GREEN
        elif parsed.status == "FAIL":
            icon  = f"{_RED}✗{_RESET}"
            color = _RED
        else:
            icon  = f"{_AMBER}⚠{_RESET}"
            color = _AMBER

        status_str = f"{color}{_BOLD}{parsed.status}{_RESET}"
        print(f"  {icon} {status_str}  — "
              f"{parsed.passed} pass / {parsed.failed} fail  "
              f"({elapsed:.2f}s)")

        if parsed.fail_lines:
            print(f"  {_RED}Failed tests:{_RESET}")
            for line in parsed.fail_lines[:5]:     # show max 5 to avoid spam
                print(f"    {_RED}{line}{_RESET}")
            if len(parsed.fail_lines) > 5:
                print(f"    {_RED}... and {len(parsed.fail_lines) - 5} more{_RESET}")

        if parsed.error_detail:
            print(f"  {_AMBER}Error: {parsed.error_detail}{_RESET}")

        print()     # blank line for readability
