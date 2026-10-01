#!/usr/bin/env python3
"""Log-only analysis of readback cadence, the OFF-state load current, and range logging.

Usage: readback_cadence.py <run_dir> [<run_dir> ...]   (a runs root is expanded to */*/scpi.jsonl)

Reads raw/samples.jsonl and scpi.jsonl; touches no instrument; prints deterministic tables.
An identical consecutive response is *consistent with* an un-refreshed readback; it is also
consistent with a genuinely stable measurement. These logs alone cannot separate the two.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

QUANTITIES = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")
MEAS = {("source", ":MEAS:VOLT? CH1"): "Vin_V", ("source", ":MEAS:CURR? CH1"): "Iin_A",
        ("load", ":MEAS:VOLT?"): "Vout_V", ("load", ":MEAS:CURR?"): "Iout_A"}
# Phases whose consecutive same-point samples are treated as a settled window.
SETTLED_PHASES = {"acquiring"}  # the accepted acquisition window; "settling" and "starting" are excluded
OFF_STATE_BAND_A = (0.0105, 0.0115)  # the "about 11 mA" class discussed in the M2 plan


def iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def stats(values: list[float], scale: float = 1.0, unit: str = "") -> str:
    if not values:
        return "n=0"
    v = sorted(x * scale for x in values)
    p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
    return (f"n={len(v)} min={v[0]:.1f} med={statistics.median(v):.1f} p95={p95:.1f} "
            f"max={v[-1]:.1f}{unit}")


def run_dirs(args: list[str]) -> list[Path]:
    out = []
    for arg in args:
        p = Path(arg)
        if (p / "scpi.jsonl").exists():
            out.append(p)
        else:
            out.extend(sorted(q.parent for q in p.glob("*/*/scpi.jsonl")))
    return out


def short(run: Path) -> str:
    return run.name[-6:]


def cadence_from_samples(samples: list[dict], settled_only: bool) -> dict[str, dict]:
    """Consecutive same-quantity polls inside one point and one phase."""
    by_q = defaultdict(list)
    for s in samples:
        if s["quantity"] in QUANTITIES:
            by_q[s["quantity"]].append(s)
    result = {}
    for q, seq in by_q.items():
        pairs = ident = 0
        intervals, changed_intervals, run_lengths, run_durations = [], [], [], []
        run_len, run_start = 1, None
        for prev, cur in zip(seq, seq[1:]):
            same_window = (prev["point_id"] == cur["point_id"] and prev["phase"] == cur["phase"]
                           and (not settled_only or cur["phase"] in SETTLED_PHASES))
            if not same_window:
                if run_len > 1:
                    run_lengths.append(run_len)
                    run_durations.append(prev["query_start_monotonic_s"] - run_start)
                run_len, run_start = 1, None
                continue
            dt = cur["query_start_monotonic_s"] - prev["query_start_monotonic_s"]
            pairs += 1
            intervals.append(dt)
            if cur["raw_response"] == prev["raw_response"]:
                ident += 1
                if run_len == 1:
                    run_start = prev["query_start_monotonic_s"]
                run_len += 1
            else:
                changed_intervals.append(dt)
                if run_len > 1:
                    run_lengths.append(run_len)
                    run_durations.append(prev["query_start_monotonic_s"] - run_start)
                run_len, run_start = 1, None
        if run_len > 1:
            run_lengths.append(run_len)
            run_durations.append(seq[-1]["query_start_monotonic_s"] - run_start)
        result[q] = dict(pairs=pairs, identical=ident, intervals=intervals,
                         changed_intervals=changed_intervals, run_lengths=run_lengths,
                         run_durations=run_durations,
                         round_trips=[s["query_end_monotonic_s"] - s["query_start_monotonic_s"] for s in seq])
    return result


def print_cadence(label: str, cad: dict[str, dict]) -> None:
    print(f"\n{label}")
    print("quantity | pairs | identical | frac | poll interval s (min/med/max) | shortest change interval s"
          " | identical runs: count, longest (polls, s) | run-length histogram")
    for q in QUANTITIES:
        c = cad.get(q)
        if not c or not c["pairs"]:
            print(f"{q} | 0 | - | - | - | - | - | -")
            continue
        iv = sorted(c["intervals"])
        frac = c["identical"] / c["pairs"]
        sci = f"{min(c['changed_intervals']):.3f}" if c["changed_intervals"] else "none"
        if c["run_lengths"]:
            longest = max(range(len(c["run_lengths"])), key=lambda i: c["run_lengths"][i])
            runs = (f"{len(c['run_lengths'])}, {c['run_lengths'][longest]} polls / "
                    f"{c['run_durations'][longest]:.2f} s")
        else:
            runs = "0"
        hist = dict(sorted(Counter(c["run_lengths"]).items()))
        print(f"{q} | {c['pairs']} | {c['identical']} | {frac:.3f} | "
              f"{iv[0]:.3f}/{statistics.median(iv):.3f}/{iv[-1]:.3f} | {sci} | {runs} | {hist}")


def difference_spectrum(samples: list[dict]) -> dict[str, Counter]:
    """|delta| between consecutive settled polls in units of the response's last printed digit.

    A spike at exactly 0 far above the 1-2 digit bins is *consistent with* a held (un-refreshed)
    value; a smooth fall-off is consistent with ordinary noise around a stable measurement.
    """
    bins = (("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3-10", 3, 10), ("11-100", 11, 100),
            ("101-1000", 101, 1000), (">1000", 1001, float("inf")))
    by_q = defaultdict(list)
    for s in samples:
        if s["quantity"] in QUANTITIES and s["phase"] in SETTLED_PHASES and s["raw_response"]:
            by_q[s["quantity"]].append(s)
    out = {}
    for q, seq in by_q.items():
        hist = Counter()
        for prev, cur in zip(seq, seq[1:]):
            if prev["point_id"] != cur["point_id"] or prev["phase"] != cur["phase"]:
                continue
            decimals = len(cur["raw_response"].split(".")[1]) if "." in cur["raw_response"] else 0
            lsb = round(abs(cur["value"] - prev["value"]) * 10 ** decimals)
            for name, lo, hi in bins:
                if lo <= lsb <= hi:
                    hist[name] += 1
                    break
        hist["_lsb"] = decimals if seq else None
        out[q] = hist
    return out


def cooccurrence(samples: list[dict]) -> list[str]:
    """Do identical-to-previous readings on an instrument's two channels fall in the same cycle pair?

    Under independence the expected joint count is n * p(V) * p(I); a much larger observed count is
    *consistent with* both channels being served from one held conversion.
    """
    cycles, order = defaultdict(dict), []
    for s in samples:
        if s["phase"] in SETTLED_PHASES:
            if s["acquisition_cycle_id"] not in cycles:
                order.append(s["acquisition_cycle_id"])
            cycles[s["acquisition_cycle_id"]][s["quantity"]] = s
    lines = []
    for label, qv, qi in (("source Vin_V/Iin_A", "Vin_V", "Iin_A"), ("load Vout_V/Iout_A", "Vout_V", "Iout_A")):
        n = both = only_v = only_i = 0
        for a, b in zip(order, order[1:]):
            ca, cb = cycles[a], cycles[b]
            if not all(q in ca and q in cb for q in (qv, qi)):
                continue
            if ca[qv]["point_id"] != cb[qv]["point_id"]:
                continue
            n += 1
            sv = ca[qv]["raw_response"] == cb[qv]["raw_response"]
            si = ca[qi]["raw_response"] == cb[qi]["raw_response"]
            both += sv and si
            only_v += sv and not si
            only_i += si and not sv
        if n:
            pv, pi = (both + only_v) / n, (both + only_i) / n
            lines.append(f"  {label}: pairs={n} V-identical={both+only_v} I-identical={both+only_i} "
                         f"both={both} (independence expects {n*pv*pi:.1f})")
    return lines


def quantum(samples: list[dict]) -> list[str]:
    """Smallest and most common nonzero |delta| per quantity, to expose the effective readback step."""
    by_q = defaultdict(list)
    for s in samples:
        if s["quantity"] in QUANTITIES and s["phase"] in SETTLED_PHASES and s["value"] is not None:
            by_q[s["quantity"]].append(s)
    lines = []
    for q in QUANTITIES:
        deltas = Counter()
        for a, b in zip(by_q[q], by_q[q][1:]):
            if a["point_id"] == b["point_id"]:
                d = round(abs(b["value"] - a["value"]), 7)
                if d:
                    deltas[d] += 1
        if deltas:
            common = ", ".join(f"{d:g}x{n}" for d, n in sorted(deltas.items(), key=lambda kv: (-kv[1], kv[0]))[:5])
            lines.append(f"  {q}: smallest nonzero |delta|={min(deltas):g}; most common: {common}")
    return lines


def transcript_states(scpi: list[dict]):
    """Yield (record, load_input_on, source_output_on) with state tracked from writes and queries."""
    load_on = source_on = None
    for r in scpi:
        cmd, dev, resp = r["command"], r["device"], r.get("response")
        if dev == "load":
            if cmd.startswith(":SOUR:INP:STAT ") or cmd.startswith(":INP "):
                load_on = cmd.split()[-1].upper() in ("ON", "1")
            elif cmd in (":SOUR:INP:STAT?", ":INP?") and resp is not None:
                load_on = resp.strip() in ("1", "ON")
        if dev == "source":
            if cmd.startswith(":OUTP CH1,"):
                source_on = cmd.split(",")[-1].upper() in ("ON", "1")
            elif cmd == ":OUTP? CH1" and resp is not None:
                source_on = resp.strip() in ("1", "ON")
        yield r, load_on, source_on


POOL = {"round_trips": defaultdict(list), "pairs": Counter(), "identical": Counter(),
        "off_values": defaultdict(list), "frac": defaultdict(list)}


def analyse_run(run: Path) -> None:
    samples = rows(run / "raw" / "samples.jsonl") if (run / "raw" / "samples.jsonl").exists() else []
    scpi = rows(run / "scpi.jsonl")
    if samples:
        for q, c in cadence_from_samples(samples, settled_only=False).items():
            POOL["round_trips"][q].extend(c["round_trips"])
        for q, c in cadence_from_samples(samples, settled_only=True).items():
            POOL["pairs"][q] += c["pairs"]
            POOL["identical"][q] += c["identical"]
            if c["pairs"] >= 40:
                POOL["frac"][q].append(c["identical"] / c["pairs"])
    for r, load_on, source_on in transcript_states(scpi):
        if (r["device"], r["command"]) == ("load", ":MEAS:CURR?") and load_on is False and r.get("response"):
            POOL["off_values"][source_on].append(float(r["response"]))
    print("\n" + "=" * 100)
    print(f"RUN {short(run)}  {run}")
    print(f"samples={len(samples)} scpi_records={len(scpi)}")
    phases = Counter((s["phase"], s["acquisition_settings"].get("load_enabled")) for s in samples
                     if s["quantity"] == "Iout_A")
    print("cycles by (phase, load_enabled):", dict(sorted(phases.items(), key=str)))

    # ---- A: cadence and round trips ------------------------------------------------------------
    if samples:
        print_cadence("A1 samples, settled windows (same point and phase, phase in SETTLED_PHASES):",
                      cadence_from_samples(samples, settled_only=True))
        print_cadence("A1b samples, all phases (same point and phase):",
                      cadence_from_samples(samples, settled_only=False))
        print("\nA2 round trip query_end - query_start (ms), all samples:")
        allc = cadence_from_samples(samples, settled_only=False)
        for q in QUANTITIES:
            if q in allc:
                print(f"  {q}: {stats(allc[q]['round_trips'], 1000.0, ' ms')}")
        print("\nA4 |delta| between consecutive settled polls, in units of the last printed digit:")
        spec = difference_spectrum(samples)
        for q in QUANTITIES:
            if q in spec:
                h = spec[q]
                print(f"  {q} (digit=1e-{h['_lsb']}): " + " ".join(
                    f"{b}:{h.get(b, 0)}" for b in ("0", "1", "2", "3-10", "11-100", "101-1000", ">1000")))
        print("\nA5 effective readback step (settled windows):")
        for line in quantum(samples):
            print(line)
        print("\nA6 co-occurrence of identical readings across an instrument's two channels (settled windows):")
        for line in cooccurrence(samples):
            print(line)
    # Transcript view: every measurement query regardless of phase, plus duration_s.
    print("\nA3 transcript, consecutive same-command polls (all phases) and duration_s (ms):")
    by_cmd = defaultdict(list)
    for r in scpi:
        key = (r["device"], r["command"])
        if key in MEAS:
            by_cmd[key].append(r)
    for key, q in MEAS.items():
        seq = by_cmd.get(key, [])
        if len(seq) < 2:
            print(f"  {key[0]} {key[1]} ({q}): n={len(seq)}")
            continue
        ident = sum(1 for a, b in zip(seq, seq[1:]) if a.get("response") == b.get("response"))
        gaps = [(iso(b["timestamp"]) - iso(a["timestamp"])).total_seconds() for a, b in zip(seq, seq[1:])]
        print(f"  {key[0]} {key[1]:<16} ({q}): n={len(seq)} identical={ident}/{len(seq)-1}"
              f" ({ident/(len(seq)-1):.3f}); gap {stats(gaps, 1.0, ' s')}; duration {stats([r['duration_s'] for r in seq], 1000.0, ' ms')}")
    if samples:
        # Which instant does the transcript timestamp represent? Compare with the sample bounds.
        offs = []
        for s in samples[:40]:
            key = {"Vin_V": ("source", ":MEAS:VOLT? CH1"), "Iin_A": ("source", ":MEAS:CURR? CH1"),
                   "Vout_V": ("load", ":MEAS:VOLT?"), "Iout_A": ("load", ":MEAS:CURR?")}[s["quantity"]]
            st, en = iso(s["query_start_utc"]), iso(s["query_end_utc"])
            cands = [r for r in by_cmd[key] if r.get("response") == s["raw_response"]
                     and abs((iso(r["timestamp"]) - st).total_seconds()) < 0.5]
            if cands:
                t = iso(cands[0]["timestamp"])
                offs.append(((t - st).total_seconds() * 1000, (en - t).total_seconds() * 1000))
        if offs:
            print(f"  transcript timestamp minus sample query_start: {stats([o[0] for o in offs], 1.0, ' ms')};"
                  f" sample query_end minus transcript timestamp: {stats([o[1] for o in offs], 1.0, ' ms')}")

    # ---- B: OFF-state load current ---------------------------------------------------------------
    print("\nB1 transcript: load :MEAS:CURR? while load input state is OFF, by source output state:")
    tab = Counter()
    values = defaultdict(list)
    t0 = iso(scpi[0]["timestamp"]) if scpi else None
    last_state_write = last_vout = None
    listing = []
    for r, load_on, source_on in transcript_states(scpi):
        if r["device"] == "load" and r["command"].startswith(":SOUR:INP:STAT ") and "?" not in r["command"]:
            last_state_write = iso(r["timestamp"])
        if (r["device"], r["command"]) == ("load", ":MEAS:VOLT?") and r.get("response"):
            last_vout = r["response"]
        if (r["device"], r["command"]) == ("load", ":MEAS:CURR?") and load_on is False and r.get("response"):
            v = float(r["response"])
            cls = "zero" if v == 0.0 else ("~11 mA" if OFF_STATE_BAND_A[0] <= v <= OFF_STATE_BAND_A[1] else "other")
            tab[(source_on, cls)] += 1
            values[(source_on, cls)].append(v)
            t = iso(r["timestamp"])
            since = "n/a" if last_state_write is None else f"{(t - last_state_write).total_seconds():7.2f}"
            listing.append(f"    t+{(t - t0).total_seconds():7.2f}s  since_INP_write={since}s  source_on={source_on!s:<5}"
                           f" Vout={last_vout:<10} Iout={r['response']}")
    for line in listing:
        print(line)
    for key in sorted(tab, key=str):
        vs = sorted(values[key])
        print(f"  source_on={key[0]!s:<5} {key[1]:<7} n={tab[key]:<3} "
              f"min={vs[0]*1000:.3f} med={statistics.median(vs)*1000:.3f} max={vs[-1]*1000:.3f} mA")
    if not tab:
        print("  none")

    if samples:
        print("\nB2 samples: cycles with load_enabled=false, Iout_A vs same-cycle Vin/Vout (nonzero Iout listed):")
        cycles = defaultdict(dict)
        order = []
        for s in samples:
            if s["acquisition_cycle_id"] not in cycles:
                order.append(s["acquisition_cycle_id"])
            cycles[s["acquisition_cycle_id"]][s["quantity"]] = s
        prev_vout = None
        n_off = n_nonzero = 0
        for cid in order:
            c = cycles[cid]
            io = c.get("Iout_A")
            if io is None:
                continue
            vout = c.get("Vout_V", {}).get("value")
            if io["acquisition_settings"].get("load_enabled") is False:
                n_off += 1
                if io["value"] not in (0.0, None):
                    n_nonzero += 1
                    vin = c.get("Vin_V", {}).get("value")
                    dv = None if prev_vout is None or vout is None else vout - prev_vout
                    print(f"  {cid} {io['phase']:<10} Iout={io['raw_response']:<9} Vin={vin} Vout={vout}"
                          f" dVout_prev_cycle={'n/a' if dv is None else f'{dv:+.4f}'} src_mode={io['acquisition_settings'].get('source_mode')}")
            prev_vout = vout
        print(f"  OFF cycles={n_off} nonzero Iout={n_nonzero}")

        print("\nB3 samples: loaded settled windows, measured - requested Iout by requested level (mA):")
        setp = []
        for r in scpi:
            if r["device"] == "load" and r["command"].startswith(":SOUR:CURR:LEV:IMM ") and "?" not in r["command"]:
                setp.append((iso(r["timestamp"]), float(r["command"].split()[-1])))
        by_level = defaultdict(list)
        for s in samples:
            if s["quantity"] != "Iout_A" or s["value"] is None or s["phase"] not in SETTLED_PHASES:
                continue
            if s["acquisition_settings"].get("load_enabled") is not True:
                continue
            req = s["acquisition_settings"].get("requested_load_A")
            if req is None:
                t = iso(s["query_start_utc"])
                earlier = [lv for ts, lv in setp if ts <= t]
                req = earlier[-1] if earlier else None
            if req is not None:
                by_level[req].append(s["value"] - req)
        for lvl in sorted(by_level):
            print(f"  requested {lvl:.3f} A: {stats(by_level[lvl], 1000.0, ' mA')} (mean {statistics.mean(by_level[lvl])*1000:+.2f})")
        if not by_level:
            print("  none")

    # ---- C: range logging -------------------------------------------------------------------------
    print("\nC range logging:")
    if samples:
        print("  samples measurement_range/resolution values:",
              dict(Counter((s["measurement_range"], s["resolution"]) for s in samples)))
    rng = Counter((r["device"], r["command"], r.get("response")) for r in scpi
                  if any(k in r["command"].upper() for k in ("RANG", "SENS", "NPLC", "APER", "AVER")))
    for k in sorted(rng, key=str):
        print(f"  {rng[k]}x {k}")
    if not rng:
        print("  no range/sense/aperture traffic")


def main(argv: list[str]) -> int:
    runs = run_dirs(argv[1:])
    if not runs:
        print(__doc__)
        return 2
    for run in runs:
        analyse_run(run)
    print("\n" + "=" * 100)
    print(f"POOLED over {len(runs)} run directories")
    print("round trip query_end - query_start (ms), all samples:")
    for q in QUANTITIES:
        print(f"  {q}: {stats(POOL['round_trips'][q], 1000.0, ' ms')}")
    print("identical consecutive polls in settled windows (runs with >= 40 pairs give the per-run range):")
    for q in QUANTITIES:
        p, i = POOL["pairs"][q], POOL["identical"][q]
        fr = POOL["frac"][q]
        rng = f"{min(fr):.3f}-{max(fr):.3f}" if fr else "n/a"
        print(f"  {q}: {i}/{p} = {i/p if p else 0:.3f}; per-run range {rng}")
    print("load :MEAS:CURR? with input OFF, by source output state:")
    for state, vals in sorted(POOL["off_values"].items(), key=str):
        nz = sorted(v for v in vals if v)
        print(f"  source_on={state}: reads={len(vals)} zero={len(vals)-len(nz)} nonzero={len(nz)}"
              + (f" nonzero min/med/max = {nz[0]*1000:.3f}/{statistics.median(nz)*1000:.3f}/{nz[-1]*1000:.3f} mA"
                 if nz else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
