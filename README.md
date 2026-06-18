# Verilog EDA Automation Framework

A professional Python automation framework for VLSI RTL design projects.
Wraps `iverilog` + `vvp` with compile, simulate, parse, report, watch, and Vivado parsing — all from a single CLI command.

---

## Collaborators

| Role | Contributor |
|------|-------------|
| Framework design and implementation | [Sujeet Kona](https://github.com/Sujeet-Kona) |
| RTL project integration and module registry | [Abhi Chandra B](https://github.com/abhichandra586) |

---

## Used In

Part of an 8-repository VLSI portfolio building toward a **16-bit pipelined RISC processor** from scratch.

**VLSI Portfolio:** [github.com/abhichandra586](https://github.com/abhichandra586)

---

## What It Does

```
Your Verilog files
      ↓
automate.py     ← single CLI entry point
      ↓
runner.py       ← compiles with iverilog, simulates with vvp
      ↓
parser.py       ← extracts PASS/FAIL counts from terminal output
      ↓
reporter.py     ← generates HTML dashboard + JSON report
```

---

## Project Structure

```
verilog-eda-automation/
├── automate.py          # CLI entry point
├── modules.py           # Module registry — only file to edit for new RTL
├── parser.py            # SimulationParser — regex to structured data
├── reporter.py          # JsonReporter + HtmlReporter
├── runner.py            # RegressionRunner — iverilog + vvp
├── watcher.py           # VerilogWatcher — watchdog file monitor
├── vivado.py            # VivadoParser — utilization + timing reports
├── requirements.txt     # Python dependencies
└── README.md
```

---

## Prerequisites

```bash
# Verilog simulator
sudo apt install iverilog          # Ubuntu / WSL
brew install icarus-verilog        # macOS

# Python file watcher
pip install watchdog
```

---

## Usage

### Run a single module
```bash
python automate.py --root /path/to/vlsi-repo run --module alu_16bit
```

### Run all registered modules
```bash
python automate.py --root /path/to/vlsi-repo run --all
```

### Run by tag
```bash
python automate.py --root /path/to/vlsi-repo run --tag combinational
```

### Watch mode — auto-reruns on every file save
```bash
python automate.py --root /path/to/vlsi-repo watch
```

### Parse Vivado synthesis reports
```bash
python automate.py vivado \
  --util  reports/utilization.txt \
  --timing reports/timing.txt \
  --clock-period 10.0
```

### List all registered modules
```bash
python automate.py list
```

### Validate all source files exist
```bash
python automate.py --root /path/to/vlsi-repo validate
```

### CI integration — non-zero exit code on failure
```bash
python automate.py --root . run --all
echo $?   # 0 = all pass, 1 = any failure
```

---

## Adding a New Module

Edit `modules.py` only — no framework code changes needed:

```python
"counter_bcd": {
    "src": [
        "src/counter_bcd.v",
    ],
    "tb": "src/tb/counter_bcd_tb.v",
    "description": "BCD counter — wraps at 9",
    "tags": ["sequential", "counter"],
},
```

For modules with dependencies, list source files in strict dependency order:

```python
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
```

---

## Testbench Output Format

The parser expects this summary line from your testbenches:

```verilog
$display("Results: PASS=%0d FAIL=%0d", pass_count, fail_count);
```

Individual failures should use the `FAIL:` prefix:

```verilog
$display("FAIL: test_add expected %h got %h", expected, actual);
```

---

## Reports Generated

| File | Description |
|------|-------------|
| `reports/regression_report.html` | Dark-theme dashboard with expandable logs |
| `reports/regression_results.json` | Structured data for CI/CD pipelines |
| `reports/vivado_summary.json` | LUT / FF / BRAM / DSP / WNS / Fmax metrics |
| `logs/eda_automation.log` | Full timestamped log |

---

## Sample HTML Report

The file `sample_regression_report.html` in this repo shows an example dashboard output. Open it in any browser to preview the report format.

---

## Tools Used

| Tool | Purpose |
|------|---------|
| Python 3.12 | Framework language |
| Icarus Verilog | Verilog compilation and simulation |
| watchdog | File system monitoring for watch mode |
| Vivado | FPGA synthesis report parsing (Repo 5+) |

---

*Built to support an 8-repository VLSI learning roadmap — from AND gate to 16-bit pipelined RISC processor.*
