"""
core/runner.py — RegressionRunner

Responsibilities:
  - Validate all source and testbench files exist before touching the shell
  - Build and execute the iverilog compile command
  - Build and execute the vvp simulate command
  - Time each phase independently with perf_counter
  - Capture stdout/stderr without mixing them
  - Return a structured RunResult — never print, never raise on sim failure

Design decisions:
  - subprocess.run() with timeout, not Popen, keeps the code simple and safe
  - compile and run are separate methods so the parser can distinguish
    compile errors from simulation errors
  - The runner is stateless: create one instance, call run() many times
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data contracts (produced by this module, consumed by parser.py)
# ---------------------------------------------------------------------------

@dataclass
class CompileResult:
    success: bool
    command: str
    stdout: str
    stderr: str
    elapsed: float          # seconds


@dataclass
class SimResult:
    success: bool
    command: str
    stdout: str
    stderr: str
    elapsed: float          # seconds


@dataclass
class RunResult:
    """
    Complete result of compiling + simulating one module.
    This is the data contract passed to SimulationParser.
    """
    module: str
    compile: CompileResult
    sim: Optional[SimResult]   # None if compile failed
    total_elapsed: float

    @property
    def stdout(self) -> str:
        """Combined simulation stdout — what the parser reads."""
        return self.sim.stdout if self.sim else ""

    @property
    def stderr(self) -> str:
        """Combined stderr from both phases."""
        parts = []
        if self.compile.stderr:
            parts.append(self.compile.stderr)
        if self.sim and self.sim.stderr:
            parts.append(self.sim.stderr)
        return "\n".join(parts)

    @property
    def succeeded(self) -> bool:
        return self.compile.success and self.sim is not None and self.sim.success


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class RegressionRunner:
    """
    Compiles and simulates a single RTL module using iverilog + vvp.

    Usage:
        runner = RegressionRunner(project_root=Path("."), timeout=60)
        result = runner.run(module_config)
    """

    SIM_BINARY = "sim.vvp"          # intermediate compiled binary

    def __init__(
        self,
        project_root: Path,
        timeout: int = 60,
        iverilog_bin: str = "iverilog",
        vvp_bin: str = "vvp",
    ) -> None:
        self.project_root = project_root.resolve()
        self.timeout = timeout
        self.iverilog_bin = iverilog_bin
        self.vvp_bin = vvp_bin
        self._sim_path = self.project_root / self.SIM_BINARY

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, config) -> RunResult:
        """
        Full compile + simulate cycle for the given ModuleConfig.
        Never raises — all errors are captured in the returned RunResult.
        """
        module_name = config.name
        logger.info("Starting regression run for module: %s", module_name)
        t_start = time.perf_counter()

        # 1. Pre-flight: validate files exist
        missing = self._validate_files(config)
        if missing:
            msg = f"Missing files: {', '.join(missing)}"
            logger.error("[%s] %s", module_name, msg)
            compile_result = CompileResult(
                success=False,
                command="",
                stdout="",
                stderr=msg,
                elapsed=0.0,
            )
            return RunResult(
                module=module_name,
                compile=compile_result,
                sim=None,
                total_elapsed=time.perf_counter() - t_start,
            )

        # 2. Compile
        compile_result = self._compile(config)
        if not compile_result.success:
            logger.warning("[%s] Compilation failed", module_name)
            return RunResult(
                module=module_name,
                compile=compile_result,
                sim=None,
                total_elapsed=time.perf_counter() - t_start,
            )

        # 3. Simulate
        sim_result = self._simulate(module_name)
        total = time.perf_counter() - t_start
        logger.info(
            "[%s] Done — compile: %.2fs, sim: %.2fs, total: %.2fs",
            module_name,
            compile_result.elapsed,
            sim_result.elapsed,
            total,
        )

        return RunResult(
            module=module_name,
            compile=compile_result,
            sim=sim_result,
            total_elapsed=total,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_files(self, config) -> list[str]:
        """Return list of missing file paths (empty = all present)."""
        missing = []
        for p in config.all_paths(self.project_root):
            if not p.exists():
                missing.append(str(p))
        return missing

    def _compile(self, config) -> CompileResult:
        """Run iverilog to produce sim.vvp."""
        src_paths = [str(p) for p in config.src_paths(self.project_root)]
        tb_path = str(config.tb_path(self.project_root))
        cmd = [
            self.iverilog_bin,
            "-o", str(self._sim_path),
            "-Wall",            # all warnings
            "-g2012",           # SystemVerilog 2012 standard
            *src_paths,
            tb_path,
        ]
        cmd_str = " ".join(cmd)
        logger.debug("[%s] Compile: %s", config.name, cmd_str)

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.project_root,
            )
            elapsed = time.perf_counter() - t0
            success = proc.returncode == 0
            if not success:
                logger.debug("[%s] iverilog stderr: %s", config.name, proc.stderr)
            return CompileResult(
                success=success,
                command=cmd_str,
                stdout=proc.stdout,
                stderr=proc.stderr,
                elapsed=elapsed,
            )
        except FileNotFoundError:
            elapsed = time.perf_counter() - t0
            msg = (
                f"'{self.iverilog_bin}' not found. "
                "Install Icarus Verilog. On Linux: sudo apt install iverilog. "
                "On macOS: brew install icarus-verilog. "
                "On Windows: install from https://bleyer.org/icarus/ or use Chocolatey."
            )
            logger.error(msg)
            return CompileResult(success=False, command=cmd_str, stdout="", stderr=msg, elapsed=elapsed)
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t0
            msg = f"Compilation timed out after {self.timeout}s"
            logger.error("[%s] %s", config.name, msg)
            return CompileResult(success=False, command=cmd_str, stdout="", stderr=msg, elapsed=elapsed)

    def _simulate(self, module_name: str) -> SimResult:
        """Run vvp on the compiled binary."""
        cmd = [self.vvp_bin, str(self._sim_path)]
        cmd_str = " ".join(cmd)
        logger.debug("[%s] Simulate: %s", module_name, cmd_str)

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.project_root,
            )
            elapsed = time.perf_counter() - t0
            # vvp exit code 0 even on sim assertion failures — success here
            # means the process ran; the parser determines PASS/FAIL from output
            return SimResult(
                success=True,
                command=cmd_str,
                stdout=proc.stdout,
                stderr=proc.stderr,
                elapsed=elapsed,
            )
        except FileNotFoundError:
            elapsed = time.perf_counter() - t0
            msg = (
                f"'{self.vvp_bin}' not found. "
                "Install Icarus Verilog. On Linux: sudo apt install iverilog. "
                "On macOS: brew install icarus-verilog. "
                "On Windows: install from https://bleyer.org/icarus/ or use Chocolatey."
            )
            logger.error(msg)
            return SimResult(success=False, command=cmd_str, stdout="", stderr=msg, elapsed=elapsed)
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t0
            msg = f"Simulation timed out after {self.timeout}s — possible infinite loop in testbench"
            logger.error("[%s] %s", module_name, msg)
            return SimResult(success=False, command=cmd_str, stdout="", stderr=msg, elapsed=elapsed)
