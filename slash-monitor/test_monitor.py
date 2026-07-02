#!/usr/bin/env python3
"""Unit tests for the Aztec slash monitor."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from eth_account import Account
from web3 import Web3

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["L1_RPC_URL"] = "https://rpc.example"
os.environ["LOG_LEVEL"] = "ERROR"

import monitor


class SlashingMonitorTests(unittest.TestCase):
    def setUp(self):
        self.slashing_monitor = monitor.SlashingMonitor.__new__(monitor.SlashingMonitor)
        self.slashing_monitor.execution_delay = 2
        self.slashing_monitor.lifetime = 5
        self.slashing_monitor.round_size = 100
        self.slashing_monitor.slot_duration = 12

    def test_load_validator_addresses_from_sequencers_json(self):
        account = Account.create()

        with tempfile.TemporaryDirectory() as tmp_dir:
            keystore_file = Path(tmp_dir) / "sequencers.json"
            keystore_file.write_text(
                json.dumps(
                    {
                        "validators": [
                            {
                                "attester": {
                                    "eth": Web3.to_hex(account.key),
                                    "bls": "0x00",
                                },
                            },
                        ],
                    },
                ),
            )

            addresses = monitor.load_validator_addresses(tmp_dir)

        self.assertEqual(addresses, [account.address.lower()])

    def test_build_rounds_to_check_covers_voting_and_executable_windows(self):
        self.slashing_monitor.execution_delay = 2
        self.slashing_monitor.lifetime = 5

        self.assertEqual(
            self.slashing_monitor.build_rounds_to_check(current_round=10),
            [5, 6, 7, 8, 9, 10],
        )

    def test_calculate_round_status_voting_without_quorum(self):
        self.assertEqual(
            self.slashing_monitor.calculate_round_status(
                round_num=9,
                current_round=10,
                current_slot=1000,
                is_executed=False,
                has_quorum=False,
            ),
            "voting",
        )

    def test_calculate_round_status_expired_without_quorum(self):
        self.assertEqual(
            self.slashing_monitor.calculate_round_status(
                round_num=7,
                current_round=10,
                current_slot=1000,
                is_executed=False,
                has_quorum=False,
            ),
            "expired",
        )

    def test_calculate_round_status_executable_with_quorum(self):
        self.assertEqual(
            self.slashing_monitor.calculate_round_status(
                round_num=7,
                current_round=10,
                current_slot=1200,
                is_executed=False,
                has_quorum=True,
            ),
            "executable",
        )

    def test_seconds_until_slot(self):
        self.assertEqual(
            self.slashing_monitor.seconds_until_slot(target_slot=110, current_slot=100),
            120,
        )
        self.assertEqual(
            self.slashing_monitor.seconds_until_slot(target_slot=100, current_slot=100),
            0,
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
