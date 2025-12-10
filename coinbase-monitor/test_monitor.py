#!/usr/bin/env python3
"""
Test script for the Aztec Coinbase Monitor.
Uses mock data to verify the logic without making real API calls.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Set up test environment before importing monitor
TEST_KEYSTORE_DIR = tempfile.mkdtemp()
TEST_DATA_DIR = tempfile.mkdtemp()
os.environ["KEYSTORE_PATH"] = TEST_KEYSTORE_DIR
os.environ["DATA_PATH"] = TEST_DATA_DIR
os.environ["PROVIDER_ID"] = "123"
os.environ["STAKING_API_URL"] = "https://example.com/api"
os.environ["SLACK_WEBHOOK_URL"] = ""  # Disabled for testing
os.environ["LOG_LEVEL"] = "DEBUG"

# Now import the monitor module
import monitor

# Mock API response data
MOCK_PROVIDER_DATA = {
    "id": 123,
    "name": "TestProvider",
    "totalStaked": "1600000000000000000000000",  # 1.6M AZTEC
    "delegators": 8,
    "stakes": [
        {
            "attesterAddress": "0x1111111111111111111111111111111111111111",
            "splitContractAddress": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "stakedAmount": "200000000000000000000000",
            "stakerAddress": "0xDelegator1",
            "txHash": "0xTx1",
            "blockNumber": "1000"
        },
        {
            "attesterAddress": "0x2222222222222222222222222222222222222222",
            "splitContractAddress": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            "stakedAmount": "200000000000000000000000",
            "stakerAddress": "0xDelegator2",
            "txHash": "0xTx2",
            "blockNumber": "1001"
        },
        {
            "attesterAddress": "0x3333333333333333333333333333333333333333",
            "splitContractAddress": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
            "stakedAmount": "200000000000000000000000",
            "stakerAddress": "0xDelegator3",
            "txHash": "0xTx3",
            "blockNumber": "1002"
        }
    ]
}

# Mock sequencers.json - coinbase initially set to attester addresses
MOCK_SEQUENCERS = {
    "schemaVersion": 1,
    "validators": [
        {
            "attester": {"eth": "0xAttesterKey1", "bls": "0xBLSKey1"},
            "publisher": "0xPublisher1",
            "feeRecipient": "0x0000000000000000000000000000000000000000",
            "coinbase": "0x1111111111111111111111111111111111111111"  # Should be updated
        },
        {
            "attester": {"eth": "0xAttesterKey2", "bls": "0xBLSKey2"},
            "publisher": "0xPublisher2",
            "feeRecipient": "0x0000000000000000000000000000000000000000",
            "coinbase": "0x2222222222222222222222222222222222222222"  # Should be updated
        },
        {
            "attester": {"eth": "0xAttesterKey3", "bls": "0xBLSKey3"},
            "publisher": "0xPublisher3",
            "feeRecipient": "0x0000000000000000000000000000000000000000",
            "coinbase": "0x4444444444444444444444444444444444444444"  # No match - won't be updated
        }
    ]
}


def setup_test_files():
    """Create test files in the temp directories."""
    sequencers_file = Path(TEST_KEYSTORE_DIR) / "sequencers.json"
    with open(sequencers_file, "w") as f:
        json.dump(MOCK_SEQUENCERS, f, indent=2)
    print(f"✅ Created test sequencers.json at {sequencers_file}")
    return sequencers_file


def test_normalize_address():
    """Test address normalization."""
    print("\n📋 Test: normalize_address")

    assert monitor.normalize_address("0xABCD") == "0xabcd"
    assert monitor.normalize_address("0xabcd") == "0xabcd"
    assert monitor.normalize_address("") == ""
    assert monitor.normalize_address(None) == ""

    print("✅ Address normalization works correctly")


def test_format_amount():
    """Test amount formatting."""
    print("\n📋 Test: format_amount")

    assert monitor.format_amount("200000000000000000000000") == "200,000"
    assert monitor.format_amount("1600000000000000000000000") == "1,600,000"
    assert monitor.format_amount("invalid") == "invalid"

    print("✅ Amount formatting works correctly")


def test_process_stakes():
    """Test stake processing logic."""
    print("\n📋 Test: process_stakes")

    state = {"known_stakes": {}, "last_updated": None}
    all_mappings, new_or_changed = monitor.process_stakes(MOCK_PROVIDER_DATA, state)

    assert len(all_mappings) == 3, f"Expected 3 mappings, got {len(all_mappings)}"
    assert len(new_or_changed) == 3, f"Expected 3 new mappings, got {len(new_or_changed)}"

    print(f"  Found {len(all_mappings)} total stakes")
    print(f"  Found {len(new_or_changed)} new/changed stakes")

    # Second run - should have no new changes
    all_mappings2, new_or_changed2 = monitor.process_stakes(MOCK_PROVIDER_DATA, state)
    assert len(new_or_changed2) == 0, f"Expected 0 new mappings on second run, got {len(new_or_changed2)}"

    print("  Second run correctly detected 0 new stakes")
    print("✅ Stake processing works correctly")


def test_update_sequencers_coinbase():
    """Test sequencers.json update logic."""
    print("\n📋 Test: update_sequencers_coinbase")

    setup_test_files()

    mappings = [
        {"attester_address": "0x1111111111111111111111111111111111111111", "split_contract": "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        {"attester_address": "0x2222222222222222222222222222222222222222", "split_contract": "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"},
        {"attester_address": "0x3333333333333333333333333333333333333333", "split_contract": "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"},
    ]

    updates, changes, error = monitor.update_sequencers_coinbase(mappings)

    assert error is None, f"Unexpected error: {error}"
    assert updates == 2, f"Expected 2 updates, got {updates}"
    assert len(changes) == 2, f"Expected 2 changes, got {len(changes)}"

    print(f"  Updated {updates} coinbase addresses")
    for change in changes:
        print(f"  - {change['old_coinbase'][:10]}... -> {change['new_coinbase'][:10]}...")

    # Verify the file was updated
    with open(Path(TEST_KEYSTORE_DIR) / "sequencers.json", "r") as f:
        updated_data = json.load(f)

    validators = updated_data["validators"]
    assert validators[0]["coinbase"] == "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert validators[1]["coinbase"] == "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    assert validators[2]["coinbase"] == "0x4444444444444444444444444444444444444444"  # Unchanged

    print("✅ Sequencers update works correctly")


def test_state_persistence():
    """Test state save/load."""
    print("\n📋 Test: state_persistence")

    # Save state
    test_state = {
        "known_stakes": {"0xtest": "0xsplit"},
        "last_updated": None
    }
    monitor.save_state(test_state)

    # Load state
    loaded_state = monitor.load_state()

    assert "0xtest" in loaded_state["known_stakes"]
    assert loaded_state["known_stakes"]["0xtest"] == "0xsplit"
    assert loaded_state["last_updated"] is not None

    print(f"  State saved and loaded successfully")
    print(f"  Last updated: {loaded_state['last_updated']}")
    print("✅ State persistence works correctly")


def test_error_alerting():
    """Test error alerting logic."""
    print("\n📋 Test: error_alerting")

    # Reset error state
    monitor.error_state = {
        "consecutive_failures": 0,
        "last_error_alert_time": 0,
        "last_error_type": None,
        "was_in_error_state": False
    }

    # First failure - should not alert yet (threshold is 3)
    monitor.send_error_alert("Test Error", "This is a test error")
    assert monitor.error_state["consecutive_failures"] == 1
    assert monitor.error_state["was_in_error_state"] == False  # No alert sent yet

    # Second failure
    monitor.send_error_alert("Test Error", "This is a test error")
    assert monitor.error_state["consecutive_failures"] == 2

    # Third failure - would trigger alert if Slack was configured
    monitor.send_error_alert("Test Error", "This is a test error")
    assert monitor.error_state["consecutive_failures"] == 3

    print(f"  Consecutive failures tracked: {monitor.error_state['consecutive_failures']}")
    print("✅ Error alerting logic works correctly")


def test_full_run_with_mock():
    """Test full run cycle with mocked API."""
    print("\n📋 Test: full_run_with_mock")

    setup_test_files()

    # Reset state (state files are in DATA_PATH, not KEYSTORE_PATH)
    state_file = Path(TEST_DATA_DIR) / "coinbase-monitor-state.json"
    if state_file.exists():
        state_file.unlink()

    # Mock the API call
    with patch.object(monitor, 'fetch_provider_data') as mock_fetch:
        mock_fetch.return_value = (MOCK_PROVIDER_DATA, None)

        # Run check
        success = monitor.run_check()

        assert success == True, "run_check should return True"
        mock_fetch.assert_called_once()

    # Verify state was saved (in DATA_PATH)
    assert state_file.exists(), "State file should exist"

    # Verify mappings were saved (in DATA_PATH)
    mappings_file = Path(TEST_DATA_DIR) / "coinbase-mappings.json"
    assert mappings_file.exists(), "Mappings file should exist"

    with open(mappings_file, "r") as f:
        mappings_data = json.load(f)

    assert len(mappings_data["mappings"]) == 3

    print("  Full run completed successfully")
    print(f"  Mappings saved: {len(mappings_data['mappings'])}")
    print("✅ Full run with mock works correctly")


def test_api_error_handling():
    """Test API error handling."""
    print("\n📋 Test: api_error_handling")

    # Reset error state
    monitor.error_state = {
        "consecutive_failures": 0,
        "last_error_alert_time": 0,
        "last_error_type": None,
        "was_in_error_state": False
    }

    # Mock API returning error
    with patch.object(monitor, 'fetch_provider_data') as mock_fetch:
        mock_fetch.return_value = (None, "Connection timeout")

        success = monitor.run_check()

        assert success == False, "run_check should return False on error"
        assert monitor.error_state["consecutive_failures"] == 1

    print("  API error handled correctly")
    print(f"  Consecutive failures: {monitor.error_state['consecutive_failures']}")
    print("✅ API error handling works correctly")


def cleanup():
    """Clean up test files."""
    import shutil
    try:
        shutil.rmtree(TEST_KEYSTORE_DIR)
        shutil.rmtree(TEST_DATA_DIR)
        print(f"\n🧹 Cleaned up test directories")
    except Exception as e:
        print(f"\n⚠️ Failed to clean up: {e}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Aztec Coinbase Monitor - Unit Tests")
    print(f"Test keystore dir: {TEST_KEYSTORE_DIR}")
    print(f"Test data dir: {TEST_DATA_DIR}")
    print("=" * 60)

    try:
        test_normalize_address()
        test_format_amount()
        test_process_stakes()
        test_update_sequencers_coinbase()
        test_state_persistence()
        test_error_alerting()
        test_full_run_with_mock()
        test_api_error_handling()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
