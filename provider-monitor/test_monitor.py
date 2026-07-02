#!/usr/bin/env python3
"""Unit tests for the Aztec Provider Monitor."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["PROVIDER_ID"] = "74"
os.environ["L1_RPC_URL"] = "https://rpc-one.example, https://rpc-two.example"
os.environ["NETWORK"] = "mainnet"
os.environ["LOG_LEVEL"] = "ERROR"

import monitor


class ProviderMonitorTests(unittest.TestCase):
    def test_parse_rpc_urls(self):
        self.assertEqual(
            monitor.parse_rpc_urls(" https://a.example,https://b.example, "),
            ["https://a.example", "https://b.example"],
        )

    def test_build_call_data(self):
        call_data = monitor.build_call_data("getProviderQueueLength(uint256)", 74)

        self.assertTrue(call_data.startswith("0x"))
        self.assertEqual(len(call_data), 10 + 64)
        self.assertTrue(call_data.endswith(f"{74:064x}"))

    def test_decode_uint256(self):
        raw = (250).to_bytes(32, byteorder="big")

        self.assertEqual(monitor.decode_uint256(raw), 250)

    def test_decode_uint256_rejects_short_result(self):
        with self.assertRaises(ValueError):
            monitor.decode_uint256(b"\x01")

    def test_fetch_provider_queue_length_tries_next_rpc(self):
        with patch.object(monitor, "call_queue_length") as call_queue_length:
            call_queue_length.side_effect = [RuntimeError("primary failed"), 250]

            value = monitor.fetch_provider_queue_length(
                ["https://rpc-one.example", "https://rpc-two.example"],
                monitor.PROVIDER_QUEUE_CONTRACT_ADDRESS,
                74,
            )

        self.assertEqual(value, 250)
        self.assertEqual(call_queue_length.call_count, 2)

    def test_run_check_sets_success_metrics(self):
        with patch.object(monitor, "fetch_provider_queue_length", return_value=250):
            self.assertTrue(monitor.run_check())

        self.assertEqual(
            monitor.PROVIDER_QUEUE_LENGTH.labels("74")._value.get(),
            250,
        )
        self.assertEqual(
            monitor.PROVIDER_QUEUE_UP.labels("74")._value.get(),
            1,
        )

    def test_run_check_sets_failure_metric(self):
        with patch.object(monitor, "fetch_provider_queue_length", side_effect=RuntimeError("boom")):
            self.assertFalse(monitor.run_check())

        self.assertEqual(
            monitor.PROVIDER_QUEUE_UP.labels("74")._value.get(),
            0,
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
