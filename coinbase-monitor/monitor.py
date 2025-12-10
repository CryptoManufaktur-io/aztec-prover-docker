#!/usr/bin/env python3
"""
Aztec Coinbase Monitor

Monitors the Staking Dashboard API for new delegations to your provider
and automatically updates the coinbase addresses in sequencers.json
to point to the correct split contract addresses.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Configuration from environment variables
PROVIDER_ID = os.getenv("PROVIDER_ID", "")
STAKING_API_URL = os.getenv("STAKING_API_URL", "")
MONITOR_POLL_INTERVAL = int(os.getenv("MONITOR_POLL_INTERVAL", "300"))  # seconds
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
KEYSTORE_PATH = os.getenv("KEYSTORE_PATH", "/keystore")
DATA_PATH = os.getenv("DATA_PATH", "/data")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Error alerting configuration
ERROR_ALERT_THRESHOLD = int(os.getenv("ERROR_ALERT_THRESHOLD", "3"))  # Alert after N consecutive failures
ERROR_ALERT_COOLDOWN = int(os.getenv("ERROR_ALERT_COOLDOWN", "3600"))  # Seconds between error alerts (1 hour)

# File paths
# sequencers.json is in keystore (read/write)
SEQUENCERS_FILE = Path(KEYSTORE_PATH) / "sequencers.json"
# State and mappings files are in data volume (separate from keystore)
STATE_FILE = Path(DATA_PATH) / "coinbase-monitor-state.json"
MAPPINGS_FILE = Path(DATA_PATH) / "coinbase-mappings.json"

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Error tracking state
error_state = {
    "consecutive_failures": 0,
    "last_error_alert_time": 0,
    "last_error_type": None,
    "was_in_error_state": False
}


def send_slack_notification(message: str, blocks: list[dict] | None = None) -> bool:
    """Send a notification to Slack webhook."""
    if not SLACK_WEBHOOK_URL:
        logger.debug("Slack webhook URL not configured, skipping notification")
        return False

    try:
        payload = {"text": message}
        if blocks:
            payload["blocks"] = blocks

        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        logger.info("Slack notification sent successfully")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


def send_error_alert(error_type: str, error_message: str) -> None:
    """Send Slack alert for errors with rate limiting."""
    global error_state

    error_state["consecutive_failures"] += 1
    error_state["last_error_type"] = error_type

    # Check if we should send an alert
    current_time = time.time()
    time_since_last_alert = current_time - error_state["last_error_alert_time"]

    should_alert = (
        error_state["consecutive_failures"] >= ERROR_ALERT_THRESHOLD
        and time_since_last_alert >= ERROR_ALERT_COOLDOWN
    )

    if should_alert:
        message = (
            f"🚨 *Aztec Coinbase Monitor Error*\n\n"
            f"Provider ID: {PROVIDER_ID}\n"
            f"Error Type: {error_type}\n\n"
            f"`{error_message}`\n\n"
            f"Consecutive failures: {error_state['consecutive_failures']}\n"
            f"Will retry in {MONITOR_POLL_INTERVAL} seconds."
        )
        if send_slack_notification(message):
            error_state["last_error_alert_time"] = current_time
            error_state["was_in_error_state"] = True


def send_recovery_alert() -> None:
    """Send Slack alert when service recovers from errors."""
    global error_state

    if error_state["was_in_error_state"] and error_state["consecutive_failures"] > 0:
        failures = error_state["consecutive_failures"]
        message = (
            f"✅ *Aztec Coinbase Monitor Recovered*\n\n"
            f"Provider ID: {PROVIDER_ID}\n"
            f"Service resumed normal operation after {failures} failed attempt(s)."
        )
        send_slack_notification(message)

    # Reset error state
    error_state["consecutive_failures"] = 0
    error_state["last_error_type"] = None
    error_state["was_in_error_state"] = False


def fetch_provider_data() -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch provider data from the Staking Dashboard API.

    Returns:
        Tuple of (data, error_message). If successful, error_message is None.
    """
    url = f"{STAKING_API_URL}/providers/{PROVIDER_ID}"

    try:
        logger.debug(f"Fetching provider data from {url}")
        response = requests.get(
            url,
            headers={"User-Agent": "Aztec-Coinbase-Monitor/1.0"},
            timeout=30
        )
        response.raise_for_status()
        return response.json(), None
    except requests.Timeout as e:
        error_msg = f"Request timeout after 30s: {url}"
        logger.error(error_msg)
        return None, error_msg
    except requests.ConnectionError as e:
        error_msg = f"Connection error: {e}"
        logger.error(error_msg)
        return None, error_msg
    except requests.HTTPError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e}"
        logger.error(error_msg)
        return None, error_msg
    except requests.RequestException as e:
        error_msg = f"Request failed: {e}"
        logger.error(error_msg)
        return None, error_msg
    except json.JSONDecodeError as e:
        error_msg = f"JSON parse error: {e}"
        logger.error(error_msg)
        return None, error_msg


def load_sequencers() -> tuple[dict[str, Any] | None, str | None]:
    """
    Load the sequencers.json file.

    Returns:
        Tuple of (data, error_message). If successful, error_message is None.
    """
    if not SEQUENCERS_FILE.exists():
        error_msg = f"Sequencers file not found: {SEQUENCERS_FILE}"
        logger.error(error_msg)
        return None, error_msg

    try:
        with open(SEQUENCERS_FILE, "r") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse sequencers.json: {e}"
        logger.error(error_msg)
        return None, error_msg
    except IOError as e:
        error_msg = f"Failed to read sequencers.json: {e}"
        logger.error(error_msg)
        return None, error_msg


def save_sequencers(data: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Save the sequencers.json file.

    Returns:
        Tuple of (success, error_message). If successful, error_message is None.
    """
    try:
        with open(SEQUENCERS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Sequencers file saved: {SEQUENCERS_FILE}")
        return True, None
    except IOError as e:
        error_msg = f"Failed to save sequencers.json: {e}"
        logger.error(error_msg)
        return False, error_msg


def load_state() -> dict[str, Any]:
    """Load the monitor state file."""
    if not STATE_FILE.exists():
        return {"known_stakes": {}, "last_updated": None}

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"known_stakes": {}, "last_updated": None}


def save_state(state: dict[str, Any]) -> None:
    """Save the monitor state file."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        logger.error(f"Failed to save state file: {e}")


def save_mappings(mappings: list[dict[str, Any]]) -> None:
    """Save the coinbase mappings file for reference."""
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "provider_id": PROVIDER_ID,
        "mappings": mappings
    }
    try:
        with open(MAPPINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Mappings file saved: {MAPPINGS_FILE}")
    except IOError as e:
        logger.error(f"Failed to save mappings file: {e}")


def normalize_address(addr: str) -> str:
    """Normalize Ethereum address to lowercase for comparison."""
    return addr.lower() if addr else ""


def process_stakes(provider_data: dict[str, Any], state: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """
    Process stakes from API and identify new/changed mappings.

    Returns:
        Tuple of (all_mappings, new_or_changed_mappings)
    """
    stakes = provider_data.get("stakes", [])
    known_stakes = state.get("known_stakes", {})

    all_mappings = []
    new_or_changed = []

    for stake in stakes:
        attester_address = stake.get("attesterAddress", "")
        split_contract = stake.get("splitContractAddress", "")
        staked_amount = stake.get("stakedAmount", "0")

        if not attester_address or not split_contract:
            continue

        mapping = {
            "attester_address": attester_address,
            "split_contract": split_contract,
            "staked_amount": staked_amount,
            "staker_address": stake.get("stakerAddress", ""),
            "tx_hash": stake.get("txHash", ""),
            "block_number": stake.get("blockNumber", "")
        }
        all_mappings.append(mapping)

        # Check if this is new or changed
        key = normalize_address(attester_address)
        known_split = known_stakes.get(key, "")

        if normalize_address(known_split) != normalize_address(split_contract):
            new_or_changed.append(mapping)
            known_stakes[key] = split_contract

    state["known_stakes"] = known_stakes
    return all_mappings, new_or_changed


def update_sequencers_coinbase(mappings: list[dict[str, Any]]) -> tuple[int, list[dict], str | None]:
    """
    Update the coinbase addresses in sequencers.json.

    Returns:
        Tuple of (number_of_updates, list_of_changes, error_message)
    """
    sequencers_data, error = load_sequencers()
    if not sequencers_data:
        return 0, [], error

    # Build lookup map: attester_address -> split_contract
    mapping_lookup = {
        normalize_address(m["attester_address"]): m["split_contract"]
        for m in mappings
    }

    validators = sequencers_data.get("validators", [])
    updates = 0
    changes = []

    for validator in validators:
        current_coinbase = validator.get("coinbase", "")
        normalized_coinbase = normalize_address(current_coinbase)

        # Check if this coinbase (attester address) has a split contract mapping
        if normalized_coinbase in mapping_lookup:
            new_coinbase = mapping_lookup[normalized_coinbase]

            # Only update if different
            if normalize_address(new_coinbase) != normalized_coinbase:
                changes.append({
                    "attester": current_coinbase,
                    "old_coinbase": current_coinbase,
                    "new_coinbase": new_coinbase
                })
                validator["coinbase"] = new_coinbase
                updates += 1

    if updates > 0:
        success, error = save_sequencers(sequencers_data)
        if success:
            logger.info(f"Updated {updates} coinbase addresses in sequencers.json")
        else:
            return 0, [], error

    return updates, changes, None


def format_amount(amount_wei: str) -> str:
    """Format wei amount to human-readable AZTEC tokens."""
    try:
        amount = int(amount_wei) / 10**18
        return f"{amount:,.0f}"
    except (ValueError, TypeError):
        return amount_wei


def send_update_notification(changes: list[dict], provider_name: str, total_staked: str) -> None:
    """Send Slack notification about coinbase updates."""
    if not changes:
        return

    # Build message
    change_lines = []
    for change in changes:
        change_lines.append(
            f"• Attester: `{change['attester'][:10]}...{change['attester'][-8:]}`\n"
            f"  Split Contract: `{change['new_coinbase']}`"
        )

    message = (
        f"🔔 *Aztec Coinbase Update*\n\n"
        f"Provider: {provider_name} (ID: {PROVIDER_ID})\n"
        f"Total Staked: {format_amount(total_staked)} AZTEC\n\n"
        f"*{len(changes)} coinbase address(es) updated:*\n\n" +
        "\n\n".join(change_lines) +
        f"\n\n✅ `sequencers.json` has been automatically updated.\n"
        f"⚠️ *Restart your validator to apply changes.*"
    )

    send_slack_notification(message)


def send_new_delegation_notification(new_mappings: list[dict], provider_name: str) -> None:
    """Send Slack notification about new delegations detected."""
    if not new_mappings:
        return

    delegation_lines = []
    for mapping in new_mappings:
        delegation_lines.append(
            f"• Attester: `{mapping['attester_address'][:10]}...{mapping['attester_address'][-8:]}`\n"
            f"  Split Contract: `{mapping['split_contract']}`\n"
            f"  Staked: {format_amount(mapping['staked_amount'])} AZTEC"
        )

    message = (
        f"🆕 *New Aztec Delegation(s) Detected*\n\n"
        f"Provider: {provider_name} (ID: {PROVIDER_ID})\n\n"
        f"*{len(new_mappings)} new delegation(s):*\n\n" +
        "\n\n".join(delegation_lines)
    )

    send_slack_notification(message)


def run_check() -> bool:
    """
    Run a single check cycle.

    Returns:
        True if successful, False if there was an error.
    """
    logger.info(f"Running check for provider {PROVIDER_ID}")

    # Fetch provider data
    provider_data, error = fetch_provider_data()
    if not provider_data:
        send_error_alert("API Fetch Failed", error or "Unknown error")
        logger.warning("Could not fetch provider data, will retry next cycle")
        return False

    provider_name = provider_data.get("name", f"Provider {PROVIDER_ID}")
    total_staked = provider_data.get("totalStaked", "0")
    delegators = provider_data.get("delegators", 0)

    logger.info(
        f"Provider: {provider_name}, "
        f"Delegators: {delegators}, "
        f"Total Staked: {format_amount(total_staked)} AZTEC"
    )

    # Load state
    state = load_state()

    # Process stakes
    all_mappings, new_or_changed = process_stakes(provider_data, state)

    logger.info(f"Found {len(all_mappings)} total stakes, {len(new_or_changed)} new/changed")

    # Save mappings file for reference
    save_mappings(all_mappings)

    # If there are new/changed mappings, notify
    if new_or_changed:
        send_new_delegation_notification(new_or_changed, provider_name)

    # Update sequencers.json if we have mappings
    if all_mappings:
        updates, changes, error = update_sequencers_coinbase(all_mappings)

        if error:
            send_error_alert("File Operation Failed", error)
            return False

        if changes:
            logger.info(f"Made {updates} coinbase updates")
            send_update_notification(changes, provider_name, total_staked)
        else:
            logger.debug("No coinbase updates needed")

    # Save state
    save_state(state)

    logger.info("Check complete")
    return True


def main() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Aztec Coinbase Monitor starting")
    logger.info(f"Provider ID: {PROVIDER_ID}")
    logger.info(f"API URL: {STAKING_API_URL}")
    logger.info(f"Poll Interval: {MONITOR_POLL_INTERVAL}s")
    logger.info(f"Keystore Path: {KEYSTORE_PATH}")
    logger.info(f"Data Path: {DATA_PATH}")
    logger.info(f"Slack Notifications: {'Enabled' if SLACK_WEBHOOK_URL else 'Disabled'}")
    logger.info(f"Error Alert Threshold: {ERROR_ALERT_THRESHOLD} consecutive failures")
    logger.info(f"Error Alert Cooldown: {ERROR_ALERT_COOLDOWN}s")
    logger.info("=" * 60)

    # Verify keystore path exists
    if not Path(KEYSTORE_PATH).exists():
        logger.error(f"Keystore path does not exist: {KEYSTORE_PATH}")
        sys.exit(1)

    # Verify data path exists
    if not Path(DATA_PATH).exists():
        logger.error(f"Data path does not exist: {DATA_PATH}")
        sys.exit(1)

    # Run initial check
    success = run_check()
    if success:
        send_recovery_alert()

    # Main loop
    while True:
        logger.info(f"Sleeping for {MONITOR_POLL_INTERVAL} seconds...")
        time.sleep(MONITOR_POLL_INTERVAL)

        success = run_check()
        if success:
            send_recovery_alert()


if __name__ == "__main__":
    main()
