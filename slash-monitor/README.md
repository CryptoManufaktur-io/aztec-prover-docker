# Aztec Slash Monitor

Read-only Prometheus exporter for Aztec on-chain slashing state.

The monitor polls the Aztec L1 slashing contracts and checks whether any locally configured validator attester is targeted in active slashing rounds. It does not submit transactions, vote, veto, or modify validator configuration.

## Targeting scope

The monitor reads local attester private keys from `sequencers.json` or `sequencer.json` in the mounted keystore and derives the corresponding validator addresses. It only checks those local validator addresses; it does not query a provider ID or discover every sequencer assigned to a provider account.

When one of the local validator addresses is targeted, the exported metrics include the slashing round, validator address, slash amount, and round status. The status indicates whether the round is still voting, has reached quorum, is in the veto window, is executable, or has already executed.

The on-chain action data used here includes the targeted validator and slash amount. It does not include an offense reason, so the monitor can show which address is going to be slashed or has been slashed, but it cannot explain why the slash was proposed.

## Metrics

| Metric | Description |
| --- | --- |
| `aztec_slashing_enabled` | `1` when slashing is globally enabled, otherwise `0` |
| `aztec_slashing_our_validator_targeted` | `1` for a targeted local validator by round |
| `aztec_slashing_our_validator_targeted_rounds_total` | Count of active rounds targeting local validators |
| `aztec_slashing_last_poll_timestamp` | Unix timestamp of the last successful poll |
| `aztec_slashing_round_vote_count` | Vote count by slashing round |
| `aztec_slashing_round_status` | Round status enum: `0=expired`, `1=voting`, `2=quorum-reached`, `3=in-veto-window`, `4=executable`, `5=executed` |

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `L1_RPC` | none | Comma-separated L1 RPC URLs, mapped to `L1_RPC_URL` in the container |
| `SLASH_MONITOR_NETWORK` | `mainnet` | Network contract defaults to use |
| `SLASH_MONITOR_POLL_INTERVAL` | `900` | Seconds between L1 slashing polls |
| `SLASH_MONITOR_METRICS_PORT` | `9101` | Prometheus scrape port |
| `KEYSTORE_PATH` | `/keystore` | Container path for `sequencers.json` or `sequencer.json` |

## Run

Add `slash-monitor.yml` to `COMPOSE_FILE` with the validator stack:

```env
COMPOSE_FILE=validator.yml:coinbase-monitor.yml:provider-key-monitor.yml:slash-monitor.yml:ext-network.yml
SLASH_MONITOR_NETWORK=mainnet
SLASH_MONITOR_POLL_INTERVAL=900
SLASH_MONITOR_METRICS_PORT=9101
```

Start only the sidecar:

```sh
docker compose up -d --build slash-monitor
```
