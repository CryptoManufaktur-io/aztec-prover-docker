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
| `KEYSTORE_PATH` | `/keystore` | Path to the keystore directory (inside container) |
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

## Output Files

The monitor creates/updates these files in `aztec-validator-keystore/`:

### `coinbase-monitor-state.json`
Tracks known stakes to prevent duplicate notifications:
```json
{
  "known_stakes": {
    "0x1c289f47ac8e0ff60ecef1a37b9b74b4687d3cc1": "0x78bBD4af04af5208743497AE32a554281Bf90999"
  },
  "last_updated": "2025-12-09T10:30:00Z"
}
```

### `coinbase-mappings.json`
Reference file with all current mappings:
```json
{
  "last_updated": "2025-12-09T10:30:00Z",
  "provider_id": "7",
  "mappings": [
    {
      "attester_address": "0x1c289f47AC8e0fF60eCef1A37b9B74B4687D3cC1",
      "split_contract": "0x78bBD4af04af5208743497AE32a554281Bf90999",
      "staked_amount": "200000000000000000000000"
    }
  ]
}
```

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
⚠️ Restart your validator to apply changes.
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

## Important Notes

⚠️ **Restart Required**: After the monitor updates `sequencers.json`, you must restart your validator for changes to take effect:
```bash
docker compose restart validator
```

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
KEYSTORE_PATH=../aztec-validator-keystore PROVIDER_ID=<your-id> STAKING_API_URL=<api-url> python monitor.py
```

## License

Same as the parent project.
