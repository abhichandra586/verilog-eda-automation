"""
modules.py — Module Registry for EDA Automation Framework

This is the ONLY file that needs updating when new RTL modules are added.
Framework code (runner, parser, reporter) never changes for new modules.

Dependency ordering in 'src' lists is CRITICAL:
  iverilog compiles left-to-right, so dependencies must come before dependents.
  Example: half_adder.v must precede full_adder.v which must precede addsub_16bit.v

Path convention:
  All paths are relative to the project root (where automate.py lives).
  Since the RTL project and framework share the same repo, no cross-repo
  path resolution is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data contract: one ModuleConfig per RTL testbench
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModuleConfig:
    """
    Immutable description of one RTL module and its testbench.

    Attributes:
        name:        Canonical module name (matches the key in REGISTRY).
        src:         Source files in dependency order, relative to project root.
        tb:          Testbench file, relative to project root.
        description: Human-readable summary shown in reports.
        tags:        Optional labels for filtering (e.g. 'combinational', 'alu').
    """
    name: str
    src: list[str]
    tb: str
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def src_paths(self, root: Path) -> list[Path]:
        """Return fully-resolved source paths under the given project root."""
        return [root / s for s in self.src]

    def tb_path(self, root: Path) -> Path:
        """Return the fully-resolved testbench path under the given project root."""
        return root / self.tb

    def all_paths(self, root: Path) -> list[Path]:
        """Return all paths (src + tb) — used by the file watcher."""
        return self.src_paths(root) + [self.tb_path(root)]


# ---------------------------------------------------------------------------
# Registry definition
# ---------------------------------------------------------------------------
#
# HOW TO ADD A NEW MODULE:
#   1. Add an entry to _RAW_REGISTRY below.
#   2. List src files in strict dependency order (leaf dependencies first).
#   3. Point tb at the testbench file.
#   4. Run: python automate.py run --module your_new_module
#
# Nothing else in the framework needs to change.
# ---------------------------------------------------------------------------

_RAW_REGISTRY: dict[str, dict] = {

    # -----------------------------------------------------------------------
    # 02-combinational-circuits
    # -----------------------------------------------------------------------

    "half_adder": {
        "src": [
            "src/half_adder.v",
        ],
        "tb": "src/tb/half_adder_tb.v",
        "description": "1-bit half adder: sum and carry outputs",
        "tags": ["combinational", "adder"],
    },

    "full_adder": {
        "src": [
            "src/half_adder.v",
            "src/full_adder.v",
        ],
        "tb": "src/tb/full_adder_tb.v",
        "description": "1-bit full adder with carry-in, built from half adders",
        "tags": ["combinational", "adder"],
    },

    "addsub_16bit": {
        "src": [
            "src/half_adder.v",
            "src/full_adder.v",
            "src/addsub_16bit.v",
        ],
        "tb": "src/tb/addsub_16bit_tb.v",
        "description": "16-bit adder/subtractor with overflow detection",
        "tags": ["combinational", "adder", "16bit"],
    },

    "alu_16bit": {
        "src": [
            "src/half_adder.v",
            "src/full_adder.v",
            "src/addsub_16bit.v",
            "src/alu_16bit.v",
        ],
        "tb": "src/tb/alu_16bit_tb.v",
        "description": "16-bit ALU supporting arithmetic and logic operations",
        "tags": ["combinational", "alu", "16bit"],
    },

    # -----------------------------------------------------------------------
    # Future modules — uncomment and fill in as the project grows
    # -----------------------------------------------------------------------

    # "register_file": {
    #     "src": [
    #         "src/register_file.v",
    #     ],
    #     "tb": "tb/register_file_tb.v",
    #     "description": "16-register file with dual read ports and single write port",
    #     "tags": ["sequential", "register"],
    # },

    # "program_counter": {
    #     "src": [
    #         "src/program_counter.v",
    #     ],
    #     "tb": "tb/program_counter_tb.v",
    #     "description": "16-bit program counter with load and increment",
    #     "tags": ["sequential", "control"],
    # },

    # "control_unit": {
    #     "src": [
    #         "src/half_adder.v",
    #         "src/full_adder.v",
    #         "src/addsub_16bit.v",
    #         "src/alu_16bit.v",
    #         "src/register_file.v",
    #         "src/program_counter.v",
    #         "src/control_unit.v",
    #     ],
    #     "tb": "tb/control_unit_tb.v",
    #     "description": "Instruction decoder and control signal generator",
    #     "tags": ["sequential", "control", "pipeline"],
    # },
}


# ---------------------------------------------------------------------------
# ModuleRegistry — the public API for the rest of the framework
# ---------------------------------------------------------------------------

class ModuleRegistry:
    """
    Provides validated, queryable access to the module registry.

    Usage:
        registry = ModuleRegistry()
        config   = registry.get("alu_16bit")
        all_mods = registry.all()
        alu_mods = registry.filter_by_tag("alu")
    """

    def __init__(self) -> None:
        self._modules: dict[str, ModuleConfig] = {
            name: ModuleConfig(name=name, **data)
            for name, data in _RAW_REGISTRY.items()
        }

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> ModuleConfig:
        """
        Return the ModuleConfig for the given module name.

        Raises:
            KeyError: with a helpful message listing valid names.
        """
        if name not in self._modules:
            valid = ", ".join(sorted(self._modules))
            raise KeyError(
                f"Module '{name}' not found in registry.\n"
                f"Valid modules: {valid}"
            )
        return self._modules[name]

    def all(self) -> list[ModuleConfig]:
        """Return all registered modules in definition order."""
        return list(self._modules.values())

    def names(self) -> list[str]:
        """Return all module names — used for CLI tab-completion and --list."""
        return list(self._modules.keys())

    def filter_by_tag(self, tag: str) -> list[ModuleConfig]:
        """Return all modules carrying the given tag."""
        return [m for m in self._modules.values() if tag in m.tags]

    def find_by_path(self, path: Path) -> Optional[ModuleConfig]:
        """
        Given a filesystem path, return the first module that owns that file.
        Used by the file watcher to map a changed .v file → its module.

        Returns None if the path doesn't belong to any registered module.
        """
        # We compare by suffix only (no root needed for matching).
        # The watcher passes absolute paths; we compare the relative portion.
        path_str = path.as_posix()
        for module in self._modules.values():
            all_relative = module.src + [module.tb]
            if any(path_str.endswith(rel) for rel in all_relative):
                return module
        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, root: Path) -> dict[str, list[str]]:
        """
        Check that every file in the registry exists on disk.

        Returns:
            A dict mapping module name → list of missing file paths.
            An empty dict means everything is present.

        Usage:
            issues = registry.validate(Path("."))
            if issues:
                for module, missing in issues.items():
                    print(f"{module}: missing {missing}")
        """
        issues: dict[str, list[str]] = {}
        for name, config in self._modules.items():
            missing = [
                str(p) for p in config.all_paths(root)
                if not p.exists()
            ]
            if missing:
                issues[name] = missing
        return issues

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"ModuleRegistry({len(self._modules)} modules: {self.names()})"

    def summary(self) -> str:
        """Human-readable summary for --list CLI output."""
        lines = [f"{'Module':<20} {'Tags':<30} {'Description'}"]
        lines.append("-" * 72)
        for m in self._modules.values():
            tags = ", ".join(m.tags) if m.tags else "-"
            lines.append(f"{m.name:<20} {tags:<30} {m.description}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere in the framework
# ---------------------------------------------------------------------------

REGISTRY = ModuleRegistry()
