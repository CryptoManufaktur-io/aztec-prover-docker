#!/usr/bin/env python3
"""
Aztec Provider Monitor

Polls Aztec L1 contracts for provider-level state and exposes raw Prometheus
metrics. Alert thresholds and routing are owned by Grafana.
"""

import logging
import os
import sys
import time
from typing import Iterable

from prometheus_client import Counter, Gauge, start_http_server
from web3 import Web3

PROVIDER_ID = os.getenv("PROVIDER_ID", "")
L1_RPC_URL = os.getenv("L1_RPC_URL", "")
NETWORK = os.getenv("NETWORK", "mainnet").lower()
MONITOR_POLL_INTERVAL = int(os.getenv("MONITOR_POLL_INTERVAL", "300"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9102"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
RPC_TIMEOUT = int(os.getenv("RPC_TIMEOUT", "30"))

CONTRACTS = {
    "mainnet": {
        "rollup": "0xAe2001f7e21d5EcABf6234E9FDd1E76F50F74962",
    },
    "testnet": {
        "rollup": "0x66A41CB55F9a1e38A45A2Ac8685F12A61fBFab77",
    },
}

PROVIDER_QUEUE_CONTRACT_ADDRESS = os.getenv(
    "PROVIDER_QUEUE_CONTRACT_ADDRESS",
    CONTRACTS.get(NETWORK, {}).get("rollup", ""),
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


def run_check() -> bool:
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
    """Validate required config before serving metrics."""
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


def main() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Aztec Provider Monitor starting")
    logger.info("Provider ID: %s", PROVIDER_ID)
    logger.info("Network: %s", NETWORK)
    logger.info("Poll Interval: %ss", MONITOR_POLL_INTERVAL)
    logger.info("Metrics Port: %s", METRICS_PORT)
    logger.info("Provider Queue Contract: %s", PROVIDER_QUEUE_CONTRACT_ADDRESS)
    logger.info("=" * 60)

    validate_config()

    PROVIDER_QUEUE_UP.labels(PROVIDER_ID).set(0)
    start_http_server(METRICS_PORT)
    logger.info("Prometheus metrics server started on :%s", METRICS_PORT)

    while True:
        run_check()
        logger.info("Sleeping for %s seconds", MONITOR_POLL_INTERVAL)
        time.sleep(MONITOR_POLL_INTERVAL)


if __name__ == "__main__":
    main()
