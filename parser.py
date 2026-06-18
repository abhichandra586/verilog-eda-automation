"""
core/parser.py — SimulationParser

Responsibilities:
  - Parse raw simulation stdout into typed, structured data
  - Extract PASS/FAIL counts from standard testbench output format
  - Collect individual FAIL lines for reporting
  - Detect error conditions (timeout, compile failure, empty output)
  - Return a ParsedResult dataclass — no printing, no side effects

Expected testbench output format:
  Results: PASS=22 FAIL=0
  (any lines containing FAIL, ERROR, or assertion failures are collected)

Design decisions:
  - All parsing via re (regex) — no string splitting heuristics
  - Multiple fallback patterns in priority order so slightly different
    testbench styles still parse correctly
  - ParsedResult.status is always one of: "PASS" | "FAIL" | "ERROR"
    making downstream if-statements clean and predictable
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from runner import RunResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data contract (produced here, consumed by reporter.py)
# ---------------------------------------------------------------------------

@dataclass
class ParsedResult:
    """
    Structured interpretation of one module's simulation run.
    This is the data contract passed to the reporters.
    """
    module: str
    status: str             # "PASS" | "FAIL" | "ERROR"
    passed: int
    failed: int
    fail_lines: list[str]   # individual lines containing failures
    warnings: list[str]     # lines with WARNING keyword
    compile_time: float     # seconds
    sim_time: float         # seconds
    total_time: float       # seconds
    raw_output: str         # full stdout for expandable log in HTML report
    error_detail: str = ""  # populated on ERROR status (compile fail, timeout)

    @property
    def total_tests(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return self.passed / self.total_tests * 100


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Pattern: "Results: PASS=22 FAIL=0"  (primary — matches our testbench convention)
_RESULTS_PATTERN = re.compile(
    r"Results?.*?PASS\s*[=:]\s*(\d+).*?FAIL\s*[=:]\s*(\d+)",
    re.IGNORECASE,
)

# Pattern: "22 tests passed, 0 failed"  (alternative testbench style)
_TESTS_PASSED_PATTERN = re.compile(
    r"(\d+)\s+tests?\s+passed.*?(\d+)\s+failed",
    re.IGNORECASE,
)

# Pattern: standalone "PASSED: 22" and "FAILED: 0" on separate lines
_STANDALONE_PASS = re.compile(r"PASSED\s*[=:]\s*(\d+)", re.IGNORECASE)
_STANDALONE_FAIL = re.compile(r"FAILED\s*[=:]\s*(\d+)", re.IGNORECASE)

# Lines that indicate individual test failures.
# Must NOT match the summary "Results: PASS=N FAIL=N" line.
_FAIL_LINE_PATTERN = re.compile(
    r"(FAIL:|ERROR:|ASSERT|mismatch|unexpected)",
    re.IGNORECASE,
)
_SUMMARY_LINE_PATTERN = re.compile(
    r"Results?.*PASS\s*[=:]\s*\d+.*FAIL\s*[=:]\s*\d+",
    re.IGNORECASE,
)

# Lines that are warnings
_WARN_LINE_PATTERN = re.compile(r"\bWARNING\b", re.IGNORECASE)


class SimulationParser:
    """
    Converts a RunResult into a ParsedResult.

    Usage:
        parser = SimulationParser()
        parsed = parser.parse(run_result)
    """

    def parse(self, run_result: RunResult) -> ParsedResult:
        """
        Parse a RunResult into a structured ParsedResult.
        Never raises — error conditions become status="ERROR".
        """
        module = run_result.module

        # --- Compile failure ---
        if not run_result.compile.success:
            logger.warning("[%s] Compile failed — marking ERROR", module)
            return ParsedResult(
                module=module,
                status="ERROR",
                passed=0,
                failed=0,
                fail_lines=[],
                warnings=[],
                compile_time=run_result.compile.elapsed,
                sim_time=0.0,
                total_time=run_result.total_elapsed,
                raw_output=run_result.stderr,
                error_detail=f"Compilation failed:\n{run_result.compile.stderr}",
            )

        # --- Simulation did not run (timeout or tool missing) ---
        if run_result.sim is None or not run_result.sim.success:
            detail = run_result.sim.stderr if run_result.sim else "Simulation did not run"
            logger.warning("[%s] Simulation error — marking ERROR", module)
            return ParsedResult(
                module=module,
                status="ERROR",
                passed=0,
                failed=0,
                fail_lines=[],
                warnings=[],
                compile_time=run_result.compile.elapsed,
                sim_time=run_result.sim.elapsed if run_result.sim else 0.0,
                total_time=run_result.total_elapsed,
                raw_output=detail,
                error_detail=detail,
            )

        stdout = run_result.stdout
        lines = stdout.splitlines()

        passed, failed, summary_found = self._extract_counts(stdout, lines)
        fail_lines = self._collect_fail_lines(lines)
        warnings = self._collect_warnings(lines)

        if passed == 0 and failed == 0 and fail_lines:
            failed = len(fail_lines)
            logger.debug(
                "[%s] No summary line found; inferred %d failures from FAIL lines",
                module, failed,
            )

        status = "PASS"
        error_detail = ""

        if not stdout.strip():
            status = "ERROR"
            error_detail = "Simulation produced no output — check $finish and $display in testbench"
            logger.warning("[%s] %s", module, error_detail)
        elif failed > 0:
            status = "FAIL"
        elif not summary_found:
            warnings.append(
                "No PASS/FAIL summary line found in simulation output; counts may be incomplete."
            )
            logger.warning(
                "[%s] No summary line found; marking PASS by absence of failure indicators.",
                module,
            )

        logger.info(
            "[%s] Parsed — status=%s  PASS=%d  FAIL=%d",
            module, status, passed, failed,
        )

        return ParsedResult(
            module=module,
            status=status,
            passed=passed,
            failed=failed,
            fail_lines=fail_lines,
            warnings=warnings,
            compile_time=run_result.compile.elapsed,
            sim_time=run_result.sim.elapsed,
            total_time=run_result.total_elapsed,
            raw_output=stdout,
            error_detail=error_detail,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_counts(self, stdout: str, lines: list[str]) -> tuple[int, int, bool]:
        """
        Try multiple regex patterns in priority order.
        Returns (passed, failed, summary_found).
        """
        # Primary: "Results: PASS=22 FAIL=0"
        m = _RESULTS_PATTERN.search(stdout)
        if m:
            return int(m.group(1)), int(m.group(2)), True

        # Secondary: "22 tests passed, 0 failed"
        m = _TESTS_PASSED_PATTERN.search(stdout)
        if m:
            return int(m.group(1)), int(m.group(2)), True

        # Tertiary: standalone PASSED/FAILED lines (scan all lines)
        passed = failed = None
        for line in lines:
            if passed is None:
                mp = _STANDALONE_PASS.search(line)
                if mp:
                    passed = int(mp.group(1))
            if failed is None:
                mf = _STANDALONE_FAIL.search(line)
                if mf:
                    failed = int(mf.group(1))
            if passed is not None and failed is not None:
                break

        if passed is not None and failed is not None:
            return passed, failed, True

        return 0, 0, False

    def _collect_fail_lines(self, lines: list[str]) -> list[str]:
        """Collect lines that indicate individual test failures.
        Excludes the summary 'Results: PASS=N FAIL=N' line."""
        return [
            line.strip()
            for line in lines
            if _FAIL_LINE_PATTERN.search(line)
            and not _SUMMARY_LINE_PATTERN.search(line)
        ]

    def _collect_warnings(self, lines: list[str]) -> list[str]:
        """Collect lines that contain warnings."""
        return [
            line.strip()
            for line in lines
            if _WARN_LINE_PATTERN.search(line)
        ]
