#!/usr/bin/env python3
"""Unit tests for the Aztec Provider Monitor."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_KEYSTORE_DIR = tempfile.mkdtemp()
TEST_DATA_DIR = tempfile.mkdtemp()

os.environ["KEYSTORE_PATH"] = TEST_KEYSTORE_DIR
os.environ["DATA_PATH"] = TEST_DATA_DIR
os.environ["PROVIDER_ID"] = "123"
os.environ["STAKING_API_URL"] = "https://example.com/api"
os.environ["L1_RPC_URL"] = "https://rpc-one.example, https://rpc-two.example"
os.environ["NETWORK"] = "mainnet"
os.environ["SLACK_WEBHOOK_URL"] = ""
os.environ["LOG_LEVEL"] = "ERROR"

sys.path.insert(0, str(Path(__file__).resolve().parent))

import monitor

MOCK_PROVIDER_DATA = {
    "id": 123,
    "name": "TestProvider",
    "totalStaked": "1600000000000000000000000",
    "delegators": 8,
    "stakes": [
        {
            "attesterAddress": "0x1111111111111111111111111111111111111111",
            "splitContractAddress": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "stakedAmount": "200000000000000000000000",
            "stakerAddress": "0xDelegator1",
            "txHash": "0xTx1",
            "blockNumber": "1000",
        },
        {
            "attesterAddress": "0x2222222222222222222222222222222222222222",
            "splitContractAddress": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            "stakedAmount": "200000000000000000000000",
            "stakerAddress": "0xDelegator2",
            "txHash": "0xTx2",
            "blockNumber": "1001",
        },
        {
            "attesterAddress": "0x3333333333333333333333333333333333333333",
            "splitContractAddress": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
            "stakedAmount": "200000000000000000000000",
            "stakerAddress": "0xDelegator3",
            "txHash": "0xTx3",
            "blockNumber": "1002",
        },
    ],
}

MOCK_SEQUENCERS = {
    "schemaVersion": 1,
    "validators": [
        {
            "attester": {"eth": "0xAttesterKey1", "bls": "0xBLSKey1"},
            "publisher": "0xPublisher1",
            "feeRecipient": "0x0000000000000000000000000000000000000000",
            "coinbase": "0x1111111111111111111111111111111111111111",
        },
        {
            "attester": {"eth": "0xAttesterKey2", "bls": "0xBLSKey2"},
            "publisher": "0xPublisher2",
            "feeRecipient": "0x0000000000000000000000000000000000000000",
            "coinbase": "0x2222222222222222222222222222222222222222",
        },
        {
            "attester": {"eth": "0xAttesterKey3", "bls": "0xBLSKey3"},
            "publisher": "0xPublisher3",
            "feeRecipient": "0x0000000000000000000000000000000000000000",
            "coinbase": "0x4444444444444444444444444444444444444444",
        },
    ],
}


class ProviderMonitorTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_KEYSTORE_DIR)
        shutil.rmtree(TEST_DATA_DIR)

    def setUp(self):
        sequencers_file = Path(TEST_KEYSTORE_DIR) / "sequencers.json"
        with open(sequencers_file, "w") as file_handle:
            json.dump(MOCK_SEQUENCERS, file_handle, indent=2)

        for path in (monitor.STATE_FILE, monitor.MAPPINGS_FILE):
            if path.exists():
                path.unlink()

        monitor.error_state = {
            "consecutive_failures": 0,
            "last_error_alert_time": 0,
            "last_error_type": None,
            "was_in_error_state": False,
        }

    def test_mainnet_default_uses_staking_registry(self):
        self.assertEqual(
            monitor.PROVIDER_QUEUE_CONTRACT_ADDRESS,
            "0x042dF8f42790d6943F41C25C2132400fd727f452",
        )

    def test_normalize_address(self):
        self.assertEqual(monitor.normalize_address("0xABCD"), "0xabcd")
        self.assertEqual(monitor.normalize_address("0xabcd"), "0xabcd")
        self.assertEqual(monitor.normalize_address(""), "")
        self.assertEqual(monitor.normalize_address(None), "")

    def test_format_amount(self):
        self.assertEqual(monitor.format_amount("200000000000000000000000"), "200,000")
        self.assertEqual(monitor.format_amount("1600000000000000000000000"), "1,600,000")
        self.assertEqual(monitor.format_amount("invalid"), "invalid")

    def test_process_stakes_tracks_new_and_changed_mappings(self):
        state = {"known_stakes": {}, "last_updated": None}
        all_mappings, new_or_changed = monitor.process_stakes(MOCK_PROVIDER_DATA, state)

        self.assertEqual(len(all_mappings), 3)
        self.assertEqual(len(new_or_changed), 3)
        self.assertEqual(all_mappings[0]["previous_split_contract"], "")

        _, new_or_changed_again = monitor.process_stakes(MOCK_PROVIDER_DATA, state)
        self.assertEqual(len(new_or_changed_again), 0)
        self.assertEqual(state["known_stakes"]["0x1111111111111111111111111111111111111111"], "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

    def test_update_sequencers_coinbase(self):
        mappings = [
            {
                "attester_address": "0x1111111111111111111111111111111111111111",
                "split_contract": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
            {
                "attester_address": "0x2222222222222222222222222222222222222222",
                "split_contract": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            },
            {
                "attester_address": "0x3333333333333333333333333333333333333333",
                "split_contract": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
            },
        ]

        updates, changes, error = monitor.update_sequencers_coinbase(mappings)

        self.assertIsNone(error)
        self.assertEqual(updates, 2)
        self.assertEqual(len(changes), 2)

        with open(Path(TEST_KEYSTORE_DIR) / "sequencers.json", "r") as file_handle:
            updated_data = json.load(file_handle)

        validators = updated_data["validators"]
        self.assertEqual(validators[0]["coinbase"], "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        self.assertEqual(validators[1]["coinbase"], "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB")
        self.assertEqual(validators[2]["coinbase"], "0x4444444444444444444444444444444444444444")

    def test_update_sequencers_coinbase_updates_changed_split_contract(self):
        sequencers = MOCK_SEQUENCERS.copy()
        sequencers["validators"] = [validator.copy() for validator in MOCK_SEQUENCERS["validators"]]
        sequencers["validators"][0]["coinbase"] = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

        with open(Path(TEST_KEYSTORE_DIR) / "sequencers.json", "w") as file_handle:
            json.dump(sequencers, file_handle, indent=2)

        mappings = [
            {
                "attester_address": "0x1111111111111111111111111111111111111111",
                "split_contract": "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
                "previous_split_contract": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
        ]

        updates, changes, error = monitor.update_sequencers_coinbase(mappings)

        self.assertIsNone(error)
        self.assertEqual(updates, 1)
        self.assertEqual(changes[0]["attester"], "0x1111111111111111111111111111111111111111")
        self.assertEqual(changes[0]["old_coinbase"], "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        self.assertEqual(changes[0]["new_coinbase"], "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD")

        with open(Path(TEST_KEYSTORE_DIR) / "sequencers.json", "r") as file_handle:
            updated_data = json.load(file_handle)

        self.assertEqual(
            updated_data["validators"][0]["coinbase"],
            "0xDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
        )

    def test_state_persistence(self):
        test_state = {
            "known_stakes": {"0xtest": "0xsplit"},
            "last_updated": None,
        }
        monitor.save_state(test_state)

        loaded_state = monitor.load_state()

        self.assertIn("0xtest", loaded_state["known_stakes"])
        self.assertEqual(loaded_state["known_stakes"]["0xtest"], "0xsplit")
        self.assertIsNotNone(loaded_state["last_updated"])

    def test_run_coinbase_check_with_mock_provider_data(self):
        with patch.object(monitor, "fetch_provider_data", return_value=(MOCK_PROVIDER_DATA, None)):
            self.assertTrue(monitor.run_coinbase_check())

        self.assertTrue(monitor.STATE_FILE.exists())
        self.assertTrue(monitor.MAPPINGS_FILE.exists())
        self.assertEqual(monitor.COINBASE_UPDATE_UP.labels("123")._value.get(), 1)

        with open(monitor.MAPPINGS_FILE, "r") as file_handle:
            mappings_data = json.load(file_handle)

        self.assertEqual(len(mappings_data["mappings"]), 3)

    def test_run_coinbase_check_api_error(self):
        with patch.object(monitor, "fetch_provider_data", return_value=(None, "Connection timeout")):
            self.assertFalse(monitor.run_coinbase_check())

        self.assertEqual(monitor.error_state["consecutive_failures"], 1)
        self.assertEqual(monitor.COINBASE_UPDATE_UP.labels("123")._value.get(), 0)

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

    def test_run_provider_queue_check_sets_success_metrics(self):
        with patch.object(monitor, "fetch_provider_queue_length", return_value=250):
            self.assertTrue(monitor.run_provider_queue_check())

        self.assertEqual(
            monitor.PROVIDER_QUEUE_LENGTH.labels("123")._value.get(),
            250,
        )
        self.assertEqual(
            monitor.PROVIDER_QUEUE_UP.labels("123")._value.get(),
            1,
        )

    def test_run_provider_queue_check_sets_failure_metric(self):
        with patch.object(
            monitor,
            "fetch_provider_queue_length",
            side_effect=RuntimeError("boom"),
        ):
            self.assertFalse(monitor.run_provider_queue_check())

        self.assertEqual(
            monitor.PROVIDER_QUEUE_UP.labels("123")._value.get(),
            0,
        )


if __name__ == "__main__":
    sys.exit(unittest.main())
