#!/usr/bin/env python3
"""
checkPID - open-loop check of tcontrol()'s behaviour (see specs/checkPID.md).

Feeds the real `tcontrol` strategy (tcontrol.py, unmodified) a prescribed
temperature signal and records what it does with it. The temperature starts
at the initial value and is then changed on fixed time steps, each change
applied to the value at that moment and held:

    5th step:  +5%
    10th step: -2.5%
    15th step: -2.5%
    20th step: -5%
    25th step: +2.5%
    30th step: +2.5%
    35th step: -1.6%
    40th step: +1.6%

Step n happens at t = (n - 1) * Dt, so Tmax must be at least 39 * Dt for
every change to take place; the script says so when a run is too short.

The loop is open: the temperature does NOT react to the voltage tcontrol()
returns. The voltage it returns is fed back in as `current_voltage` on the
next step, exactly as TuningManager does.

Usage (run from the folder that holds tcontrol.py):
    python checkPID.py --dt 5 --kp 0.15 --ki 0.001 --kd 0.02 --temp 60 --tmax 300

Inputs (specs/checkPID.md), all read from the command line and printed at
start-up:
    --dt      time step, in seconds (also tcontrol's sample_interval)
    --kp --ki --kd   PID gains
    --temp    initial temperature, deg C
    --tmax    max simulation time, seconds
    --deadband       deadband on deltaT/target_temp (default 0.05)
    --max-voltage --min-voltage   voltage limits, mV (default 1250 / 1000)

The first six are required; the rest default to the values above. Run with
--help for the remaining options (setpoint, initial voltage, run name).

Outputs, all written to a folder called `checkPID` next to this script:
    <name>.csv    every step's inputs and outputs
    <name>.png    input temperature, output voltage, PID output and the ratio
                  PID output / target temperature, each against time
    <name>.json   the run's inputs and a short summary
    index.html    a page showing every run in the folder; it is rewritten on
                  every run and reloads itself, so it can stay open in a
                  browser while runs are repeated
<name> is `checkPID` unless --output says otherwise, so repeating a run
replaces its files and a different --output keeps both side by side.

Dependencies: tcontrol.py's own (control, numpy) plus matplotlib.
"""

import argparse
import csv
import html
import json
import logging
import re
import sys
import time as time_module
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed; the plot is only saved to a file
import matplotlib.pyplot as plt  # noqa: E402

from tcontrol import tcontrol  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "checkPID"

# Temperature changes: {time step (counting from 1): factor applied to the
# temperature at that moment}. Step n happens at t = (n - 1) * dt.
TEMP_CHANGES = {
    5: 1.05,
    10: 0.975,
    15: 0.975,
    20: 0.95,
    25: 1.025,
    30: 1.025,
    35: 0.984,
    40: 1.016,
}
FREQUENCY = 550.0  # MHz; tcontrol passes it through unchanged

# tcontrol() only returns the new voltage; its PID output (deltaT), the ratio
# deltaT/target_temp and the deadband decision are reported through its INFO
# log line. They are read back from there so they are exactly what tcontrol
# computed, rather than being re-derived here.
_LOG_FIELDS = re.compile(
    r"PID_output\(deltaT\)=(?P<delta_t>-?[\d.]+(?:e-?\d+)?) "
    r"ratio\(r=deltaT/target_temp\)=(?P<ratio>-?[\d.]+(?:e-?\d+)?) "
    r"in_deadband=(?P<in_deadband>True|False)"
)


class _TcontrolLogCapture(logging.Handler):
    """Keeps the fields of the most recent tcontrol INFO line."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.last = None

    def emit(self, record: logging.LogRecord) -> None:
        match = _LOG_FIELDS.search(record.getMessage())
        if match:
            self.last = {
                "delta_t": float(match["delta_t"]),
                "ratio": float(match["ratio"]),
                "in_deadband": match["in_deadband"] == "True",
            }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open-loop check of tcontrol(): change the input temperature "
        "on fixed time steps and record/plot the response."
    )
    required = parser.add_argument_group("required inputs")
    required.add_argument("--dt", type=float, required=True, help="Time step, in seconds")
    required.add_argument("--kp", type=float, required=True, help="Proportional gain")
    required.add_argument("--ki", type=float, required=True, help="Integral gain")
    required.add_argument("--kd", type=float, required=True, help="Derivative gain")
    required.add_argument(
        "--temp", type=float, required=True, help="Initial temperature, deg C"
    )
    required.add_argument(
        "--tmax", type=float, required=True, help="Max simulation time, seconds"
    )

    optional = parser.add_argument_group("other tcontrol() inputs")
    optional.add_argument(
        "--target-temp",
        type=float,
        default=None,
        help="Temperature setpoint, deg C (default: same as --temp, so the "
        "error is zero until the first temperature change)",
    )
    optional.add_argument(
        "--deadband",
        "--max-delta-v",
        dest="deadband",
        type=float,
        default=0.05,
        help="Deadband on deltaT/target_temp, unitless fraction "
        "(tcontrol's max_delta_v; default: 0.05)",
    )
    optional.add_argument(
        "--voltage", type=float, default=1150.0, help="Initial voltage, mV (default: 1150)"
    )
    optional.add_argument(
        "--min-voltage", type=float, default=1000.0, help="Minimum voltage, mV (default: 1000)"
    )
    optional.add_argument(
        "--max-voltage", type=float, default=1250.0, help="Maximum voltage, mV (default: 1250)"
    )
    optional.add_argument(
        "--output",
        default="checkPID",
        help="Run name: files are written as <name>.csv/.png/.json inside the "
        "checkPID folder (default: checkPID)",
    )
    optional.add_argument(
        "--outdir",
        type=Path,
        default=OUTPUT_DIR,
        help="Folder for all output files (default: a folder called checkPID "
        "next to this script)",
    )
    args = parser.parse_args()
    if args.dt <= 0:
        parser.error("--dt must be greater than zero")
    if args.tmax < 0:
        parser.error("--tmax must not be negative")
    if args.deadband < 0:
        parser.error("--deadband must not be negative")
    if args.min_voltage > args.max_voltage:
        parser.error("--min-voltage must not be greater than --max-voltage")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.output) or args.output == "index":
        parser.error(
            "--output is a run name, not a path: use letters, digits, '.', '_' "
            "or '-' only (and not 'index', which is the web page)"
        )
    if args.target_temp is None:
        args.target_temp = args.temp
    if args.target_temp == 0:
        parser.error("the temperature setpoint must not be zero (tcontrol divides by it)")
    return args


def input_table(args: argparse.Namespace) -> list:
    """(label, value) for every input, in the order they are reported."""
    return [
        ("Time step, Dt", f"{args.dt:g} s"),
        ("kp", f"{args.kp:g}"),
        ("ki", f"{args.ki:g}"),
        ("kd", f"{args.kd:g}"),
        ("Initial temperature, T", f"{args.temp:g} C"),
        ("Max simulation time, Tmax", f"{args.tmax:g} s"),
        ("Deadband", f"{args.deadband:g}"),
        ("Max voltage", f"{args.max_voltage:g} mV"),
        ("Min voltage", f"{args.min_voltage:g} mV"),
        ("Temperature setpoint", f"{args.target_temp:g} C"),
        ("Initial voltage", f"{args.voltage:g} mV"),
        ("Run name", args.output),
    ]


def print_inputs(args: argparse.Namespace) -> None:
    print("Input variables:")
    for name, value in input_table(args):
        print(f"  {name:<26} {value}")
    print()


def simulate(args: argparse.Namespace) -> list:
    capture = _TcontrolLogCapture()
    root = logging.getLogger()
    root.addHandler(capture)
    root.setLevel(logging.INFO)

    controller = tcontrol(
        kp=args.kp,
        ki=args.ki,
        kd=args.kd,
        sample_interval=args.dt,
        target_temp=args.target_temp,
        max_delta_v=args.deadband,
        min_voltage=args.min_voltage,
        max_voltage=args.max_voltage,
    )

    # Steps at t = 0, dt, 2*dt, ... up to and including tmax. The small
    # tolerance keeps a tmax that is an exact multiple of dt from being lost
    # to floating-point rounding.
    n_steps = int(args.tmax / args.dt + 1e-9) + 1

    rows = []
    voltage = args.voltage
    temp = args.temp
    for step in range(1, n_steps + 1):
        if step in TEMP_CHANGES:
            temp = temp * TEMP_CHANGES[step]
        capture.last = None
        voltage_in = voltage
        voltage, _ = controller.apply_strategy(
            current_voltage=voltage_in,
            current_frequency=FREQUENCY,
            temp=temp,
            hashrate=0.0,
            power=0.0,
        )
        seen = capture.last or {}
        rows.append(
            {
                "step": step,
                "time_s": (step - 1) * args.dt,
                "temp_in_C": temp,
                "target_temp_C": args.target_temp,
                "voltage_in_mV": voltage_in,
                "voltage_out_mV": voltage,
                "pid_output_deltaT": seen.get("delta_t", ""),
                "ratio_deltaT_over_target": seen.get("ratio", ""),
                "in_deadband": seen.get("in_deadband", ""),
            }
        )

    root.removeHandler(capture)
    return rows


def describe_changes() -> str:
    parts = []
    for step, factor in sorted(TEMP_CHANGES.items()):
        parts.append(f"{(factor - 1) * 100:+g}% at step {step}")
    return ", ".join(parts)


def describe_changes_short() -> str:
    """Same list, compact enough for one line of the plot."""
    return ", ".join(
        f"{step}: {(factor - 1) * 100:+g}%" for step, factor in sorted(TEMP_CHANGES.items())
    )


def write_csv(rows: list, path: Path) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_plot(rows: list, args: argparse.Namespace, path: Path) -> None:
    surface, ink, muted, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    blue, orange, aqua, violet = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"

    time = [row["time_s"] for row in rows]
    temps = [row["temp_in_C"] for row in rows]
    volts = [row["voltage_out_mV"] for row in rows]
    # "" means tcontrol's log line could not be read for that step.
    pid = [
        row["pid_output_deltaT"] if row["pid_output_deltaT"] != "" else float("nan")
        for row in rows
    ]
    ratio = [
        row["ratio_deltaT_over_target"]
        if row["ratio_deltaT_over_target"] != ""
        else float("nan")
        for row in rows
    ]

    # Four measures on different scales (input deg C, mV, PID deltaT and the
    # unitless ratio): four panels sharing the time axis, rather than one
    # panel with several y-scales.
    fig, (ax_temp, ax_volt, ax_pid, ax_ratio) = plt.subplots(
        4, 1, sharex=True, figsize=(9, 11.5), facecolor=surface
    )
    fig.suptitle(
        "tcontrol() response to input temperature changes",
        x=0.08, y=0.985, ha="left", fontsize=13, color=ink,
    )
    fig.text(
        0.08, 0.942, f"Temperature changes by step: {describe_changes_short()}",
        fontsize=9, color=muted,
    )
    fig.text(
        0.08, 0.957,
        f"kp={args.kp}  ki={args.ki}  kd={args.kd}  dt={args.dt}s  "
        f"setpoint={args.target_temp:g}C  deadband=+-{args.deadband:g}  "
        f"voltage {args.min_voltage:g}-{args.max_voltage:g} mV",
        fontsize=9, color=muted,
    )

    ax_temp.axhline(args.target_temp, color=muted, linewidth=1, linestyle=(0, (4, 3)))
    ax_temp.step(time, temps, where="post", color=blue, linewidth=2)
    ax_temp.set_ylabel("Input temperature (deg C)", color=muted)
    ax_temp.annotate(
        "setpoint", xy=(time[0], args.target_temp), xytext=(0, 5),
        textcoords="offset points", ha="left", fontsize=8, color=muted,
    )

    ax_volt.step(time, volts, where="post", color=orange, linewidth=2)
    ax_volt.set_ylabel("Output voltage (mV)", color=muted)
    ax_volt.ticklabel_format(useOffset=False, style="plain", axis="y")

    ax_pid.axhline(0, color=muted, linewidth=1, linestyle=(0, (4, 3)))
    ax_pid.step(time, pid, where="post", color=aqua, linewidth=2)
    ax_pid.set_ylabel("PID output, deltaT (deg C)", color=muted)

    # The deadband is defined on this ratio: while it stays inside the shaded
    # band (+-deadband), tcontrol() leaves the voltage unchanged.
    if args.deadband > 0:
        ax_ratio.axhspan(
            -args.deadband, args.deadband, color=grid, alpha=0.6, linewidth=0
        )
        ax_ratio.annotate(
            "deadband: voltage unchanged inside", xy=(time[0], args.deadband),
            xytext=(0, 4), textcoords="offset points", ha="left",
            fontsize=8, color=muted,
        )
    ax_ratio.axhline(0, color=muted, linewidth=1, linestyle=(0, (4, 3)))
    ax_ratio.step(time, ratio, where="post", color=violet, linewidth=2)
    ax_ratio.set_ylabel("PID output / target temp", color=muted)
    ax_ratio.set_xlabel("Time (s)", color=muted)

    for ax in (ax_temp, ax_volt, ax_pid, ax_ratio):
        ax.set_facecolor(surface)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=muted, labelsize=9, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(grid)
        ax.margins(x=0.01, y=0.15)

    fig.subplots_adjust(left=0.11, right=0.97, top=0.925, bottom=0.055, hspace=0.12)
    fig.savefig(path, dpi=150, facecolor=surface)
    plt.close(fig)


def write_run_info(rows: list, args: argparse.Namespace, summary: list, path: Path) -> None:
    info = {
        "checkPID_run": args.output,
        "finished": time_module.strftime("%Y-%m-%d %H:%M:%S"),
        "inputs": [[label, value] for label, value in input_table(args)],
        "temperature_changes": describe_changes(),
        "summary": summary,
        "files": {"csv": f"{args.output}.csv", "plot": f"{args.output}.png"},
    }
    path.write_text(json.dumps(info, indent=2) + "\n")


_PAGE_STYLE = """
:root { --surface:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --muted:#52514e;
        --line:#e4e3df; --link:#1c5cab; }
@media (prefers-color-scheme: dark) {
  :root { --surface:#1a1a19; --card:#232322; --ink:#ffffff; --muted:#c3c2b7;
          --line:#383835; --link:#86b6ef; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 48px; background:var(--surface); color:var(--ink);
       font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:980px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:17px; margin:0; }
p.note, .when { color:var(--muted); font-size:13px; margin:0; }
section { background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:16px; margin-top:20px; }
header.run { display:flex; flex-wrap:wrap; gap:4px 16px; align-items:baseline;
             justify-content:space-between; }
dl { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr));
     gap:8px 16px; margin:14px 0; }
dl div { border-top:1px solid var(--line); padding-top:6px; }
dt { color:var(--muted); font-size:12px; }
dd { margin:0; font-variant-numeric:tabular-nums; }
ul.summary { margin:0 0 12px; padding-left:18px; color:var(--muted); font-size:14px; }
img { display:block; width:100%; height:auto; border:1px solid var(--line);
      border-radius:6px; }
.files { margin:12px 0 0; font-size:14px; }
a { color:var(--link); }
details { margin-top:12px; }
summary { cursor:pointer; color:var(--muted); font-size:14px; }
.scroll { overflow:auto; max-height:340px; margin-top:8px; border:1px solid var(--line);
          border-radius:6px; }
table { border-collapse:collapse; font-size:12px; font-variant-numeric:tabular-nums;
        white-space:nowrap; }
th, td { padding:3px 10px; text-align:right; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; position:sticky; top:0; background:var(--card); }
"""


def _run_section(info: dict, folder: Path) -> str:
    esc = html.escape
    name = info["checkPID_run"]
    csv_name, png_name = info["files"]["csv"], info["files"]["plot"]
    png_path, csv_path = folder / png_name, folder / csv_name

    inputs = "".join(
        f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>"
        for label, value in info.get("inputs", [])
    )
    summary = "".join(f"<li>{esc(line)}</li>" for line in info.get("summary", []))

    # The version query changes whenever the plot is rewritten, so a reload
    # never shows a cached copy of the previous run's image.
    version = int(png_path.stat().st_mtime) if png_path.exists() else 0
    plot = (
        f'<img src="{esc(png_name)}?v={version}" '
        f'alt="Input temperature, output voltage, PID output and PID output / target '
        f'temperature over time for run {esc(name)}">'
        if png_path.exists()
        else '<p class="note">Plot file is missing.</p>'
    )

    table = ""
    if csv_path.exists():
        with open(csv_path, newline="") as handle:
            data = list(csv.reader(handle))
        if data:
            head = "".join(f"<th>{esc(cell)}</th>" for cell in data[0])
            body = "".join(
                "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
                for row in data[1:]
            )
            table = (
                f"<details open><summary>Data file {esc(csv_name)} ({len(data) - 1} steps)</summary>"
                f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div></details>"
            )

    return (
        f'<section><header class="run"><h2>{esc(name)}</h2>'
        f'<span class="when">run finished {esc(info.get("finished", "?"))}</span></header>'
        f"<dl>{inputs}</dl><ul class=\"summary\">{summary}</ul>{plot}"
        f'<p class="files">Files: <a href="{esc(csv_name)}">{esc(csv_name)}</a> · '
        f'<a href="{esc(png_name)}">{esc(png_name)}</a> · '
        f'<a href="{esc(name)}.json">{esc(name)}.json</a></p>{table}</section>'
    )


def write_page(folder: Path) -> Path:
    """Rewrite index.html so it shows every run found in the folder."""
    runs = []
    for path in folder.glob("*.json"):
        try:
            info = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(info, dict) and "checkPID_run" in info and "files" in info:
            runs.append((path.stat().st_mtime, info))
    runs.sort(key=lambda item: item[0], reverse=True)  # newest first

    sections = "".join(_run_section(info, folder) for _, info in runs)
    page = (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        # Reloads itself, so a tab left open picks up the next run's files.
        '<meta http-equiv="refresh" content="5">'
        f"<title>checkPID runs</title><style>{_PAGE_STYLE}</style></head><body><main>"
        "<h1>checkPID runs</h1>"
        f'<p class="note">{len(runs)} run(s) in this folder, newest first. '
        f"Page written {html.escape(time_module.strftime('%Y-%m-%d %H:%M:%S'))}; "
        "it is rewritten by every checkPID.py run and reloads itself every 5 seconds.</p>"
        f"{sections}</main></body></html>\n"
    )
    index = folder / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


def main() -> int:
    args = parse_arguments()
    print_inputs(args)
    rows = simulate(args)

    moved = [row for row in rows if row["voltage_out_mV"] != row["voltage_in_mV"]]
    summary = [
        f"{len(rows)} steps simulated (t = 0 .. {rows[-1]['time_s']:g} s, dt = {args.dt:g} s)",
        f"Temperature: {args.temp:g} C at the start, {rows[-1]['temp_in_C']:g} C at the end "
        f"({describe_changes()})",
        f"Voltage: {args.voltage:g} mV -> {rows[-1]['voltage_out_mV']:.2f} mV "
        f"({len(moved)} of {len(rows)} steps changed it)",
    ]
    missed = [step for step in sorted(TEMP_CHANGES) if step > len(rows)]
    if missed:
        summary.append(
            f"Run too short for the temperature change(s) at step "
            f"{', '.join(str(step) for step in missed)}: only {len(rows)} steps ran. "
            f"Use --tmax {(max(TEMP_CHANGES) - 1) * args.dt:g} or more to include them all."
        )

    folder = args.outdir
    folder.mkdir(parents=True, exist_ok=True)
    write_csv(rows, folder / f"{args.output}.csv")
    write_plot(rows, args, folder / f"{args.output}.png")
    write_run_info(rows, args, summary, folder / f"{args.output}.json")
    index = write_page(folder)

    for line in summary:
        print(line)
    print(f"Wrote {args.output}.csv, {args.output}.png and {args.output}.json to {folder}")
    print(f"Web page: {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
