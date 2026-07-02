# Aztec Provider Key Monitor

Read-only Prometheus exporter for Aztec provider sequencer key availability.

The monitor polls the Aztec staking registry for `getProviderQueueLength(<provider_id>)` and exposes raw metrics for Grafana. It does not update `sequencers.json`, does not change coinbase addresses, and does not send Slack notifications.

## Metrics

| Metric | Description |
| --- | --- |
| `aztec_provider_sequencer_key_queue_length{provider_id="74"}` | Current provider sequencer key queue length |
| `aztec_provider_queue_last_success_timestamp{provider_id="74"}` | Unix timestamp of the last successful poll |
| `aztec_provider_queue_poll_errors_total{provider_id="74"}` | Total failed poll attempts |
| `aztec_provider_queue_up{provider_id="74"}` | `1` when the latest poll succeeded, otherwise `0` |

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `PROVIDER_ID` | none | Aztec staking provider ID |
| `L1_RPC` | none | Comma-separated L1 RPC URLs, mapped to `L1_RPC_URL` in the container |
| `PROVIDER_KEY_MONITOR_NETWORK` | `mainnet` | Network contract defaults to use |
| `PROVIDER_QUEUE_CONTRACT_ADDRESS` | mainnet staking registry | Optional override for the queue contract |
| `PROVIDER_KEY_MONITOR_POLL_INTERVAL` | `300` | Seconds between queue polls |
| `PROVIDER_KEY_MONITOR_METRICS_PORT` | `9102` | Prometheus scrape port |

## Run

Add `provider-key-monitor.yml` to `COMPOSE_FILE` with `validator.yml`:

```env
COMPOSE_FILE=validator.yml:coinbase-monitor.yml:provider-key-monitor.yml:ext-network.yml
PROVIDER_ID=74
PROVIDER_KEY_MONITOR_NETWORK=mainnet
PROVIDER_KEY_MONITOR_POLL_INTERVAL=300
PROVIDER_KEY_MONITOR_METRICS_PORT=9102
```

Start only the sidecar:

```sh
docker compose up -d --build provider-key-monitor
```
