# Aztec Provider Monitor

Read-only Prometheus exporter for Aztec provider-level metrics.

The monitor currently polls the L1 provider queue length with
`getProviderQueueLength(PROVIDER_ID)` and exposes raw metrics. Grafana owns
alert thresholds, severity, routing, and no-data behavior.

## Metrics

| Metric | Description |
| --- | --- |
| `aztec_provider_sequencer_key_queue_length{provider_id}` | Current provider sequencer key queue length |
| `aztec_provider_queue_last_success_timestamp{provider_id}` | Unix timestamp of the last successful queue poll |
| `aztec_provider_queue_poll_errors_total{provider_id}` | Total failed provider queue polls |
| `aztec_provider_queue_up{provider_id}` | Latest queue poll status, `1` for success and `0` for failure |

## Configuration

| Environment Variable | Default | Description |
| --- | --- | --- |
| `PROVIDER_ID` | `` | Aztec provider ID to monitor |
| `L1_RPC_URL` | `` | L1 RPC URL list, comma-separated |
| `NETWORK` | `mainnet` | Network used to select default contract addresses |
| `MONITOR_POLL_INTERVAL` | `300` | Seconds between provider queue polls |
| `METRICS_PORT` | `9102` | Prometheus metrics port |
| `PROVIDER_QUEUE_CONTRACT_ADDRESS` | network default | Optional override for the queue contract address |
| `LOG_LEVEL` | `INFO` | Logging level |
| `RPC_TIMEOUT` | `30` | Per-RPC timeout in seconds |

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
PROVIDER_ID=74 \
L1_RPC_URL=https://ethereum-rpc.example \
NETWORK=mainnet \
python monitor.py
```

Run tests:

```bash
cd provider-monitor
python -m unittest test_monitor.py
```
