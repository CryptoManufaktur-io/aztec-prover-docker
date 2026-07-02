# Aztec Provider Monitor

Provider monitor for Aztec validators.

The service keeps the existing coinbase updater behavior and also exports
provider-level Prometheus metrics:

- Fetches provider stake data from the Staking Dashboard API.
- Updates `aztec-validator-keystore/sequencers.json` coinbase addresses to the
  matching split contract addresses.
- Sends Slack notifications for new delegations, coinbase updates, and repeated
  updater errors when `SLACK_WEBHOOK_URL` is configured.
- Polls the L1 staking registry with `getProviderQueueLength(PROVIDER_ID)`.
- Exposes raw metrics for Grafana alerting.

Grafana owns metric alert thresholds, severity, routing, and no-data behavior.
The compose volume and persisted mapping files keep their existing names:
`coinbase-monitor-data`, `coinbase-monitor-state.json`, and
`coinbase-mappings.json`. This preserves updater state across the service
rename.

## Metrics

| Metric | Description |
| --- | --- |
| `aztec_provider_sequencer_key_queue_length{provider_id}` | Current provider sequencer key queue length |
| `aztec_provider_queue_last_success_timestamp{provider_id}` | Unix timestamp of the last successful provider queue poll |
| `aztec_provider_queue_poll_errors_total{provider_id}` | Total failed provider queue polls |
| `aztec_provider_queue_up{provider_id}` | Latest queue poll status, `1` for success and `0` for failure |
| `aztec_provider_coinbase_update_up{provider_id}` | Latest coinbase updater status, `1` for success and `0` for failure |
| `aztec_provider_coinbase_update_last_success_timestamp{provider_id}` | Unix timestamp of the last successful coinbase updater check |
| `aztec_provider_coinbase_updates_total{provider_id}` | Total coinbase updates written to `sequencers.json` |
| `aztec_provider_coinbase_update_errors_total{provider_id}` | Total coinbase updater errors |

## Configuration

| Environment Variable | Default | Description |
| --- | --- | --- |
| `PROVIDER_ID` | `` | Aztec provider ID to monitor |
| `STAKING_API_URL` | `` | Staking Dashboard API base URL |
| `L1_RPC_URL` | `` | L1 RPC URL list, comma-separated |
| `NETWORK` | `mainnet` | Network used to select default contract addresses |
| `MONITOR_POLL_INTERVAL` | `10800` | Seconds between coinbase update checks and provider queue metric polls |
| `PROVIDER_MONITOR_METRICS_PORT` | `9102` | Compose-level Prometheus metrics port and scrape label |
| `METRICS_PORT` | `9102` | Container/script Prometheus metrics port, normally set by compose |
| `PROVIDER_QUEUE_CONTRACT_ADDRESS` | network default | Optional override for the staking registry address. Required for networks without a verified default. |
| `SLACK_WEBHOOK_URL` | `` | Optional Slack webhook for coinbase updater notifications |
| `KEYSTORE_PATH` | `/keystore` | Path containing `sequencers.json` |
| `DATA_PATH` | `/data` | Path for updater state and mapping files |
| `LOG_LEVEL` | `INFO` | Logging level |
| `RPC_TIMEOUT` | `30` | Per-RPC timeout in seconds |
| `ERROR_ALERT_THRESHOLD` | `3` | Consecutive updater failures before Slack alerting |
| `ERROR_ALERT_COOLDOWN` | `3600` | Seconds between repeated updater error Slack alerts |

## Running With Validator

Add the monitor to `COMPOSE_FILE`:

```bash
COMPOSE_FILE=validator.yml:provider-monitor.yml
```

Then start the stack:

```bash
docker compose up -d
```

## Local Development

```bash
cd provider-monitor
pip install -r requirements.txt
mkdir -p /tmp/aztec-provider-monitor-keystore /tmp/aztec-provider-monitor-data
printf '{"schemaVersion":1,"validators":[]}\n' > /tmp/aztec-provider-monitor-keystore/sequencers.json
PROVIDER_ID=74 \
STAKING_API_URL=https://staking-api.example/api \
L1_RPC_URL=https://ethereum-rpc.example \
KEYSTORE_PATH=/tmp/aztec-provider-monitor-keystore \
DATA_PATH=/tmp/aztec-provider-monitor-data \
NETWORK=mainnet \
python monitor.py
```

Run tests:

```bash
cd provider-monitor
python -m unittest test_monitor.py
```
