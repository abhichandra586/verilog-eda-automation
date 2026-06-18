"""
core/reporter.py — JsonReporter + HtmlReporter

Responsibilities:
  JsonReporter:
    - Serialize a list of ParsedResult objects to reports/regression_results.json
    - Include run metadata (timestamp, total duration, summary counts)

  HtmlReporter:
    - Generate reports/regression_report.html with GitHub dark theme
    - Summary dashboard with pass/fail/error counts
    - Per-module cards with timing, expandable raw logs
    - Highlighted FAIL lines in red, WARNING lines in amber
    - Professional CI/CD appearance — self-contained single HTML file

Design decisions:
  - HTML is generated as an f-string template, not via a library like Jinja2,
    to keep zero non-stdlib dependencies
  - All CSS is inlined — the report is portable (email it, open offline)
  - JavaScript is minimal vanilla JS — no frameworks
  - JSON uses indent=2 for human readability in CI diff views
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from parser import ParsedResult

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")


# ---------------------------------------------------------------------------
# JSON Reporter
# ---------------------------------------------------------------------------

class JsonReporter:
    """
    Writes regression_results.json from a list of ParsedResult objects.

    Usage:
        reporter = JsonReporter(output_dir=Path("reports"))
        path = reporter.write(results)
    """

    def __init__(self, output_dir: Path = REPORTS_DIR) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, results: list[ParsedResult]) -> Path:
        """Serialize results to JSON and return the output path."""
        output_path = self.output_dir / "regression_results.json"

        total = len(results)
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        errors = sum(1 for r in results if r.status == "ERROR")

        payload = {
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_modules": total,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "overall_status": "PASS" if failed == 0 and errors == 0 else "FAIL",
            },
            "results": [self._serialize(r) for r in results],
        }

        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("JSON report written → %s", output_path)
        return output_path

    @staticmethod
    def _serialize(r: ParsedResult) -> dict:
        return {
            "module": r.module,
            "status": r.status,
            "passed": r.passed,
            "failed": r.failed,
            "total_tests": r.total_tests,
            "pass_rate": round(r.pass_rate, 2),
            "compile_time_s": round(r.compile_time, 4),
            "sim_time_s": round(r.sim_time, 4),
            "total_time_s": round(r.total_time, 4),
            "fail_lines": r.fail_lines,
            "warnings": r.warnings,
            "error_detail": r.error_detail,
        }


# ---------------------------------------------------------------------------
# HTML Reporter
# ---------------------------------------------------------------------------

class HtmlReporter:
    """
    Generates a self-contained HTML regression report with GitHub dark theme.

    Usage:
        reporter = HtmlReporter(output_dir=Path("reports"))
        path = reporter.write(results)
    """

    def __init__(self, output_dir: Path = REPORTS_DIR) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, results: list[ParsedResult]) -> Path:
        """Generate HTML report and return the output path."""
        output_path = self.output_dir / "regression_report.html"
        html = self._render(results)
        output_path.write_text(html, encoding="utf-8")
        logger.info("HTML report written → %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self, results: list[ParsedResult]) -> str:
        total = len(results)
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        errors = sum(1 for r in results if r.status == "ERROR")
        overall = "PASS" if failed == 0 and errors == 0 else "FAIL"
        overall_color = "#3fb950" if overall == "PASS" else "#f85149"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_time = sum(r.total_time for r in results)

        module_cards = "\n".join(self._render_module_card(r) for r in results)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EDA Regression Report — {timestamp}</title>
<style>
  :root {{
    --bg-primary:   #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary:  #21262d;
    --border:       #30363d;
    --text-primary: #e6edf3;
    --text-muted:   #8b949e;
    --green:        #3fb950;
    --red:          #f85149;
    --amber:        #d29922;
    --blue:         #58a6ff;
    --purple:       #bc8cff;
    --font-mono:    'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    padding: 24px;
  }}
  a {{ color: var(--blue); text-decoration: none; }}
  /* Header */
  .header {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .header h1 {{ font-size: 20px; font-weight: 600; }}
  .header .meta {{ color: var(--text-muted); font-size: 12px; }}
  .badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }}
  .badge-pass {{ background: rgba(63,185,80,0.15); color: var(--green); border: 1px solid rgba(63,185,80,0.4); }}
  .badge-fail {{ background: rgba(248,81,73,0.15); color: var(--red);   border: 1px solid rgba(248,81,73,0.4); }}
  .badge-error {{ background: rgba(210,153,34,0.15); color: var(--amber); border: 1px solid rgba(210,153,34,0.4); }}
  /* Summary dashboard */
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}
  .stat-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}
  .stat-card .value {{
    font-size: 32px;
    font-weight: 700;
    line-height: 1.1;
  }}
  .stat-card .label {{
    color: var(--text-muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-top: 4px;
  }}
  .value-pass  {{ color: var(--green); }}
  .value-fail  {{ color: var(--red); }}
  .value-error {{ color: var(--amber); }}
  .value-total {{ color: var(--blue); }}
  .value-time  {{ color: var(--purple); }}
  /* Overall status banner */
  .overall-banner {{
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 24px;
    font-weight: 600;
    font-size: 15px;
    border: 1px solid;
  }}
  .overall-pass {{
    background: rgba(63,185,80,0.08);
    border-color: rgba(63,185,80,0.3);
    color: var(--green);
  }}
  .overall-fail {{
    background: rgba(248,81,73,0.08);
    border-color: rgba(248,81,73,0.3);
    color: var(--red);
  }}
  /* Section heading */
  .section-title {{
    font-size: 14px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 12px;
  }}
  /* Module cards */
  .module-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 12px;
    overflow: hidden;
  }}
  .module-card.card-fail  {{ border-left: 3px solid var(--red); }}
  .module-card.card-pass  {{ border-left: 3px solid var(--green); }}
  .module-card.card-error {{ border-left: 3px solid var(--amber); }}
  .card-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    cursor: pointer;
    user-select: none;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .card-header:hover {{ background: var(--bg-tertiary); }}
  .card-title {{
    font-weight: 600;
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .card-meta {{
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text-muted);
    font-size: 12px;
    flex-wrap: wrap;
  }}
  .card-meta span {{ white-space: nowrap; }}
  .chevron {{ transition: transform 0.2s; font-size: 10px; color: var(--text-muted); }}
  .card-body {{ display: none; border-top: 1px solid var(--border); }}
  .card-body.open {{ display: block; }}
  /* Timing row */
  .timing-row {{
    display: flex;
    gap: 24px;
    padding: 12px 16px;
    background: var(--bg-tertiary);
    font-size: 12px;
    color: var(--text-muted);
    flex-wrap: wrap;
  }}
  .timing-row strong {{ color: var(--text-primary); }}
  /* Fail lines */
  .fail-section {{
    padding: 12px 16px;
    border-top: 1px solid var(--border);
  }}
  .fail-section h4 {{
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-bottom: 8px;
  }}
  .fail-line {{
    background: rgba(248,81,73,0.08);
    border: 1px solid rgba(248,81,73,0.2);
    border-radius: 4px;
    padding: 4px 10px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--red);
    margin-bottom: 4px;
    word-break: break-all;
  }}
  .warn-line {{
    background: rgba(210,153,34,0.08);
    border: 1px solid rgba(210,153,34,0.2);
    border-radius: 4px;
    padding: 4px 10px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--amber);
    margin-bottom: 4px;
    word-break: break-all;
  }}
  /* Log output */
  .log-section {{
    padding: 12px 16px;
    border-top: 1px solid var(--border);
  }}
  .log-section h4 {{
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .log-toggle {{
    cursor: pointer;
    color: var(--blue);
    font-size: 11px;
    background: none;
    border: none;
    padding: 0;
  }}
  pre.log-output {{
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-muted);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 300px;
    overflow-y: auto;
    display: none;
  }}
  pre.log-output.log-open {{ display: block; }}
  /* Progress bar */
  .progress-bar-wrap {{
    background: var(--bg-tertiary);
    border-radius: 4px;
    height: 6px;
    overflow: hidden;
    margin-top: 2px;
  }}
  .progress-bar-fill {{
    height: 100%;
    border-radius: 4px;
    background: var(--green);
    transition: width 0.4s ease;
  }}
  /* Footer */
  .footer {{
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    color: var(--text-muted);
    font-size: 11px;
    text-align: center;
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>⚡ EDA Regression Report</h1>
    <div class="meta">Generated: {timestamp}</div>
  </div>
  <span class="badge {'badge-pass' if overall == 'PASS' else 'badge-fail'}"
        style="font-size:14px;padding:4px 14px">{overall}</span>
</div>

<div class="overall-banner {'overall-pass' if overall == 'PASS' else 'overall-fail'}">
  {'✓ All modules passed regression.' if overall == 'PASS'
    else f'✗ Regression failed — {failed} module(s) failed, {errors} error(s).'}
</div>

<div class="summary">
  <div class="stat-card">
    <div class="value value-total">{total}</div>
    <div class="label">Modules</div>
  </div>
  <div class="stat-card">
    <div class="value value-pass">{passed}</div>
    <div class="label">Passed</div>
  </div>
  <div class="stat-card">
    <div class="value value-fail">{failed}</div>
    <div class="label">Failed</div>
  </div>
  <div class="stat-card">
    <div class="value value-error">{errors}</div>
    <div class="label">Errors</div>
  </div>
  <div class="stat-card">
    <div class="value value-time">{total_time:.2f}s</div>
    <div class="label">Total Time</div>
  </div>
</div>

<div class="section-title">Module Results</div>

{module_cards}

<div class="footer">
  EDA Automation Framework &nbsp;·&nbsp; {timestamp} &nbsp;·&nbsp;
  {total} modules · {passed} passed · {failed} failed · {errors} errors
</div>

<script>
  function toggleCard(id) {{
    var body = document.getElementById('body-' + id);
    var chev = document.getElementById('chev-' + id);
    body.classList.toggle('open');
    chev.style.transform = body.classList.contains('open') ? 'rotate(90deg)' : '';
  }}
  function toggleLog(id) {{
    var pre = document.getElementById('log-' + id);
    var btn = document.getElementById('logbtn-' + id);
    pre.classList.toggle('log-open');
    btn.textContent = pre.classList.contains('log-open') ? 'Hide' : 'Show';
  }}
</script>
</body>
</html>"""

    def _render_module_card(self, r: ParsedResult) -> str:
        card_class = {"PASS": "card-pass", "FAIL": "card-fail", "ERROR": "card-error"}[r.status]
        badge_class = {"PASS": "badge-pass", "FAIL": "badge-fail", "ERROR": "badge-error"}[r.status]
        mid = r.module  # used as DOM id

        pass_rate_bar = ""
        if r.total_tests > 0:
            pct = r.pass_rate
            color = "#3fb950" if pct == 100 else "#f85149" if pct == 0 else "#d29922"
            pass_rate_bar = f"""
            <div style="margin-top:2px;font-size:11px;color:#8b949e">{r.passed}/{r.total_tests} tests</div>
            <div class="progress-bar-wrap" style="width:100px">
              <div class="progress-bar-fill" style="width:{pct:.0f}%;background:{color}"></div>
            </div>"""

        fail_section = ""
        if r.fail_lines:
            lines_html = "\n".join(
                f'<div class="fail-line">{self._esc(line)}</div>'
                for line in r.fail_lines
            )
            fail_section = f"""
        <div class="fail-section">
          <h4>Failures ({len(r.fail_lines)})</h4>
          {lines_html}
        </div>"""

        warn_section = ""
        if r.warnings:
            lines_html = "\n".join(
                f'<div class="warn-line">{self._esc(line)}</div>'
                for line in r.warnings
            )
            warn_section = f"""
        <div class="fail-section">
          <h4>Warnings ({len(r.warnings)})</h4>
          {lines_html}
        </div>"""

        error_section = ""
        if r.error_detail:
            error_section = f"""
        <div class="fail-section">
          <h4>Error Detail</h4>
          <div class="fail-line">{self._esc(r.error_detail)}</div>
        </div>"""

        raw_log = r.raw_output or r.error_detail or "(no output)"
        log_section = f"""
        <div class="log-section">
          <h4>Raw Output
            <button class="log-toggle" id="logbtn-{mid}" onclick="toggleLog('{mid}')">Show</button>
          </h4>
          <pre class="log-output" id="log-{mid}">{self._esc(raw_log)}</pre>
        </div>"""

        return f"""
<div class="module-card {card_class}">
  <div class="card-header" onclick="toggleCard('{mid}')">
    <div class="card-title">
      <span id="chev-{mid}" class="chevron">▶</span>
      <span>{self._esc(r.module)}</span>
      <span class="badge {badge_class}">{r.status}</span>
    </div>
    <div class="card-meta">
      {pass_rate_bar}
      <span>⏱ {r.total_time:.2f}s</span>
      <span style="color:#8b949e">compile {r.compile_time:.2f}s · sim {r.sim_time:.2f}s</span>
    </div>
  </div>
  <div class="card-body" id="body-{mid}">
    <div class="timing-row">
      <span>Compile: <strong>{r.compile_time:.4f}s</strong></span>
      <span>Simulate: <strong>{r.sim_time:.4f}s</strong></span>
      <span>Total: <strong>{r.total_time:.4f}s</strong></span>
      <span>Tests: <strong>{r.passed} pass / {r.failed} fail</strong></span>
      <span>Pass rate: <strong>{r.pass_rate:.1f}%</strong></span>
    </div>
    {fail_section}
    {warn_section}
    {error_section}
    {log_section}
  </div>
</div>"""

    @staticmethod
    def _esc(text: str) -> str:
        """HTML-escape a string to prevent XSS / broken markup."""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
