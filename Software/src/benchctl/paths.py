"""Repository-relative defaults; run the CLI from the project root.

Keeping these together makes the project layout easy to change.
Explicit CLI paths still work for inventories and results stored elsewhere.
"""

from pathlib import Path

SOFTWARE_DIR = Path("Software")
DEFAULT_CONFIG_PATH = SOFTWARE_DIR / "config" / "lab.yaml"
DEFAULT_SAFETY_PROFILES_PATH = SOFTWARE_DIR / "config" / "safety_profiles.yaml"
DEFAULT_RESULTS_DIR = Path("Data") / "Runs"
DEFAULT_LOG_PATH = Path("Data") / "Logs" / "commands.jsonl"
