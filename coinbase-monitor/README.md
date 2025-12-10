# Aztec Coinbase Monitor

Automatically monitors the Aztec Staking Dashboard API for new delegations to your provider and updates the coinbase addresses in `sequencers.json` to point to the correct split contract addresses.

## Overview

When delegators stake with your provider on Aztec, a **split contract** is created that handles reward distribution between you (the provider) and the delegator. Each sequencer's `coinbase` address must be set to this split contract to ensure proper reward distribution.

This monitor:
1. Polls the Staking Dashboard API periodically
2. Detects new delegations and their split contracts
3. Automatically updates `sequencers.json` with the correct coinbase addresses
4. Sends Slack notifications for updates and errors

## Prerequisites

- Docker and Docker Compose
- Your `sequencers.json` file in `aztec-validator-keystore/`
- Your Provider ID from the Staking Dashboard
- (Optional) Slack webhook URL for notifications

## Quick Start

1. **Copy environment file:**
   ```bash
   cp default.env .env
   ```

2. **Configure your `.env`:**
   ```bash
   # Required
   PROVIDER_ID=<your-provider-id>
   STAKING_API_URL=<staking-api-url>

   # Optional but recommended
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/xxx/xxx
   ```

3. **Run the monitor:**
   ```bash
   docker compose -f coinbase-monitor.yml up -d
   ```

4. **View logs:**
   ```bash
   docker compose -f coinbase-monitor.yml logs -f
   ```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PROVIDER_ID` | `` | Your provider ID on the Staking Dashboard (required) |
| `STAKING_API_URL` | `` | Staking Dashboard API URL (required) |
| `MONITOR_POLL_INTERVAL` | `300` | Seconds between API polls (5 minutes) |
| `SLACK_WEBHOOK_URL` | `` | Slack webhook URL for notifications |
| `KEYSTORE_PATH` | `/keystore` | Path to the keystore directory containing sequencers.json |
| `DATA_PATH` | `/data` | Path for state/mappings files (Docker named volume) |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ERROR_ALERT_THRESHOLD` | `3` | Number of consecutive failures before alerting |
| `ERROR_ALERT_COOLDOWN` | `3600` | Seconds between error alerts (1 hour) |

## Running with Validator

Add to your `COMPOSE_FILE` in `.env`:

```bash
COMPOSE_FILE=validator.yml:coinbase-monitor.yml
```

Then start both services:
```bash
docker compose up -d
```

## Storage

### Volumes

The monitor uses two separate volumes:

| Volume | Path | Purpose |
|--------|------|---------|
| `./aztec-validator-keystore` | `/keystore` | Contains `sequencers.json` (read/write) |
| `coinbase-monitor-data` (Docker named volume) | `/data` | State and mappings files |

This keeps your `aztec-validator-keystore/` directory clean with only `sequencers.json`.

### State Files (in Docker named volume)

These files are stored in a Docker-managed volume and don't appear on your host filesystem:

#### `coinbase-monitor-state.json`
Tracks known stakes to prevent duplicate notifications:
```json
{
  "known_stakes": {
    "0x1c289f47ac8e0ff60ecef1a37b9b74b4687d3cc1": "0x78bBD4af04af5208743497AE32a554281Bf90999"
  },
  "last_updated": "2025-12-09T10:30:00Z"
}
```

#### `coinbase-mappings.json`
Reference file with all current mappings:
```json
{
  "last_updated": "2025-12-09T10:30:00Z",
  "provider_id": "123",
  "mappings": [
    {
      "attester_address": "0x1c289f47AC8e0fF60eCef1A37b9B74B4687D3cC1",
      "split_contract": "0x78bBD4af04af5208743497AE32a554281Bf90999",
      "staked_amount": "200000000000000000000000"
    }
  ]
}
```

**Note:** If the state files are lost (e.g., volume deleted), the only impact is a one-time re-notification of existing delegations. No functional impact occurs since `sequencers.json` already has the correct coinbase addresses.

## Slack Notifications

### New Delegation Detected
```
🆕 New Aztec Delegation(s) Detected

Provider: YourProvider (ID: 123)

2 new delegation(s):

• Attester: 0x1234abcd...5678efgh
  Split Contract: 0xabcd1234...efgh5678
  Staked: 200,000 AZTEC
```

### Coinbase Update Applied
```
🔔 Aztec Coinbase Update

Provider: YourProvider (ID: 123)
Total Staked: 1,600,000 AZTEC

8 coinbase address(es) updated:

• Attester: 0x1234abcd...5678efgh
  Split Contract: 0xabcd1234...efgh5678

✅ sequencers.json has been automatically updated.
```

### Error Alert
```
🚨 Aztec Coinbase Monitor Error

Provider ID: 123
Error Type: API Fetch Failed

Request timeout after 30s: https://...

Consecutive failures: 3
Will retry in 300 seconds.
```

### Recovery Alert
```
✅ Aztec Coinbase Monitor Recovered

Provider ID: 123
Service resumed normal operation after 3 failed attempt(s).
```

## How It Works

1. **Fetch Provider Data**: Calls the Staking Dashboard API to get your provider's current stakes
2. **Process Stakes**: Extracts `attesterAddress` → `splitContractAddress` mappings
3. **Compare with State**: Identifies new or changed mappings
4. **Update sequencers.json**: For each validator where `coinbase` matches an `attesterAddress`, updates it to the `splitContractAddress`
5. **Notify**: Sends Slack notifications for new delegations and updates
6. **Save State**: Persists state to avoid duplicate notifications

## Understanding Key Relationships

### sequencers.json Structure

Each validator in `sequencers.json` has:
```json
{
  "attester": {
    "eth": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",  // Private key (example)
    "bls": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
  },
  "publisher": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
  "feeRecipient": "0x0000000000000000000000000000000000000000000000000000000000000000",
  "coinbase": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"  // Public address (attester address)
}
```

- **`attester.eth`**: The private key (DO NOT share!)
- **`coinbase`**: Initially set to the **public Ethereum address** derived from `attester.eth`

### Deriving Public Address from Private Key

To verify which attester address corresponds to a private key:

**Using cast (Foundry):**
```bash
cast wallet address --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
# Output: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
```

**Using Python:**
```bash
pip install eth-account
python3 -c "from eth_account import Account; print(Account.from_key('0xYOUR_PRIVATE_KEY_HERE').address)"
```

**Using Node.js (ethers):**
```bash
node -e "console.log(new (require('ethers').Wallet)('0xYOUR_PRIVATE_KEY_HERE').address)"
```

> **Note:** The example key `0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80` is the well-known Hardhat/Foundry test account #0. Never use test keys in production!

### How Matching Works

1. When you generate keys with `aztec validator-keys new`, `coinbase` is automatically set to the public address derived from `attester.eth`
2. When you stake, this address becomes the `attesterAddress` on-chain
3. The API returns `attesterAddress` → `splitContractAddress` mappings
4. The monitor matches `coinbase` in `sequencers.json` with `attesterAddress` from the API
5. When matched, it replaces `coinbase` with the `splitContractAddress`

### Example Flow

| Step | coinbase value | Description |
|------|---------------|-------------|
| 1. Key generation | `0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266` | Public address from private key |
| 2. Staking | (same) | Registered on-chain as attester |
| 3. Delegation | (same) | Delegator stakes, split contract created |
| 4. Monitor update | `0xSplitContractAddress...` | Replaced with split contract |

## Important Notes

⚠️ **Backup**: The monitor modifies `sequencers.json`. Consider backing it up before first run.

⚠️ **Initial Coinbase**: Your `sequencers.json` must have the `coinbase` field set to the **attester's Ethereum address** (not the split contract) for the monitor to match them correctly. This is the default when generating keys with `aztec validator-keys new`.

## Troubleshooting

### API Fetch Errors
- Check your network connectivity
- Verify the API URL is accessible
- The API may have rate limiting or geo-restrictions

### No Updates Happening
- Verify your `PROVIDER_ID` is correct
- Check that `coinbase` addresses in `sequencers.json` match attester addresses from the API
- Enable `LOG_LEVEL=DEBUG` for more verbose output

### Permission Errors
- Ensure the container has write access to `aztec-validator-keystore/`
- Check file ownership and permissions

### Inspect State Files
Since state files are in a Docker named volume:
```bash
# View state file
docker compose -f coinbase-monitor.yml exec coinbase-monitor cat /data/coinbase-monitor-state.json

# View mappings file
docker compose -f coinbase-monitor.yml exec coinbase-monitor cat /data/coinbase-mappings.json
```

### View Logs
```bash
# Follow logs
docker compose -f coinbase-monitor.yml logs -f coinbase-monitor

# Last 100 lines
docker compose -f coinbase-monitor.yml logs --tail 100 coinbase-monitor
```

## Development

Run locally without Docker:
```bash
cd coinbase-monitor
pip install -r requirements.txt
mkdir -p /tmp/coinbase-data
KEYSTORE_PATH=../aztec-validator-keystore DATA_PATH=/tmp/coinbase-data PROVIDER_ID=<your-id> STAKING_API_URL=<api-url> python monitor.py
```

## License

Same as the parent project.
