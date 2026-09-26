"""Read-only HTTP status dashboard.

Safety boundary
---------------
This module is strictly read-only toward instruments:

* The only driver methods it ever invokes are ``identify()`` and the
  ``measure_voltage`` / ``measure_current`` / ``measure_power`` queries.
  Nothing in this module imports or calls code that can enable or disable
  an output or input, and no request parameter is ever forwarded to an
  instrument.
* The HTTP surface is GET-only; every other method receives 405.

Instruments are guarded by an exclusive per-resource ``flock``, so VISA
sessions are kept short (open, read, close on every poll) and all polling
is serialized behind a single lock -- concurrent HTTP requests never talk
to instruments at the same time.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlsplit

from benchctl.config import DeviceConfig, LabConfig
from benchctl.identity import identify_and_verify
from benchctl.interfaces import Transport
from benchctl.registry import get_driver_class

TransportFactory = Callable[[str, DeviceConfig], Transport]
DriverFactory = Callable[[str], Any]

# Channels polled on a power supply (per the rigol_dp800 driver contract).
SUPPLY_CHANNELS = (1, 2)


class StatusCollector:
    """Gathers read-only device information on demand.

    Each poll opens a fresh transport per device and closes it before
    moving on, and ``status()`` holds a lock for the whole sweep so
    instrument access is never concurrent.
    """

    def __init__(
        self,
        config: LabConfig,
        transport_factory: TransportFactory,
        driver_factory: DriverFactory = get_driver_class,
    ) -> None:
        self._config = config
        self._transport_factory = transport_factory
        self._driver_factory = driver_factory
        self._poll_lock = threading.Lock()

    def devices(self) -> dict[str, Any]:
        """Static device inventory from the configuration (no I/O)."""
        return {
            name: device.model_dump()
            for name, device in self._config.devices.items()
        }

    def status(self) -> dict[str, Any]:
        """Identify and measure every configured device, serially."""
        with self._poll_lock:
            return {
                name: self._poll_device(name, device)
                for name, device in self._config.devices.items()
            }

    def _poll_device(self, name: str, device: DeviceConfig) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "kind": device.kind,
            "driver": device.driver,
            "resource": device.resource,
            "identify": None,
            "measurements": None,
            "error": None,
        }
        try:
            driver_cls = self._driver_factory(device.driver)
            with self._transport_factory(name, device) as transport:
                driver = driver_cls(transport)
                identification = identify_and_verify(name, device, driver)
                entry["identify"] = asdict(identification)
                entry["measurements"] = self._measure(driver, device.kind)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry

    @staticmethod
    def _measure(driver: Any, kind: str) -> dict[str, Any]:
        # Read-only allowlist: measure_voltage / measure_current /
        # measure_power are the only methods called besides identify().
        if kind == "power_supply":
            return {
                f"channel_{channel}": {
                    "voltage_v": float(driver.measure_voltage(channel)),
                    "current_a": float(driver.measure_current(channel)),
                    "power_w": float(driver.measure_power(channel)),
                }
                for channel in SUPPLY_CHANNELS
            }
        return {
            "voltage_v": float(driver.measure_voltage()),
            "current_a": float(driver.measure_current()),
            "power_w": float(driver.measure_power()),
        }


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>benchctl status</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem;
         background: #14171c; color: #e8eaed; }
  h1 { font-size: 1.3rem; }
  .muted { color: #9aa0a6; font-size: 0.85rem; }
  .device { border: 1px solid #2c313a; border-radius: 8px; padding: 1rem;
            margin: 1rem 0; background: #1b1f26; }
  .device h2 { margin: 0 0 0.3rem; font-size: 1.05rem; }
  .error { color: #f28b82; }
  table { border-collapse: collapse; margin-top: 0.5rem; }
  td, th { padding: 0.2rem 0.9rem 0.2rem 0; text-align: left;
           font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<h1>benchctl &mdash; read-only status</h1>
<p class="muted">Auto-refreshes every 3 seconds. <span id="updated"></span></p>
<div id="devices"><p class="muted">Loading&hellip;</p></div>
<script>
"use strict";
function cell(row, text, tag) {
  const el = document.createElement(tag || "td");
  el.textContent = text;
  row.appendChild(el);
}
function measurementTable(measurements) {
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["", "Voltage (V)", "Current (A)", "Power (W)"].forEach(function (t) {
    cell(head, t, "th");
  });
  table.appendChild(head);
  const rows = ("voltage_v" in measurements)
    ? [["", measurements]]
    : Object.keys(measurements).sort().map(function (k) {
        return [k.replace("_", " "), measurements[k]];
      });
  rows.forEach(function (pair) {
    const tr = document.createElement("tr");
    cell(tr, pair[0]);
    ["voltage_v", "current_a", "power_w"].forEach(function (key) {
      const v = pair[1][key];
      cell(tr, typeof v === "number" ? v.toFixed(3) : "-");
    });
    table.appendChild(tr);
  });
  return table;
}
function render(status) {
  const root = document.getElementById("devices");
  root.replaceChildren();
  Object.keys(status).sort().forEach(function (name) {
    const d = status[name];
    const box = document.createElement("div");
    box.className = "device";
    const title = document.createElement("h2");
    title.textContent = name + " (" + d.kind + ")";
    box.appendChild(title);
    const meta = document.createElement("p");
    meta.className = "muted";
    let line = d.resource + " \u00b7 driver " + d.driver;
    if (d.identify) {
      line += " \u00b7 " + d.identify.manufacturer + " " + d.identify.model +
              " \u00b7 s/n " + d.identify.serial + " \u00b7 fw " + d.identify.firmware;
    }
    meta.textContent = line;
    box.appendChild(meta);
    if (d.error) {
      const err = document.createElement("p");
      err.className = "error";
      err.textContent = "offline: " + d.error;
      box.appendChild(err);
    } else if (d.measurements) {
      box.appendChild(measurementTable(d.measurements));
    }
    root.appendChild(box);
  });
}
async function refresh() {
  try {
    const response = await fetch("/api/status");
    render(await response.json());
    document.getElementById("updated").textContent =
      "Last update: " + new Date().toLocaleTimeString();
  } catch (err) {
    document.getElementById("updated").textContent = "Update failed: " + err;
  } finally {
    setTimeout(refresh, 3000);
  }
}
refresh();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    """GET-only request handler; every other HTTP method gets 405."""

    server_version = "benchctl-web"
    collector: StatusCollector  # set on the subclass built by create_server()

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = urlsplit(self.path).path
        if path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/devices":
            self._send_json(200, self.collector.devices())
        elif path == "/api/status":
            self._send_json(200, self.collector.status())
        else:
            self._send_json(404, {"error": f"unknown path {path!r}"})

    def _method_not_allowed(self) -> None:
        body = json.dumps({"error": "read-only server: only GET is allowed"})
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    # The dashboard is strictly read-only over HTTP as well.
    do_POST = _method_not_allowed  # noqa: N815
    do_PUT = _method_not_allowed  # noqa: N815
    do_DELETE = _method_not_allowed  # noqa: N815
    do_PATCH = _method_not_allowed  # noqa: N815
    do_HEAD = _method_not_allowed  # noqa: N815

    def _send_json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # keep the console quiet; transport has its own JSONL log


def create_server(
    config: LabConfig,
    transport_factory: TransportFactory,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    driver_factory: DriverFactory = get_driver_class,
) -> ThreadingHTTPServer:
    """Build a ThreadingHTTPServer serving the read-only dashboard.

    Pass ``port=0`` to bind an ephemeral port (``server.server_address``
    reports the assigned one). The caller owns the server lifecycle.
    """
    collector = StatusCollector(config, transport_factory, driver_factory)
    handler = type("BoundDashboardHandler", (DashboardHandler,), {"collector": collector})
    return ThreadingHTTPServer((host, port), handler)
