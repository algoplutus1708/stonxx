"""
state_manager.py
================
Lightweight local state persistence for the stonxx trading bot.

Usage (inside any LumiBot Strategy):
    from state_manager import load_state, save_state, STATE_FILE

The state file is written atomically (write-then-rename) so a crash
mid-write never produces a corrupt JSON file.
"""

import json
import logging
import os
import tempfile

# ---------------------------------------------------------------------------
# Public constant — keep the filename in one place so callers can reference it
# ---------------------------------------------------------------------------
STATE_FILE: str = "bot_state.json"

# Default shape of the state dict that every consumer can depend on
_DEFAULT_STATE: dict = {
    "active_trades": {},
    "pending_orders": [],
    "paper_cash": 0.0,
    "last_signal_date": None,
    "last_submission_date": None,
    # Future keys can be added here without breaking old state files
}

logger = logging.getLogger(__name__)


def load_state(path: str = STATE_FILE) -> dict:
    """
    Read the persisted bot state from *path*.

    Returns a deep-copy of ``_DEFAULT_STATE`` if the file does not exist or
    cannot be parsed (so the bot always starts with a valid dict).

    Parameters
    ----------
    path : str
        Path to the JSON state file.  Defaults to ``STATE_FILE``.

    Returns
    -------
    dict
        Parsed state dictionary, guaranteed to contain at least the keys
        defined in ``_DEFAULT_STATE``.
    """
    import copy
    default = copy.deepcopy(_DEFAULT_STATE)

    if not os.path.exists(path):
        logger.info("[state_manager] No state file found at '%s'. Starting fresh.", path)
        return default

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "[state_manager] Could not read '%s' (%s). Returning default state.", path, exc
        )
        return default

    # Merge loaded data on top of defaults so new keys always exist
    for key, val in default.items():
        data.setdefault(key, val)

    return data


def save_state(state_dict: dict, path: str = STATE_FILE) -> None:
    """
    Atomically persist *state_dict* to *path*.

    The write is done to a sibling temp-file first; on success the temp-file
    is renamed over the target — ensuring the target is never left half-written
    even if the process is killed mid-flush.

    Parameters
    ----------
    state_dict : dict
        The state dictionary to persist.
    path : str
        Destination file path.  Defaults to ``STATE_FILE``.
    """
    dir_name = os.path.dirname(os.path.abspath(path))
    try:
        # Write to a temp file in the same directory (same filesystem → rename is atomic)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dir_name,
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(state_dict, tmp, indent=4)
            tmp_path = tmp.name

        os.replace(tmp_path, path)  # atomic on POSIX; best-effort on Windows
        logger.debug("[state_manager] State saved to '%s'.", path)

    except OSError as exc:
        logger.error("[state_manager] Failed to save state to '%s': %s", path, exc)
        # Clean up orphaned temp file if rename failed
        try:
            os.remove(tmp_path)
        except OSError:
            pass
