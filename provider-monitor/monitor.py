#!/usr/bin/env python3
"""
Aztec Provider Monitor

Maintains provider coinbase address mappings in sequencers.json and exposes
provider-level Prometheus metrics. Grafana owns metric alert thresholds and
routing; Slack notifications remain for coinbase updater events.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from prometheus_client import Counter, Gauge, start_http_server
from web3 import Web3

PROVIDER_ID = os.getenv("PROVIDER_ID", "")
STAKING_API_URL = os.getenv("STAKING_API_URL", "")
L1_RPC_URL = os.getenv("L1_RPC_URL", "")
NETWORK = os.getenv("NETWORK", "mainnet").lower()
MONITOR_POLL_INTERVAL = int(os.getenv("MONITOR_POLL_INTERVAL", "10800"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9102"))
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
KEYSTORE_PATH = os.getenv("KEYSTORE_PATH", "/keystore")
DATA_PATH = os.getenv("DATA_PATH", "/data")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
RPC_TIMEOUT = int(os.getenv("RPC_TIMEOUT", "30"))

ERROR_ALERT_THRESHOLD = int(os.getenv("ERROR_ALERT_THRESHOLD", "3"))
ERROR_ALERT_COOLDOWN = int(os.getenv("ERROR_ALERT_COOLDOWN", "3600"))

SEQUENCERS_FILE = Path(KEYSTORE_PATH) / "sequencers.json"
STATE_FILE = Path(DATA_PATH) / "coinbase-monitor-state.json"
MAPPINGS_FILE = Path(DATA_PATH) / "coinbase-mappings.json"

CONTRACTS = {
    "mainnet": {
        "staking_registry": "0x042dF8f42790d6943F41C25C2132400fd727f452",
    },
}

PROVIDER_QUEUE_CONTRACT_ADDRESS = os.getenv(
    "PROVIDER_QUEUE_CONTRACT_ADDRESS",
    CONTRACTS.get(NETWORK, {}).get("staking_registry", ""),
)

QUEUE_LENGTH_SIGNATURES = (
    "getProviderQueueLength(uint256)",
    "getProviderQueueLength(uint32)",
    "getProviderQueueLength(uint16)",
    "getProviderQueueLength(uint8)",
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

error_state = {
    "consecutive_failures": 0,
    "last_error_alert_time": 0,
    "last_error_type": None,
    "was_in_error_state": False,
}

PROVIDER_QUEUE_LENGTH = Gauge(
    "aztec_provider_sequencer_key_queue_length",
    "Current available sequencer key queue length for an Aztec provider",
    ["provider_id"],
)
PROVIDER_QUEUE_LAST_SUCCESS = Gauge(
    "aztec_provider_queue_last_success_timestamp",
    "Unix timestamp of the last successful Aztec provider queue poll",
    ["provider_id"],
)
PROVIDER_QUEUE_POLL_ERRORS = Counter(
    "aztec_provider_queue_poll_errors_total",
    "Total number of Aztec provider queue poll errors",
    ["provider_id"],
)
PROVIDER_QUEUE_UP = Gauge(
    "aztec_provider_queue_up",
    "Whether the Aztec provider queue poll succeeded on the latest attempt (1=yes, 0=no)",
    ["provider_id"],
)
COINBASE_UPDATE_UP = Gauge(
    "aztec_provider_coinbase_update_up",
    "Whether the latest provider coinbase update check succeeded (1=yes, 0=no)",
    ["provider_id"],
)
COINBASE_UPDATE_LAST_SUCCESS = Gauge(
    "aztec_provider_coinbase_update_last_success_timestamp",
    "Unix timestamp of the last successful provider coinbase update check",
    ["provider_id"],
)
COINBASE_UPDATES_TOTAL = Counter(
    "aztec_provider_coinbase_updates_total",
    "Total number of provider coinbase address updates written to sequencers.json",
    ["provider_id"],
)
COINBASE_UPDATE_ERRORS = Counter(
    "aztec_provider_coinbase_update_errors_total",
    "Total number of provider coinbase updater errors",
    ["provider_id"],
)


def send_slack_notification(message: str, blocks: list[dict] | None = None) -> bool:
    """Send a notification to Slack webhook."""
    if not SLACK_WEBHOOK_URL:
        logger.debug("Slack webhook URL not configured, skipping notification")
        return False

    try:
        payload: dict[str, Any] = {"text": message}
        if blocks:
            payload["blocks"] = blocks

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Slack notification sent successfully")
        return True
    except requests.RequestException as exc:
        logger.error("Failed to send Slack notification: %s", exc)
        return False


def send_error_alert(error_type: str, error_message: str) -> None:
    """Send Slack alert for repeated coinbase updater errors."""
    error_state["consecutive_failures"] += 1
    error_state["last_error_type"] = error_type

    current_time = time.time()
    time_since_last_alert = current_time - error_state["last_error_alert_time"]
    should_alert = (
        error_state["consecutive_failures"] >= ERROR_ALERT_THRESHOLD
        and time_since_last_alert >= ERROR_ALERT_COOLDOWN
    )

    if not should_alert:
        return

    message = (
        "Aztec Provider Monitor Error\n\n"
        f"Provider ID: {PROVIDER_ID}\n"
        f"Error Type: {error_type}\n\n"
        f"{error_message}\n\n"
        f"Consecutive failures: {error_state['consecutive_failures']}\n"
        f"Will retry in {MONITOR_POLL_INTERVAL} seconds."
    )
    if send_slack_notification(message):
        error_state["last_error_alert_time"] = current_time
        error_state["was_in_error_state"] = True


def send_recovery_alert() -> None:
    """Send Slack alert when the coinbase updater recovers from errors."""
    if error_state["was_in_error_state"] and error_state["consecutive_failures"] > 0:
        failures = error_state["consecutive_failures"]
        message = (
            "Aztec Provider Monitor Recovered\n\n"
            f"Provider ID: {PROVIDER_ID}\n"
            f"Service resumed normal operation after {failures} failed attempt(s)."
        )
        send_slack_notification(message)

    error_state["consecutive_failures"] = 0
    error_state["last_error_type"] = None
    error_state["was_in_error_state"] = False


def fetch_provider_data() -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch provider data from the Staking Dashboard API.

    Returns a tuple of (data, error_message). If successful, error_message is None.
    """
    url = f"{STAKING_API_URL.rstrip('/')}/providers/{PROVIDER_ID}"

    try:
        logger.debug("Fetching provider data from %s", url)
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Origin": "https://staking.aztec.network",
                "Referer": "https://staking.aztec.network/",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json(), None
    except requests.Timeout:
        error_msg = f"Request timeout after 30s: {url}"
        logger.error(error_msg)
        return None, error_msg
    except requests.ConnectionError as exc:
        error_msg = f"Connection error: {exc}"
        logger.error(error_msg)
        return None, error_msg
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        error_msg = f"HTTP error {status_code}: {exc}"
        logger.error(error_msg)
        return None, error_msg
    except requests.RequestException as exc:
        error_msg = f"Request failed: {exc}"
        logger.error(error_msg)
        return None, error_msg
    except json.JSONDecodeError as exc:
        error_msg = f"JSON parse error: {exc}"
        logger.error(error_msg)
        return None, error_msg


def load_sequencers() -> tuple[dict[str, Any] | None, str | None]:
    """Load sequencers.json."""
    if not SEQUENCERS_FILE.exists():
        error_msg = f"Sequencers file not found: {SEQUENCERS_FILE}"
        logger.error(error_msg)
        return None, error_msg

    try:
        with open(SEQUENCERS_FILE, "r") as file_handle:
            return json.load(file_handle), None
    except json.JSONDecodeError as exc:
        error_msg = f"Failed to parse sequencers.json: {exc}"
        logger.error(error_msg)
        return None, error_msg
    except OSError as exc:
        error_msg = f"Failed to read sequencers.json: {exc}"
        logger.error(error_msg)
        return None, error_msg


def save_sequencers(data: dict[str, Any]) -> tuple[bool, str | None]:
    """Save sequencers.json."""
    try:
        with open(SEQUENCERS_FILE, "w") as file_handle:
            json.dump(data, file_handle, indent=2)
        logger.info("Sequencers file saved: %s", SEQUENCERS_FILE)
        return True, None
    except OSError as exc:
        error_msg = f"Failed to save sequencers.json: {exc}"
        logger.error(error_msg)
        return False, error_msg


def load_state() -> dict[str, Any]:
    """Load the coinbase updater state file."""
    if not STATE_FILE.exists():
        return {"known_stakes": {}, "last_updated": None}

    try:
        with open(STATE_FILE, "r") as file_handle:
            return json.load(file_handle)
    except (json.JSONDecodeError, OSError):
        return {"known_stakes": {}, "last_updated": None}


def save_state(state: dict[str, Any]) -> None:
    """Save the coinbase updater state file."""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(STATE_FILE, "w") as file_handle:
            json.dump(state, file_handle, indent=2)
    except OSError as exc:
        logger.error("Failed to save state file: %s", exc)


def save_mappings(mappings: list[dict[str, Any]]) -> None:
    """Save the coinbase mappings file for reference."""
    data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "provider_id": PROVIDER_ID,
        "mappings": mappings,
    }
    try:
        with open(MAPPINGS_FILE, "w") as file_handle:
            json.dump(data, file_handle, indent=2)
        logger.debug("Mappings file saved: %s", MAPPINGS_FILE)
    except OSError as exc:
        logger.error("Failed to save mappings file: %s", exc)


def normalize_address(addr: str | None) -> str:
    """Normalize Ethereum address to lowercase for comparison."""
    return addr.lower() if addr else ""


def process_stakes(
    provider_data: dict[str, Any],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Process stakes from API data and identify new or changed mappings.

    Returns a tuple of (all_mappings, new_or_changed_mappings).
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
            "previous_split_contract": known_stakes.get(normalize_address(attester_address), ""),
            "staked_amount": staked_amount,
            "staker_address": stake.get("stakerAddress", ""),
            "tx_hash": stake.get("txHash", ""),
            "block_number": stake.get("blockNumber", ""),
        }
        all_mappings.append(mapping)

        key = normalize_address(attester_address)
        known_split = known_stakes.get(key, "")

        if normalize_address(known_split) != normalize_address(split_contract):
            new_or_changed.append(mapping)
            known_stakes[key] = split_contract

    state["known_stakes"] = known_stakes
    return all_mappings, new_or_changed


def update_sequencers_coinbase(
    mappings: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]], str | None]:
    """
    Update coinbase addresses in sequencers.json.

    Returns a tuple of (number_of_updates, changes, error_message).
    """
    sequencers_data, error = load_sequencers()
    if not sequencers_data:
        return 0, [], error

    mapping_lookup = {}
    for mapping in mappings:
        mapping_lookup[normalize_address(mapping["attester_address"])] = mapping

        previous_split = normalize_address(mapping.get("previous_split_contract"))
        if previous_split:
            mapping_lookup[previous_split] = mapping

    validators = sequencers_data.get("validators", [])
    updates = 0
    changes = []

    for validator in validators:
        current_coinbase = validator.get("coinbase", "")
        normalized_coinbase = normalize_address(current_coinbase)

        matching_mapping = mapping_lookup.get(normalized_coinbase)
        if matching_mapping:
            new_coinbase = matching_mapping["split_contract"]

            if normalize_address(new_coinbase) != normalized_coinbase:
                changes.append(
                    {
                        "attester": matching_mapping["attester_address"],
                        "old_coinbase": current_coinbase,
                        "new_coinbase": new_coinbase,
                    }
                )
                validator["coinbase"] = new_coinbase
                updates += 1

    if updates > 0:
        success, error = save_sequencers(sequencers_data)
        if not success:
            return 0, [], error
        logger.info("Updated %s coinbase addresses in sequencers.json", updates)

    return updates, changes, None


def format_amount(amount_wei: str) -> str:
    """Format wei amount to human-readable AZTEC tokens."""
    try:
        amount = int(amount_wei) / 10**18
        return f"{amount:,.0f}"
    except (TypeError, ValueError):
        return amount_wei


def send_update_notification(
    changes: list[dict[str, Any]],
    provider_name: str,
    total_staked: str,
) -> None:
    """Send Slack notification about coinbase updates."""
    if not changes:
        return

    change_lines = []
    for change in changes:
        attester = change["attester"]
        change_lines.append(
            f"- Attester: `{attester[:10]}...{attester[-8:]}`\n"
            f"  Split Contract: `{change['new_coinbase']}`"
        )

    message = (
        "Aztec Coinbase Update\n\n"
        f"Provider: {provider_name} (ID: {PROVIDER_ID})\n"
        f"Total Staked: {format_amount(total_staked)} AZTEC\n\n"
        f"{len(changes)} coinbase address(es) updated:\n\n"
        + "\n\n".join(change_lines)
        + "\n\nsequencers.json has been automatically updated.\n"
        + "The validator will pick up the new coinbase via hot-reload."
    )

    send_slack_notification(message)


def send_new_delegation_notification(new_mappings: list[dict[str, Any]], provider_name: str) -> None:
    """Send Slack notification about new delegations detected."""
    if not new_mappings:
        return

    delegation_lines = []
    for mapping in new_mappings:
        attester = mapping["attester_address"]
        delegation_lines.append(
            f"- Attester: `{attester[:10]}...{attester[-8:]}`\n"
            f"  Split Contract: `{mapping['split_contract']}`\n"
            f"  Staked: {format_amount(mapping['staked_amount'])} AZTEC"
        )

    message = (
        "New Aztec Delegation(s) Detected\n\n"
        f"Provider: {provider_name} (ID: {PROVIDER_ID})\n\n"
        f"{len(new_mappings)} new delegation(s):\n\n"
        + "\n\n".join(delegation_lines)
    )

    send_slack_notification(message)


def run_coinbase_check() -> bool:
    """
    Run one coinbase updater cycle.

    Returns True if successful, False if there was an error.
    """
    logger.info("Running coinbase updater check for provider %s", PROVIDER_ID)

    provider_data, error = fetch_provider_data()
    if not provider_data:
        COINBASE_UPDATE_ERRORS.labels(PROVIDER_ID).inc()
        COINBASE_UPDATE_UP.labels(PROVIDER_ID).set(0)
        send_error_alert("API Fetch Failed", error or "Unknown error")
        logger.warning("Could not fetch provider data, will retry next cycle")
        return False

    provider_name = provider_data.get("name", f"Provider {PROVIDER_ID}")
    total_staked = provider_data.get("totalStaked", "0")
    delegators = provider_data.get("delegators", 0)

    logger.info(
        "Provider: %s, Delegators: %s, Total Staked: %s AZTEC",
        provider_name,
        delegators,
        format_amount(total_staked),
    )

    state = load_state()
    all_mappings, new_or_changed = process_stakes(provider_data, state)

    logger.info("Found %s total stakes, %s new/changed", len(all_mappings), len(new_or_changed))
    save_mappings(all_mappings)

    if new_or_changed:
        send_new_delegation_notification(new_or_changed, provider_name)

    if all_mappings:
        updates, changes, error = update_sequencers_coinbase(all_mappings)

        if error:
            COINBASE_UPDATE_ERRORS.labels(PROVIDER_ID).inc()
            COINBASE_UPDATE_UP.labels(PROVIDER_ID).set(0)
            send_error_alert("File Operation Failed", error)
            return False

        if changes:
            logger.info("Made %s coinbase updates", updates)
            COINBASE_UPDATES_TOTAL.labels(PROVIDER_ID).inc(updates)
            send_update_notification(changes, provider_name, total_staked)
        else:
            logger.debug("No coinbase updates needed")

    save_state(state)
    COINBASE_UPDATE_LAST_SUCCESS.labels(PROVIDER_ID).set(time.time())
    COINBASE_UPDATE_UP.labels(PROVIDER_ID).set(1)
    send_recovery_alert()

    logger.info("Coinbase updater check complete")
    return True


def parse_rpc_urls(raw_urls: str) -> list[str]:
    """Split comma-separated RPC URLs and drop empty entries."""
    return [url.strip() for url in raw_urls.split(",") if url.strip()]


def build_call_data(signature: str, provider_id: int) -> str:
    """Build calldata for a single-uint provider queue length call."""
    selector = Web3.keccak(text=signature)[:4].hex()
    argument = provider_id.to_bytes(32, byteorder="big").hex()
    return f"0x{selector}{argument}"


def decode_uint256(result: bytes) -> int:
    """Decode a uint256 eth_call result."""
    raw = bytes(result)
    if len(raw) < 32:
        raise ValueError(f"expected at least 32 bytes, got {len(raw)}")
    return int.from_bytes(raw[-32:], byteorder="big")


def call_queue_length(
    rpc_url: str,
    contract_address: str,
    provider_id: int,
    signatures: Iterable[str] = QUEUE_LENGTH_SIGNATURES,
) -> int:
    """Call getProviderQueueLength through one RPC URL."""
    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": RPC_TIMEOUT}))
    checksum_address = Web3.to_checksum_address(contract_address)
    last_error: Exception | None = None

    for signature in signatures:
        try:
            call_data = build_call_data(signature, provider_id)
            result = web3.eth.call({"to": checksum_address, "data": call_data})
            value = decode_uint256(result)
            logger.debug("Provider queue call succeeded with signature %s", signature)
            return value
        except Exception as exc:
            last_error = exc
            logger.debug("Provider queue call failed with signature %s: %s", signature, exc)

    raise RuntimeError(f"all provider queue call signatures failed: {last_error}")


def fetch_provider_queue_length(
    rpc_urls: Iterable[str],
    contract_address: str,
    provider_id: int,
) -> int:
    """Fetch provider queue length, trying configured RPC URLs in order."""
    last_error: Exception | None = None

    for rpc_url in rpc_urls:
        try:
            return call_queue_length(rpc_url, contract_address, provider_id)
        except Exception as exc:
            last_error = exc
            logger.warning("Provider queue poll failed via %s: %s", rpc_url, exc)

    raise RuntimeError(f"all configured L1 RPC URLs failed: {last_error}")


def run_provider_queue_check() -> bool:
    """Run one provider queue poll and update metrics."""
    provider_id = int(PROVIDER_ID)
    rpc_urls = parse_rpc_urls(L1_RPC_URL)

    try:
        queue_length = fetch_provider_queue_length(
            rpc_urls,
            PROVIDER_QUEUE_CONTRACT_ADDRESS,
            provider_id,
        )
        PROVIDER_QUEUE_LENGTH.labels(PROVIDER_ID).set(queue_length)
        PROVIDER_QUEUE_LAST_SUCCESS.labels(PROVIDER_ID).set(time.time())
        PROVIDER_QUEUE_UP.labels(PROVIDER_ID).set(1)
        logger.info("Provider %s queue length: %s", PROVIDER_ID, queue_length)
        return True
    except Exception as exc:
        PROVIDER_QUEUE_POLL_ERRORS.labels(PROVIDER_ID).inc()
        PROVIDER_QUEUE_UP.labels(PROVIDER_ID).set(0)
        logger.error("Provider queue poll failed: %s", exc)
        return False


def validate_config() -> None:
    """Validate required config before starting monitor loops."""
    if not PROVIDER_ID:
        logger.error("PROVIDER_ID is required")
        sys.exit(1)

    try:
        int(PROVIDER_ID)
    except ValueError:
        logger.error("PROVIDER_ID must be an integer, got %s", PROVIDER_ID)
        sys.exit(1)

    if not parse_rpc_urls(L1_RPC_URL):
        logger.error("L1_RPC_URL is required")
        sys.exit(1)

    if not PROVIDER_QUEUE_CONTRACT_ADDRESS:
        logger.error("No provider queue contract address configured for network %s", NETWORK)
        sys.exit(1)

    if not Web3.is_address(PROVIDER_QUEUE_CONTRACT_ADDRESS):
        logger.error("Invalid provider queue contract address: %s", PROVIDER_QUEUE_CONTRACT_ADDRESS)
        sys.exit(1)

    if not STAKING_API_URL:
        logger.warning("STAKING_API_URL is not configured; coinbase updater checks will fail")

    if not Path(KEYSTORE_PATH).exists():
        logger.warning("Keystore path does not exist: %s", KEYSTORE_PATH)

    if not Path(DATA_PATH).exists():
        logger.warning("Data path does not exist: %s", DATA_PATH)


def main() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Aztec Provider Monitor starting")
    logger.info("Provider ID: %s", PROVIDER_ID)
    logger.info("API URL: %s", STAKING_API_URL)
    logger.info("Network: %s", NETWORK)
    logger.info("Monitor Poll Interval: %ss", MONITOR_POLL_INTERVAL)
    logger.info("Metrics Port: %s", METRICS_PORT)
    logger.info("Provider Queue Contract: %s", PROVIDER_QUEUE_CONTRACT_ADDRESS)
    logger.info("Keystore Path: %s", KEYSTORE_PATH)
    logger.info("Data Path: %s", DATA_PATH)
    logger.info("Slack Notifications: %s", "Enabled" if SLACK_WEBHOOK_URL else "Disabled")
    logger.info("Error Alert Threshold: %s consecutive failures", ERROR_ALERT_THRESHOLD)
    logger.info("Error Alert Cooldown: %ss", ERROR_ALERT_COOLDOWN)
    logger.info("=" * 60)

    validate_config()

    COINBASE_UPDATE_UP.labels(PROVIDER_ID).set(0)
    PROVIDER_QUEUE_UP.labels(PROVIDER_ID).set(0)
    start_http_server(METRICS_PORT)
    logger.info("Prometheus metrics server started on :%s", METRICS_PORT)

    next_coinbase_check = 0.0
    next_provider_queue_check = 0.0

    while True:
        now = time.time()

        if now >= next_coinbase_check:
            run_coinbase_check()
            next_coinbase_check = time.time() + MONITOR_POLL_INTERVAL

        if now >= next_provider_queue_check:
            run_provider_queue_check()
            next_provider_queue_check = time.time() + MONITOR_POLL_INTERVAL

        next_check = min(next_coinbase_check, next_provider_queue_check)
        sleep_seconds = max(1, min(60, int(next_check - time.time())))
        logger.debug("Sleeping for %s seconds", sleep_seconds)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
