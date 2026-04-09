#!/usr/bin/env python3
"""
Aztec Slashing Monitor — Prometheus Exporter

Polls Aztec L1 contracts to detect slashing proposals targeting our validators.
Exposes Prometheus metrics for Grafana dashboards and alerting.

Based on the logic from sekuba/slashmon (slashveto.me).
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from eth_account import Account
from prometheus_client import Counter, Gauge, start_http_server
from web3 import Web3

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

L1_RPC_URL = os.getenv("L1_RPC_URL", "")
KEYSTORE_PATH = os.getenv("KEYSTORE_PATH", "/keystore")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "900"))
NETWORK = os.getenv("NETWORK", "mainnet").lower()
METRICS_PORT = int(os.getenv("METRICS_PORT", "9101"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Contract addresses per network
CONTRACTS = {
    "mainnet": {
        "tally": "0xa4a38fD0108C00983E75616b638Ff3321FD26958",
        "slasher": "0x64E6e9Bb9f1E33D319578B9f8a9C719Ca6D46eBb",
        "rollup": "0xAe2001f7e21d5EcABf6234E9FDd1E76F50F74962",
    },
    "testnet": {
        "tally": "0xcA49e32bc2926c3F2Ef67E1647Fa14a8ebf34065",
        "slasher": "0x89684502e6A5fD3f1e4B3C610429F6E2C181c6ba",
        "rollup": "0x66A41CB55F9a1e38A45A2Ac8685F12A61fBFab77",
    },
}

# ---------------------------------------------------------------------------
# ABIs (minimal — only the functions we call)
# ---------------------------------------------------------------------------

TALLY_ABI = json.loads("""[
    {"type":"function","name":"getCurrentRound","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"getRound","stateMutability":"view",
     "inputs":[{"name":"_round","type":"uint256"}],
     "outputs":[{"name":"isExecuted","type":"bool"},{"name":"voteCount","type":"uint256"}]},
    {"type":"function","name":"getSlashTargetCommittees","stateMutability":"nonpayable",
     "inputs":[{"name":"_round","type":"uint256"}],
     "outputs":[{"name":"committees","type":"address[][]"}]},
    {"type":"function","name":"getTally","stateMutability":"view",
     "inputs":[{"name":"_round","type":"uint256"},{"name":"_committees","type":"address[][]"}],
     "outputs":[{"name":"actions","type":"tuple[]","components":[
         {"name":"validator","type":"address"},{"name":"slashAmount","type":"uint256"}]}]},
    {"type":"function","name":"getPayloadAddress","stateMutability":"view",
     "inputs":[{"name":"_round","type":"uint256"},
               {"name":"_actions","type":"tuple[]","components":[
                   {"name":"validator","type":"address"},{"name":"slashAmount","type":"uint256"}]}],
     "outputs":[{"name":"","type":"address"}]},
    {"type":"function","name":"QUORUM","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"ROUND_SIZE","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"ROUND_SIZE_IN_EPOCHS","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"EXECUTION_DELAY_IN_ROUNDS","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"LIFETIME_IN_ROUNDS","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"SLASH_OFFSET_IN_ROUNDS","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]}
]""")

SLASHER_ABI = json.loads("""[
    {"type":"function","name":"isSlashingEnabled","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"bool"}]},
    {"type":"function","name":"slashingDisabledUntil","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"vetoedPayloads","stateMutability":"view",
     "inputs":[{"name":"payload","type":"address"}],
     "outputs":[{"name":"vetoed","type":"bool"}]}
]""")

ROLLUP_ABI = json.loads("""[
    {"type":"function","name":"getCurrentSlot","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"getCurrentEpoch","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"getSlotDuration","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"getEpochDuration","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]},
    {"type":"function","name":"getActiveAttesterCount","stateMutability":"view",
     "inputs":[],"outputs":[{"name":"","type":"uint256"}]}
]""")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

# Global slashing state
SLASHING_ENABLED = Gauge(
    "aztec_slashing_enabled",
    "Whether slashing is globally enabled (1=yes, 0=no)",
)
SLASHING_DISABLED_UNTIL = Gauge(
    "aztec_slashing_disabled_until_timestamp",
    "Unix timestamp when slashing halt ends (0 if enabled)",
)
CURRENT_ROUND = Gauge(
    "aztec_slashing_current_round",
    "Current slashing round number",
)
CURRENT_SLOT = Gauge(
    "aztec_slashing_current_slot",
    "Current Aztec slot number",
)
QUORUM_THRESHOLD = Gauge(
    "aztec_slashing_quorum_threshold",
    "Number of votes needed for quorum",
)
ACTIVE_ATTESTER_COUNT = Gauge(
    "aztec_slashing_active_attester_count",
    "Number of active attesters in the network",
)

# Per-round metrics
ROUND_VOTE_COUNT = Gauge(
    "aztec_slashing_round_vote_count",
    "Vote count for a slashing round",
    ["round"],
)
ROUND_HAS_QUORUM = Gauge(
    "aztec_slashing_round_has_quorum",
    "Whether a round has reached quorum (1=yes, 0=no)",
    ["round"],
)
ROUND_IS_EXECUTED = Gauge(
    "aztec_slashing_round_is_executed",
    "Whether a round has been executed (1=yes, 0=no)",
    ["round"],
)
ROUND_IS_VETOED = Gauge(
    "aztec_slashing_round_is_vetoed",
    "Whether a round has been vetoed (1=yes, 0=no)",
    ["round"],
)
ROUND_SECONDS_UNTIL_EXECUTABLE = Gauge(
    "aztec_slashing_round_seconds_until_executable",
    "Seconds until a round becomes executable",
    ["round"],
)
ROUND_SECONDS_UNTIL_EXPIRES = Gauge(
    "aztec_slashing_round_seconds_until_expires",
    "Seconds until a round expires",
    ["round"],
)
ROUND_STATUS = Gauge(
    "aztec_slashing_round_status",
    "Round status encoded as int: 0=expired, 1=voting, 2=quorum-reached, 3=in-veto-window, 4=executable, 5=executed",
    ["round"],
)

# Our-validator-specific metrics
OUR_VALIDATOR_TARGETED = Gauge(
    "aztec_slashing_our_validator_targeted",
    "Whether our validator is targeted in a round (1=yes, 0=no)",
    ["round", "validator"],
)
OUR_VALIDATOR_SLASH_AMOUNT = Gauge(
    "aztec_slashing_our_validator_slash_amount",
    "Slash amount targeting our validator in a round (wei)",
    ["round", "validator"],
)
OUR_VALIDATOR_TARGETED_TOTAL = Gauge(
    "aztec_slashing_our_validator_targeted_rounds_total",
    "Total number of active rounds targeting any of our validators",
)

# Poll health
POLL_ERRORS = Counter(
    "aztec_slashing_poll_errors_total",
    "Total number of poll errors",
)
POLL_SUCCESS = Counter(
    "aztec_slashing_poll_success_total",
    "Total number of successful polls",
)
LAST_POLL_TIMESTAMP = Gauge(
    "aztec_slashing_last_poll_timestamp",
    "Unix timestamp of the last successful poll",
)

# Status string to int mapping for Prometheus
STATUS_MAP = {
    "expired": 0,
    "voting": 1,
    "quorum-reached": 2,
    "in-veto-window": 3,
    "executable": 4,
    "executed": 5,
}

# ---------------------------------------------------------------------------
# Keystore reader
# ---------------------------------------------------------------------------


def load_validator_addresses(keystore_path: str) -> list[str]:
    """
    Read attester addresses from the keystore.

    Tries sequencers.json first (has validator entries with attester keys),
    falls back to sequencer.json.
    """
    addresses = []

    for filename in ("sequencers.json", "sequencer.json"):
        filepath = Path(keystore_path) / filename
        if not filepath.exists():
            continue

        try:
            with open(filepath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to read %s: %s", filepath, e)
            continue

        validators = data.get("validators", [])
        for v in validators:
            attester = v.get("attester", {})

            # attester.eth is a private key — derive the public address
            eth_key = attester.get("eth", "") if isinstance(attester, dict) else ""
            if eth_key:
                try:
                    account = Account.from_key(eth_key)
                    addresses.append(account.address.lower())
                    logger.info("Loaded attester address %s from %s", account.address, filename)
                except Exception as e:
                    logger.warning("Failed to derive address from attester key in %s: %s", filename, e)

        if addresses:
            break

    if not addresses:
        logger.warning("No validator addresses found in keystore at %s", keystore_path)

    return addresses


# ---------------------------------------------------------------------------
# Slashing monitor
# ---------------------------------------------------------------------------


class SlashingMonitor:
    def __init__(self, w3: Web3, network: str, our_addresses: list[str]):
        addrs = CONTRACTS.get(network, CONTRACTS["mainnet"])
        self.w3 = w3
        self.our_addresses = set(our_addresses)

        self.tally = w3.eth.contract(
            address=Web3.to_checksum_address(addrs["tally"]),
            abi=TALLY_ABI,
        )
        self.slasher = w3.eth.contract(
            address=Web3.to_checksum_address(addrs["slasher"]),
            abi=SLASHER_ABI,
        )
        self.rollup = w3.eth.contract(
            address=Web3.to_checksum_address(addrs["rollup"]),
            abi=ROLLUP_ABI,
        )

        # Contract constants (loaded once)
        self.quorum: int = 0
        self.round_size: int = 0
        self.execution_delay: int = 0
        self.lifetime: int = 0
        self.slash_offset: int = 0
        self.slot_duration: int = 0

        # Track which round labels we've set so we can clean up stale ones
        self._active_round_labels: set[str] = set()
        self._active_validator_labels: set[tuple[str, str]] = set()

    def load_constants(self):
        """Load immutable contract parameters (called once at startup)."""
        self.quorum = self.tally.functions.QUORUM().call()
        self.round_size = self.tally.functions.ROUND_SIZE().call()
        self.execution_delay = self.tally.functions.EXECUTION_DELAY_IN_ROUNDS().call()
        self.lifetime = self.tally.functions.LIFETIME_IN_ROUNDS().call()
        self.slash_offset = self.tally.functions.SLASH_OFFSET_IN_ROUNDS().call()
        self.slot_duration = self.rollup.functions.getSlotDuration().call()

        QUORUM_THRESHOLD.set(self.quorum)

        logger.info(
            "Contract constants: quorum=%d, round_size=%d, "
            "execution_delay=%d, lifetime=%d, slash_offset=%d, slot_duration=%ds",
            self.quorum, self.round_size,
            self.execution_delay, self.lifetime, self.slash_offset, self.slot_duration,
        )

    def build_rounds_to_check(self, current_round: int) -> list[int]:
        """
        Build the list of rounds to check, matching slashmon's logic:
        - Current round back through execution delay (early warning / voting)
        - Executable window: from (current - lifetime) to (current - execution_delay)
        """
        rounds = set()

        # Early warning window: rounds still in voting phase
        early_start = current_round - self.execution_delay + 1
        for r in range(max(0, early_start), current_round + 1):
            rounds.add(r)

        # Executable window: rounds past execution delay but within lifetime
        exec_start = current_round - self.lifetime
        exec_end = current_round - self.execution_delay
        for r in range(max(0, exec_start), exec_end + 1):
            rounds.add(r)

        return sorted(rounds)

    def calculate_executable_slot(self, round_num: int) -> int:
        return (round_num + 1 + self.execution_delay) * self.round_size

    def calculate_expiry_slot(self, round_num: int) -> int:
        return (round_num + 1 + self.lifetime) * self.round_size

    def calculate_round_status(
        self,
        round_num: int,
        current_round: int,
        current_slot: int,
        is_executed: bool,
        has_quorum: bool,
    ) -> str:
        if is_executed:
            return "executed"

        if current_round - round_num > self.lifetime:
            return "expired"

        if has_quorum:
            executable_slot = self.calculate_executable_slot(round_num)

            # In veto window: first executable round and past executable slot
            if (current_round - round_num == self.execution_delay
                    and current_slot >= executable_slot):
                return "in-veto-window"

            # Executable: past execution delay and within lifetime
            if (current_round - round_num > self.execution_delay
                    and current_round - round_num <= self.lifetime
                    and current_slot >= executable_slot):
                return "executable"

            return "quorum-reached"

        return "expired" if not has_quorum else "voting"

    def seconds_until_slot(self, target_slot: int, current_slot: int) -> int:
        if target_slot <= current_slot:
            return 0
        return (target_slot - current_slot) * self.slot_duration

    def poll(self):
        """Run a single poll cycle."""
        # Get current chain state
        current_round = self.tally.functions.getCurrentRound().call()
        current_slot = self.rollup.functions.getCurrentSlot().call()
        is_enabled = self.slasher.functions.isSlashingEnabled().call()
        disabled_until = self.slasher.functions.slashingDisabledUntil().call()
        active_attesters = self.rollup.functions.getActiveAttesterCount().call()

        # Update global metrics
        CURRENT_ROUND.set(current_round)
        CURRENT_SLOT.set(current_slot)
        SLASHING_ENABLED.set(1 if is_enabled else 0)
        SLASHING_DISABLED_UNTIL.set(disabled_until)
        ACTIVE_ATTESTER_COUNT.set(active_attesters)

        logger.info(
            "State: round=%d, slot=%d, slashing_enabled=%s, active_attesters=%d",
            current_round, current_slot, is_enabled, active_attesters,
        )

        rounds_to_check = self.build_rounds_to_check(current_round)
        logger.info("Checking %d rounds: %s", len(rounds_to_check), rounds_to_check)

        new_round_labels: set[str] = set()
        new_validator_labels: set[tuple[str, str]] = set()
        our_targeted_count = 0

        for round_num in rounds_to_check:
            round_label = str(round_num)
            new_round_labels.add(round_label)

            try:
                is_executed, vote_count = self.tally.functions.getRound(round_num).call()
            except Exception as e:
                logger.warning("Failed to get round %d: %s", round_num, e)
                continue

            has_quorum = vote_count >= self.quorum
            status = self.calculate_round_status(
                round_num, current_round, current_slot, is_executed, has_quorum,
            )

            executable_slot = self.calculate_executable_slot(round_num)
            expiry_slot = self.calculate_expiry_slot(round_num)

            # Set per-round metrics
            ROUND_VOTE_COUNT.labels(round=round_label).set(vote_count)
            ROUND_HAS_QUORUM.labels(round=round_label).set(1 if has_quorum else 0)
            ROUND_IS_EXECUTED.labels(round=round_label).set(1 if is_executed else 0)
            ROUND_STATUS.labels(round=round_label).set(STATUS_MAP.get(status, 0))
            ROUND_SECONDS_UNTIL_EXECUTABLE.labels(round=round_label).set(
                self.seconds_until_slot(executable_slot, current_slot),
            )
            ROUND_SECONDS_UNTIL_EXPIRES.labels(round=round_label).set(
                self.seconds_until_slot(expiry_slot, current_slot),
            )

            if vote_count > 0:
                logger.info(
                    "Round %d: votes=%d, quorum=%s, status=%s",
                    round_num, vote_count, has_quorum, status,
                )

            # Load details for rounds with quorum or executed
            is_vetoed = False
            if has_quorum or is_executed:
                try:
                    is_vetoed = self._check_round_details(
                        round_num, current_slot, new_validator_labels,
                    )
                except Exception as e:
                    logger.warning("Failed to load details for round %d: %s", round_num, e)

            ROUND_IS_VETOED.labels(round=round_label).set(1 if is_vetoed else 0)

        # Count rounds targeting our validators
        targeted_rounds = set()
        for round_label, _ in new_validator_labels:
            targeted_rounds.add(round_label)
        our_targeted_count = len(targeted_rounds)
        OUR_VALIDATOR_TARGETED_TOTAL.set(our_targeted_count)

        if our_targeted_count > 0:
            logger.warning(
                "OUR VALIDATOR IS TARGETED in %d round(s)!", our_targeted_count,
            )

        # Clean up stale round labels
        stale_rounds = self._active_round_labels - new_round_labels
        for round_label in stale_rounds:
            ROUND_VOTE_COUNT.remove(round_label)
            ROUND_HAS_QUORUM.remove(round_label)
            ROUND_IS_EXECUTED.remove(round_label)
            ROUND_IS_VETOED.remove(round_label)
            ROUND_STATUS.remove(round_label)
            ROUND_SECONDS_UNTIL_EXECUTABLE.remove(round_label)
            ROUND_SECONDS_UNTIL_EXPIRES.remove(round_label)

        stale_validators = self._active_validator_labels - new_validator_labels
        for round_label, validator in stale_validators:
            OUR_VALIDATOR_TARGETED.remove(round_label, validator)
            OUR_VALIDATOR_SLASH_AMOUNT.remove(round_label, validator)

        self._active_round_labels = new_round_labels
        self._active_validator_labels = new_validator_labels

    def _check_round_details(
        self,
        round_num: int,
        current_slot: int,
        new_validator_labels: set[tuple[str, str]],
    ) -> bool:
        """
        Load detailed round info: committees, tally, payload, veto status.
        Returns True if the round is vetoed.
        """
        round_label = str(round_num)

        committees = self.tally.functions.getSlashTargetCommittees(round_num).call()
        if not committees:
            return False

        actions = self.tally.functions.getTally(round_num, committees).call()
        if not actions:
            return False

        # Check veto status
        is_vetoed = False
        try:
            payload_addr = self.tally.functions.getPayloadAddress(
                round_num, actions,
            ).call()
            is_vetoed = self.slasher.functions.vetoedPayloads(payload_addr).call()
        except Exception as e:
            logger.warning("Failed to check veto status for round %d: %s", round_num, e)

        # Check if any of our validators are targeted
        for action in actions:
            validator_addr = action[0].lower() if isinstance(action, (list, tuple)) else action["validator"].lower()
            slash_amount = action[1] if isinstance(action, (list, tuple)) else action["slashAmount"]

            if validator_addr in self.our_addresses:
                new_validator_labels.add((round_label, validator_addr))
                OUR_VALIDATOR_TARGETED.labels(
                    round=round_label, validator=validator_addr,
                ).set(1)
                OUR_VALIDATOR_SLASH_AMOUNT.labels(
                    round=round_label, validator=validator_addr,
                ).set(slash_amount)

                logger.warning(
                    "SLASH TARGET: round=%d, validator=%s, amount=%d wei",
                    round_num, validator_addr, slash_amount,
                )

        return is_vetoed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    logger.info("=" * 60)
    logger.info("Aztec Slashing Monitor starting")
    logger.info("Network: %s", NETWORK)
    logger.info("Poll interval: %ds", POLL_INTERVAL)
    logger.info("Metrics port: %d", METRICS_PORT)
    logger.info("Keystore path: %s", KEYSTORE_PATH)
    logger.info("=" * 60)

    if not L1_RPC_URL:
        logger.error("L1_RPC_URL is required")
        sys.exit(1)

    # Use the first RPC URL if comma-separated
    rpc_url = L1_RPC_URL.split(",")[0].strip()
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        logger.error("Failed to connect to L1 RPC at %s", rpc_url)
        sys.exit(1)

    logger.info("Connected to L1 RPC (chain_id=%d)", w3.eth.chain_id)

    # Load our validator addresses from keystore
    our_addresses = load_validator_addresses(KEYSTORE_PATH)
    logger.info("Monitoring %d validator address(es): %s", len(our_addresses), our_addresses)

    # Initialize monitor
    monitor = SlashingMonitor(w3, NETWORK, our_addresses)

    logger.info("Loading contract constants...")
    monitor.load_constants()

    # Start Prometheus HTTP server
    start_http_server(METRICS_PORT)
    logger.info("Prometheus metrics server started on :%d", METRICS_PORT)

    # Initial poll
    try:
        monitor.poll()
        POLL_SUCCESS.inc()
        LAST_POLL_TIMESTAMP.set(time.time())
    except Exception as e:
        logger.error("Initial poll failed: %s", e)
        POLL_ERRORS.inc()

    # Main loop
    while True:
        logger.info("Sleeping for %ds...", POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)

        try:
            monitor.poll()
            POLL_SUCCESS.inc()
            LAST_POLL_TIMESTAMP.set(time.time())
        except Exception as e:
            logger.error("Poll failed: %s", e)
            POLL_ERRORS.inc()


if __name__ == "__main__":
    main()
