"""benchctl: bench instrument control for Rigol supplies and loads.

Layers: a strictly validated YAML inventory (Software/config/lab.yaml) maps logical
setups to devices; the registry maps device driver names to family drivers
(DP800 supplies, DL3000 loads); drivers talk through an injected PyVISA-Py
transport with per-instrument locking and JSONL command logging.

Safety model: every state-changing command is validated against manually
maintained physical limits (Software/config/safety_profiles.yaml) before any VISA
session is opened, limits are never derived from reported model names, and
drivers drain the SCPI error queue after each write. Software limits
complement, never replace, the instruments' hardware OVP/OCP/OPP.
"""

__version__ = "0.1.0"
