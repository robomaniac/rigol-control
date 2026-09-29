"""Local UI facade and detached job owner. No UI request controls instruments.

Profiles and previews are data; all hardware ownership lives in a fresh worker
process. Saving a profile invalidates earlier previews. Reports are a separate
process after acquisition has finalized and every output is verified OFF.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

from filelock import FileLock

from .domain import DutProfile, BenchProfile, TestRecipe, Plan
from .planning import build_plan, _hash_payload, verify_plan_hash
from .resources import MemoryGate, children_peak_rss_mib, session_survivors, terminate_group, try_log_event
from .storage import atomic_json, verify_integrity

MODELS = {"dut": DutProfile, "bench": BenchProfile, "recipe": TestRecipe}
IDENTIFIERS = {"dut": "profile_id", "bench": "bench_id", "recipe": "recipe_id"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
ACTIVE = {"queued", "acquiring", "reporting"}
# Pending, not active: measurements are saved and verified OFF, the render is
# not yet dispatched. Acquisition may start while such jobs wait.
REPORT_QUEUED = "report-queued"
LAUNCH_GRACE_S = 5  # a launched worker may not have exec'd yet; see status()
DEFERRAL_LOG_INTERVAL_S = 60


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    return json.loads(Path(path).read_text())


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value) or value in (".", ".."):
        raise ValueError("Invalid local identifier")
    return value


def _inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escapes the local workspace")
    return path


def _pid_starting(pid):
    """True while the process exists and is running or sleeping (not a zombie or exited)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[0] not in ("Z", "X", "x")
    except (OSError, IndexError):
        return False


def _pid_matches(pid, job):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return b"dcdc_bench.job_service" in command and os.fsencode(str(job)) in command
    except OSError:
        return False


def _latest_cycle(path):
    """Read a bounded tail, never reload the whole streaming evidence file."""
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell()-32768))
            lines = handle.read().splitlines()
        cycles = {}
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if row.get("status") != "ok" or row.get("quality_flags"):
                continue
            value = row.get("value")
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            group = cycles.setdefault(row["acquisition_cycle_id"], {})
            group[row["quantity"]] = row
            if {"Vin_V", "Iin_A", "Vout_V", "Iout_A"} <= set(group):
                latest = max(group.values(), key=lambda item: item["query_end_utc"])
                return {k: group[k]["value"] for k in ("Vin_V", "Iin_A", "Vout_V", "Iout_A")}, latest["query_end_utc"]
    except OSError:
        pass
    return {}, None


def _recent_events(path, limit=12):
    """Read-only tail of a run's raw/events.jsonl for the UI's Recent events list; [] when absent."""
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell()-16384))
            lines = handle.read().splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            continue  # a partial trailing line while the worker is still writing
    return events


class JobService:
    def __init__(self, root: Path, inventory_path: Path | None = None, gate: MemoryGate | None = None):
        self.root = Path(root).resolve()
        self.inventory_path = Path(inventory_path).resolve() if inventory_path else None
        self.gate = gate  # None: read the thresholds from the environment at each dispatch
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("profiles", "previews", "jobs"):
            (self.root / name).mkdir(exist_ok=True)
        self.lock = FileLock(self.root / ".service.lock")
        self._seed()

    def _profile(self, kind, name):
        if kind not in MODELS:
            raise ValueError("Unknown profile kind")
        return _inside(self.root, self.root / "profiles" / kind / (_name(name)+".json"))

    def _seed(self):
        from .services import default_plan
        with self.lock:
            base = default_plan()
            for kind, profile in (("dut", base.dut), ("bench", base.bench), ("recipe", base.recipe)):
                path = self._profile(kind, getattr(profile, IDENTIFIERS[kind]))
                if not path.exists():
                    atomic_json(path, profile.model_dump())
            # Purpose-limited local bench preset, requiring fresh serial/wiring
            # confirmation on every start. It contains no endpoint or secrets.
            from .extended import extended_plan
            real = extended_plan()
            real.bench.bench_id = "rigol-local-limited"
            real.bench.source.max_current_A = real.bench.protective_controls.source_current_limit_A = 1.
            real.bench.source.max_voltage_V, real.bench.source.max_power_W = 35.8, 35.8
            real.bench.load.max_current_A = real.bench.protective_controls.output_overcurrent_A = 2.55
            real.bench.load.max_power_W = 34.
            real.bench.protective_controls.approved = False
            real.recipe.recipe_id = "real-24v-small-grid"
            real.recipe.tests = [real.recipe.tests[0].model_copy(update={"output_current_targets_A": [.1, .25, .5]})]
            real.recipe.acquisition.duration_s = 8.
            real.recipe.acquisition.target_poll_interval_s = 1.
            real.bench.notes = ["Purpose-limited DP821A CH1/local-load configuration; not certification of physical ratings.",
                                "Fresh physical confirmation and the private instrument inventory are required for each run."]
            for kind, profile in (("bench", real.bench), ("recipe", real.recipe)):
                path = self._profile(kind, getattr(profile, IDENTIFIERS[kind]))
                if not path.exists():
                    atomic_json(path, profile.model_dump())

    def list_profiles(self):
        return {kind: sorted(p.stem for p in (self.root / "profiles" / kind).glob("*.json")) for kind in MODELS}

    def load_profile(self, kind, name):
        return MODELS[kind].model_validate(_read(self._profile(kind, name))).model_dump()

    def save_profile(self, kind, data):
        if kind not in MODELS:
            raise ValueError("Unknown profile kind")
        if len(json.dumps(data)) > 2_000_000:
            raise ValueError("Profile exceeds 2 MB")
        profile = MODELS[kind].model_validate(data)
        name = getattr(profile, IDENTIFIERS[kind])
        with self.lock:
            atomic_json(self._profile(kind, name), profile.model_dump())
        return name

    def _inventory(self):
        if self.inventory_path is None or not self.inventory_path.is_file():
            raise ValueError("Configure the private bench inventory before a real run")
        if self.inventory_path.stat().st_size > 2_000_000:
            raise ValueError("Inventory exceeds 2 MB")
        from benchctl.config import load_config
        config = load_config(self.inventory_path)
        result = {}
        for role, name, driver, model in (("source", "psu_rigol_1", "rigol_dp800", "DP821A"),
                                        ("load", "load_rigol_1", "rigol_dl3000", "DL3031A")):
            device = config.devices.get(name)
            if device is None or device.driver != driver or not device.expected_serial:
                raise ValueError(f"Private inventory needs {name}, {driver} and its expected serial")
            result[role] = {"model": model, "serial": device.expected_serial}
        return result

    def preview(self, dut, bench, recipe):
        with self.lock:
            names = {"dut": dut, "bench": bench, "recipe": recipe}
            profiles = {kind: self.load_profile(kind, name) for kind, name in names.items()}
            plan = build_plan(DutProfile.model_validate(profiles["dut"]), BenchProfile.model_validate(profiles["bench"]),
                              TestRecipe.model_validate(profiles["recipe"]))
            errors, seconds, inventory = [], None, {}
            if plan.bench.mode == "real":
                from .real_backend import prepare_real_plan
                plan, errors, seconds = prepare_real_plan(plan)
                try:
                    inventory = self._inventory()
                except (ValueError, OSError) as exc:
                    errors.append(str(exc))
            counts = {}
            for point in plan.points:
                counts[point.status] = counts.get(point.status, 0)+1
            if not any(p.status == "executable" for p in plan.points):
                errors.append("No feasible point is available")
            value = {"plan_hash": plan.plan_hash, "mode": plan.bench.mode, "plan": plan.model_dump(),
                "points": [p.model_dump() for p in plan.points], "counts": counts,
                "warnings": plan.warnings, "supported": not errors, "errors": errors,
                "estimated_seconds": seconds, "inventory": inventory,
                "confirmation_required": ["wiring_and_polarity", "channel1", "protections_reviewed", "source_serial", "load_serial", "plan_hash"] if plan.bench.mode == "real" else [],
                "profiles": names, "profile_hashes": {k: _hash_payload(v) for k, v in profiles.items()},
                "inventory_sha256": _digest(self.inventory_path) if inventory else None}
            atomic_json(self.root / "previews" / (plan.plan_hash+".json"), value)
            return value

    def _job(self, job_id):
        return _inside(self.root, self.root / "jobs" / _name(job_id))

    @staticmethod
    def _launch(directory, *, report_only=False):
        command = [sys.executable, "-m", "dcdc_bench.job_service", "--worker", str(directory)]
        if report_only:
            command.append("--report-only")
        launch = {"requested_utc": datetime.now(timezone.utc).isoformat(), "pid": None}
        atomic_json(directory / "launch.json", launch)
        try:
            launcher = os.environ.get("DCDC_JOB_LAUNCHER", "detached")
            if launcher == "systemd":
                unit = "dcdc-job-" + directory.name + "-" + uuid.uuid4().hex[:8]
                # The worker must see the same lease path, tool paths, import path
                # and memory-gate thresholds as the dispatcher, or the child's
                # gate (services.report_run) diverges from the one that launched it.
                forwarded = sorted({"DCDC_ACTIVITY_LOCK", "QUARTO_PATH", "BROWSER_PATH", "PATH", "PYTHONPATH"}
                                   | {key for key in os.environ if key.startswith("DCDC_")})
                environment = [f"--setenv={key}={os.environ[key]}" for key in forwarded if key in os.environ]
                command = ["systemd-run", "--user", "--quiet", "--collect", "--unit="+unit,
                    "--property=Restart=no", "--property=RuntimeMaxSec=2700",
                    "--property=KillMode=control-group", "--property=TimeoutStopSec=20",
                    "--property=StandardOutput=append:"+str(directory / "worker.log"),
                    "--property=StandardError=append:"+str(directory / "worker.log"),
                    "--working-directory="+str(directory), *environment, *command]
                launched = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                          text=True, timeout=15)
                if launched.returncode:
                    raise OSError(launched.stderr.strip() or "systemd rejected the worker service")
                launch["unit"] = unit
                atomic_json(directory / "launch.json", launch)
                return
            if launcher != "detached":
                raise OSError("DCDC_JOB_LAUNCHER must be detached or systemd")
            with (directory / "worker.log").open("ab", buffering=0) as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True, close_fds=True)
                launch["pid"] = process.pid
                atomic_json(directory / "launch.json", launch)
        except (OSError, subprocess.SubprocessError) as exc:
            # The service may have been created before a launcher timeout.
            # Late workers must see cancellation even when launch reports failure.
            (directory / "cancel.request").touch()
            state = _read(directory / "job.json")
            state.update(state="failed", error=f"Worker could not start: {exc}")
            atomic_json(directory / "job.json", state)
            raise RuntimeError(state["error"]) from exc

    def start(self, plan_hash, confirmation=None, notes="", attachments=None):
        if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
            raise ValueError("Invalid plan hash")
        attachments = list(attachments or [])
        if len(attachments) > 20:
            raise ValueError("At most 20 attachment references are supported")
        for item in attachments:
            if not isinstance(item, dict) or set(item) != {"role", "name", "caption", "location"}:
                raise ValueError("Attachment references need role, name, caption and location")
            if any(not isinstance(v, str) or len(v) > 2000 for v in item.values()):
                raise ValueError("Attachment reference fields must be text of at most 2000 characters")
            if item["role"] not in {"schematic", "board_photo", "setup_photo", "temperature_location", "other"}:
                raise ValueError("Unknown attachment role")
        with self.lock:
            preview = _read(self.root / "previews" / (plan_hash+".json"))
            if not preview["supported"]:
                raise ValueError("Unsupported plan: " + "; ".join(preview["errors"]))
            for kind, name in preview["profiles"].items():
                if _hash_payload(self.load_profile(kind, name)) != preview["profile_hashes"][kind]:
                    raise ValueError("A saved profile changed; preview and confirm the new plan")
            plan = Plan.model_validate(preview["plan"])
            if not verify_plan_hash(plan) or plan.plan_hash != plan_hash:
                raise ValueError("Saved plan was changed")
            confirmation = dict(confirmation or {})
            if plan.bench.mode == "real":
                # A cached preview is not an authorization: rebuild from the
                # profiles as saved now and re-run every real-plan check.
                from .real_backend import prepare_real_plan
                rebuilt, errors, _ = prepare_real_plan(build_plan(plan.dut, plan.bench, plan.recipe))
                if errors or rebuilt.plan_hash != plan_hash:
                    raise ValueError("Unsupported plan: " + "; ".join(errors or ["plan no longer matches its profiles"]))
                inventory = self._inventory()
                if _digest(self.inventory_path) != preview["inventory_sha256"]:
                    raise ValueError("Instrument inventory changed; preview again")
                if confirmation.get("plan_hash") != plan_hash or not all(confirmation.get(k) is True for k in
                        ("wiring_and_polarity", "channel1", "protections_reviewed")):
                    raise ValueError("Confirm wiring, CH1, protections and this exact plan before arming")
                if any(confirmation.get(role+"_serial") != data["serial"] for role, data in inventory.items()):
                    raise ValueError("Confirmed instrument serials do not match the preview")
            if any(job["state"] in ACTIVE for job in self.list_jobs()):
                raise ValueError("A job is already acquiring or reporting; no automatic hardware queue")
            from .activity import bench_activity
            with bench_activity("acquisition"):
                pass  # Busy now means no queued surprise activation later.
            job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"_"+uuid.uuid4().hex[:8]
            directory = self._job(job_id)
            directory.mkdir()
            atomic_json(directory / "plan.json", plan.model_dump())
            atomic_json(directory / "request.json", {"confirmation": confirmation, "notes": str(notes)[:10000],
                "attachments": attachments, "profile_hashes": preview["profile_hashes"],
                "inventory_sha256": preview["inventory_sha256"]})
            if plan.bench.mode == "real":
                (directory / "inventory.yaml").write_bytes(self.inventory_path.read_bytes())
                (directory / "inventory.yaml").chmod(0o600)
            atomic_json(directory / "job.json", {"job_id": job_id, "state": "queued", "mode": plan.bench.mode,
                "dut_model": plan.dut.identity.model,
                "pid": None, "created_utc": datetime.now(timezone.utc).isoformat(), "error": None,
                "run_dir": None, "report_dir": None})
            self._launch(directory)
            return {"job_id": job_id, "state": "queued"}

    def retry_report(self, job_id, annotations=None):
        """Queue a new report revision from existing evidence; never starts acquisition.

        A busy bench queues the request instead of refusing it: dispatch_reports
        launches the render once no job is active and the memory gate passes.
        Optional sensor placement annotations are bound to a stored original's
        hash now and written into the new revision by the report-only worker.
        """
        with self.lock:
            job, state = self._job(job_id), self.status(job_id)
            if state["state"] in ACTIVE:
                raise ValueError("An acquisition/report job is already active")
            if not state.get("run_dir"):
                raise ValueError("No finalized acquisition exists")
            path = _inside(job, state["run_dir"])
            _verified_off(path)
            request = job / "annotations.request.json"
            if annotations is not None:
                from .annotations import bind_annotations
                atomic_json(request, bind_annotations(path, annotations)[0])
            else:
                request.unlink(missing_ok=True)
            record = _read(job / "job.json")
            record.update(state=REPORT_QUEUED, pid=None, error=None, action="report-only", run_dir=str(path),
                          queued_utc=_utc_now(), deferred_reason=None, deferred_utc=None)
            atomic_json(job / "job.json", record)
            return {"job_id": job_id, "state": REPORT_QUEUED}

    def _job_records(self):
        """Raw job.json records by job name; no run.json or sample-tail reads (cheap for a 2 s timer)."""
        records = {}
        for entry in (self.root / "jobs").iterdir():
            try:
                records[entry.name] = _read(entry / "job.json")
            except (OSError, ValueError):
                continue
        return records

    def _report_queue(self, records=None):
        """Raw job.json states, oldest queued first; cheap enough for a 2 s timer."""
        records = self._job_records() if records is None else records
        queued = [(record.get("queued_utc") or "", name) for name, record in records.items()
                  if record.get("state") == REPORT_QUEUED]
        return [name for _, name in sorted(queued)]

    def _bench_busy(self, records):
        """True while a job is queued/acquiring/reporting.

        Only records whose raw state is ACTIVE are re-derived through status(),
        which also detects a dead worker or an expired launch; the idle path
        reads nothing but job.json files.
        """
        return any(self.status(name)["state"] in ACTIVE for name, record in records.items()
                   if record.get("state") in ACTIVE)

    def dispatch_reports(self):
        """Launch at most one report-only worker, only when the bench is idle and memory allows.

        Called from the UI's periodic timer, never from a request handler. A
        job that is queued/acquiring/reporting, a held bench lease, or a failed
        memory gate leaves the queue untouched; the deferral is recorded on the
        oldest queued job so the operator can see why nothing is rendering.
        """
        with self.lock:
            records = self._job_records()
            queue = self._report_queue(records)
            if not queue or self._bench_busy(records):
                return None
            job_id = queue[0]
            directory = self._job(job_id)
            # Re-read under the lock: cancel() also writes this record under the lock.
            record = _read(directory / "job.json")
            if record.get("state") != REPORT_QUEUED:
                return None
            logs = (directory / "resources.jsonl", self.root / "resource-log.jsonl")
            from .activity import bench_activity
            try:
                with bench_activity("report"):
                    pass
            except RuntimeError as exc:
                return self._defer(directory, record, f"bench lease held: {exc}", None, logs)
            try:
                gate = self.gate if self.gate is not None else MemoryGate()
                ok, reason, snap = gate.check()
            except ValueError as exc:
                # A malformed threshold variable must not stall the queue silently.
                return self._defer(directory, record, f"memory gate misconfigured: {exc}", None, logs)
            if not ok:
                return self._defer(directory, record, reason, snap, logs)
            (directory / "cancel.request").unlink(missing_ok=True)
            record.update(state="queued", pid=None, error=None, action="report-only",
                          deferred_reason=None, deferred_utc=None, dispatched_utc=_utc_now())
            atomic_json(directory / "job.json", record)
            for path in logs:
                try_log_event(path, "dispatch", "start", job_id=job_id, snap=snap, gate_reason=reason)
            self._launch(directory, report_only=True)
            return {"job_id": job_id, "state": "queued"}

    def add_attachment(self, job_id, filename, data, *, caption="", owner="operator"):
        """Store one validated documentation asset for a finalized run.

        The original is content-addressed and listed in a new documentation
        revision manifest; integrity.json and the acquisition manifest are
        verified unchanged afterwards. No worker or instrument is involved.
        """
        from .attachments import AssetStore, validate_asset
        # Content validation (PDF/SVG parsing can take seconds) runs before the
        # service lock so a slow upload never blocks start, preview or the
        # report dispatcher; the store re-binds the result to the bytes by hash.
        validated = validate_asset(data, filename)
        with self.lock:
            job, state = self._job(job_id), self.status(job_id)
            if state["state"] in ACTIVE:
                raise ValueError("Wait for the job to finish before attaching documentation")
            if not state.get("run_dir"):
                raise ValueError("No finalized acquisition exists")
            path = _inside(job, state["run_dir"])
            verify_integrity(path)
            entry = AssetStore(path).add(data, filename, caption=caption, owner=owner, validated=validated)
            verify_integrity(path)
            return entry

    @staticmethod
    def _defer(directory, record, reason, snap, logs):
        job_id = record.get("job_id", directory.name)
        previous = record.get("deferred_utc")
        try:
            stale = previous is None or (datetime.now(timezone.utc) - datetime.fromisoformat(previous)).total_seconds() > DEFERRAL_LOG_INTERVAL_S
        except (TypeError, ValueError):
            stale = True
        # The reason text is stable (numbers live in the snapshot), so a 2 s
        # timer does not rewrite job.json or append a log line on every tick.
        if record.get("deferred_reason") != reason or stale:
            # Never resurrect a job the operator removed from the queue meanwhile.
            current = _read(directory / "job.json")
            if current.get("state") != REPORT_QUEUED:
                return {"job_id": job_id, "state": current.get("state"), "deferred_reason": None}
            record.update(deferred_reason=reason, deferred_utc=_utc_now())
            atomic_json(directory / "job.json", record)
            for path in logs:
                try_log_event(path, "dispatch", "deferred", job_id=job_id, reason=reason, snap=snap)
        return {"job_id": job_id, "state": REPORT_QUEUED, "deferred_reason": reason}

    def status(self, job_id):
        job = self._job(job_id)
        value = _read(job / "job.json")
        launch = _read(job / "launch.json") if (job / "launch.json").exists() else {}
        if not value.get("pid"):
            value["pid"] = launch.get("pid")
        value.update(progress={"completed": 0, "total": 0, "current": None}, latest={}, shutdown={},
                     report_artifacts={}, elapsed_s=None, latest_age_s=None, latest_kind="unqualified live readings")
        candidates = sorted((job / "runs").glob("*/run.json"))
        if candidates:
            run = _read(candidates[-1])
            value["run_dir"] = str(candidates[-1].parent)
            value["progress"] = {"completed": sum(p.get("qualification") == "valid" for p in run["points"]),
                "total": sum(p.get("status", p.get("planning_status")) == "executable" for p in run["points"]), "current": run.get("current_point_id")}
            value["latest"], value["shutdown"] = run.get("latest", {}), run.get("shutdown", {})
            value["execution_status"] = run.get("execution_status")
            current = next((p for p in run["points"] if p["point_id"] == run.get("current_point_id")), {})
            value["progress"].update(requested_input_V=current.get("vin_target_V"), requested_output_A=current.get("iout_target_A"))
            now = datetime.now(timezone.utc)
            value["elapsed_s"] = run.get("duration_s", (now-datetime.fromisoformat(run["created_utc"])).total_seconds())
            latest, timestamp = _latest_cycle(candidates[-1].parent / "raw/samples.jsonl")
            if latest:
                value["latest"] = latest
                value["latest_age_s"] = max(0., (now-datetime.fromisoformat(timestamp)).total_seconds())
            value["events"] = _recent_events(candidates[-1].parent / "raw/events.jsonl")
        if value.get("report_dir"):
            report = _inside(job, value["report_dir"])
            if (report / "build_manifest.json").is_file():
                manifest = _read(report / "build_manifest.json")
                for fmt in ("html", "pdf"):
                    artifact = dict(manifest.get("artifacts", {}).get(fmt, {"status": "unavailable"}))
                    if artifact.get("status") in ("success", "unverified", "failed-validation") and not (report / ("report."+fmt)).is_file():
                        artifact["status"] = "missing"
                    value["report_artifacts"][fmt] = artifact
                value["report_artifacts"]["model"] = {
                    "status": "success" if (report / "report_model.json").is_file() else "missing"}
        if value["state"] in ACTIVE and value.get("pid") and not _pid_matches(value["pid"], job):
            # Between fork and exec the child's command line is still the launcher's;
            # a launch younger than the grace window is starting, not dead.
            requested = launch.get("requested_utc")
            try:
                launch_age_s = (datetime.now(timezone.utc) - datetime.fromisoformat(requested)).total_seconds() if requested else None
            except (TypeError, ValueError):
                launch_age_s = None
            starting = launch_age_s is not None and launch_age_s <= LAUNCH_GRACE_S and _pid_starting(value["pid"])
            if not starting:
                value.update(state="failed", error="Worker exited unexpectedly; inspect shutdown evidence before another real run")
        elif value["state"] == "queued" and launch.get("requested_utc"):
            if (datetime.now(timezone.utc)-datetime.fromisoformat(launch["requested_utc"])).total_seconds() > 120:
                value.update(state="failed", error="Worker launch expired before acquisition; no automatic restart")
        elif value["state"] == REPORT_QUEUED:
            value["pid"] = None  # the acquisition worker has exited; no process owns this job yet
        value.setdefault("deferred_reason", None)
        value["report_pending"] = value["state"] == REPORT_QUEUED
        value["cancel_requested"] = (job / "cancel.request").exists()
        return value

    def list_jobs(self):
        return [self.status(p.name) for p in sorted((self.root / "jobs").iterdir(), reverse=True) if (p / "job.json").is_file()]

    def cancel(self, job_id):
        job = self._job(job_id)
        with self.lock:
            # dispatch_reports and _defer read-modify-write this record under the
            # same lock; taking it here means a cancel is never lost to a
            # concurrent dispatch, and a cancelled job is never re-queued.
            value = self.status(job_id)
            if value["state"] == REPORT_QUEUED:
                # Nothing is running: leave the queue without signalling any process.
                record = _read(job / "job.json")
                if record.get("state") != REPORT_QUEUED:
                    return self.status(job_id)
                record.update(state="cancelled", pid=None, deferred_reason=None,
                              error="Report generation was removed from the queue; saved measurements are preserved")
                atomic_json(job / "job.json", record)
                return self.status(job_id)
        if value["state"] not in ACTIVE:
            return value
        (job / "cancel.request").touch()
        pid = value.get("pid")
        if _pid_matches(pid, job):
            try:
                # Pin the process identity while checking and signalling it.
                fd = os.pidfd_open(pid)
                try:
                    if _pid_matches(pid, job):
                        signal.pidfd_send_signal(fd, signal.SIGINT)
                finally:
                    os.close(fd)
            except ProcessLookupError:
                pass
        return self.status(job_id)

    def resolve_file(self, job_id, relative):
        value, job = self.status(job_id), self._job(job_id)
        head, _, tail = relative.partition("/")
        base = value.get("report_dir") if head == "report" else value.get("run_dir") if head == "run" else None
        if not base or not tail:
            raise ValueError("No matching job artifact")
        path = _inside(job, _inside(base, Path(base) / tail))
        if not path.is_file():
            raise FileNotFoundError(path.name)
        return path


def _verified_off(path):
    verify_integrity(path)
    manifest = _read(Path(path) / "integrity.json")
    if not {"run.json", "plan.json", "request.json", "raw/samples.jsonl"} <= set(manifest.get("files", {})):
        raise ValueError("Integrity manifest does not cover required report evidence")
    run = _read(Path(path) / "run.json")
    required = {"source", "load", "source_deadline"} if run.get("data_source") == "measured" else {"source", "load"}
    if not required <= set(run.get("shutdown", {})) or not all(s.get("state") == "OFF" and s.get("verified") is True for s in run["shutdown"].values()):
        raise RuntimeError("Shutdown is not fully verified OFF; report job was not started")
    return run


def _report_command(path, annotations=None):
    command = [sys.executable, "-m", "dcdc_bench", "report", str(path), "--formats", "html,pdf"]
    if annotations is not None:
        command += ["--annotations", str(annotations)]
    return command


def _job_resource_log(path):
    """<job>/resources.jsonl when ``path`` is a run directory inside a job; else None."""
    job = Path(path).resolve().parent.parent
    return job / "resources.jsonl" if (job / "job.json").is_file() else None


def _sweep_report_group(pgid, log_path, started, returncode):
    """After the report child exits, on every path: find, log and stop what it left behind."""
    try:
        survivors = session_survivors(pgid)
        try_log_event(log_path, "report-process", "survivors", child_pid=pgid, count=len(survivors), processes=survivors)
        if survivors:
            outcome = terminate_group(pgid, grace_s=5.)
            try_log_event(log_path, "report-process", "survivors", child_pid=pgid, count=len(outcome["remaining"]),
                          processes=outcome["remaining"], terminated=outcome["signalled"], killed=outcome["killed"])
        try_log_event(log_path, "report-process", "end", child_pid=pgid, duration_s=round(time.monotonic() - started, 3),
                      returncode=returncode, child_peak_rss_mib=children_peak_rss_mib())
    except Exception as exc:  # hygiene never masks the report outcome
        try_log_event(log_path, "report-process", "end", child_pid=pgid, duration_s=round(time.monotonic() - started, 3),
                      returncode=returncode, error=f"{type(exc).__name__}: {exc}")


def _render_process(path, annotations=None, log_path=None):
    """Run the report CLI in its own session and sweep that session when it ends.

    ``annotations`` is an optional bound sensor-placement request file forwarded
    to ``dcdc-bench report --annotations``; it never changes acquisition evidence.
    """
    log_path = log_path or _job_resource_log(path)
    started = time.monotonic()
    child = subprocess.Popen(_report_command(path, annotations), stdin=subprocess.DEVNULL, start_new_session=True)
    try_log_event(log_path, "report-process", "start", child_pid=child.pid)
    returncode = None
    try:
        returncode = child.wait(timeout=1800)
        return returncode
    except BaseException:
        # Own only this report process group. No instrument process belongs to it.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=10)
        raise
    finally:
        _sweep_report_group(child.pid, log_path, started, returncode)


def worker(directory: Path, *, report_only=False):
    directory = Path(directory).resolve()
    state = _read(directory / "job.json")
    state["pid"] = os.getpid()
    task = "report-only" if report_only else "acquisition"
    logs = (directory / "resources.jsonl", directory.parent.parent / "resource-log.jsonl")
    started = time.monotonic()
    def save(**changes):
        state.update(changes)
        atomic_json(directory / "job.json", state)
    def record(phase, **fields):
        for path in logs:
            try_log_event(path, task, phase, job_id=state.get("job_id"), **fields)
    record("start")
    save(state="reporting" if report_only else "acquiring")
    try:
        launch = _read(directory / "launch.json") if (directory / "launch.json").exists() else {}
        if launch.get("requested_utc") and (datetime.now(timezone.utc)-datetime.fromisoformat(launch["requested_utc"])).total_seconds() > 120:
            raise RuntimeError("Worker launch expired; start a fresh confirmed job")
        if (directory / "cancel.request").exists():
            save(state="cancelled")
            return
        plan = Plan.model_validate(_read(directory / "plan.json"))
        if not verify_plan_hash(plan):
            raise ValueError("Job plan changed")
        request = _read(directory / "request.json")
        if report_only:
            path = _inside(directory, state["run_dir"])
        elif plan.bench.mode == "real":
            if _digest(directory / "inventory.yaml") != request["inventory_sha256"]:
                raise ValueError("Saved job inventory changed")
            from .real_backend import run_real
            path = run_real(plan, directory / "inventory.yaml", directory / "runs",
                confirmation=request["confirmation"], cancel=directory / "cancel.request",
                notes=request.get("notes", ""), attachments=request.get("attachments", []))
        else:
            from .activity import bench_activity
            from .services import acquire_mock
            with bench_activity("acquisition"):
                # Dispatched by test type: an all-UVLO plan runs the phase-scoped
                # ramp procedure, a load sweep the generic loop; mixed plans were
                # refused at planning time.
                path = acquire_mock(plan, directory / "runs", operator_observations=[request["notes"]] if request.get("notes") else [],
                                    attachment_descriptors=request.get("attachments", []))
        run = _verified_off(path)
        save(run_dir=str(path))
        cancelled_acquisition = (directory / "cancel.request").exists()
        if not report_only:
            # Outputs are verified OFF. Exit now so drivers and acquisition state
            # leave RAM before the heaviest phase; the UI dispatcher launches a
            # fresh report-only worker once the bench is idle and memory allows.
            save(state=REPORT_QUEUED, pid=None, queued_utc=_utc_now(), acquisition_cancelled=cancelled_acquisition,
                 deferred_reason=None, deferred_utc=None)
            return
        save(state="reporting")
        # A separate process owns all optional/heavy reporting dependencies.
        request = directory / "annotations.request.json"
        returncode = _render_process(path, request) if report_only and request.is_file() else _render_process(path)
        reports = sorted((path / "reports").glob("r*"))
        report = reports[-1] if reports else None
        manifest = _read(report / "build_manifest.json") if report and (report / "build_manifest.json").exists() else {}
        if returncode or manifest.get("status") not in ("success", "unverified"):
            save(state="failed", error="Acquisition preserved; report generation failed. See worker.log and build manifest.",
                 report_dir=str(report) if report else None)
        else:
            cancelled = cancelled_acquisition or state.get("acquisition_cancelled") is True
            # "unverified": every document built, but the PDF pagination checker
            # could not run (tool missing). The documents are kept and linked;
            # the note stays visible so nobody mistakes this for a verified PDF.
            note = None
            if manifest.get("status") == "unverified":
                note = manifest.get("artifacts", {}).get("pdf", {}).get("note") or "PDF not verified: tool missing"
            save(state="cancelled" if cancelled else "completed" if run["execution_status"] == "completed" else "aborted",
                 report_dir=str(report), report_note=note)
    except KeyboardInterrupt:
        save(state="cancelled", error="Operator cancelled the job; inspect recorded shutdown status")
    except BaseException as exc:
        save(state="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        record("end", duration_s=round(time.monotonic() - started, 3), state=state.get("state"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    worker(args.worker, report_only=args.report_only)
