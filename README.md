# Aztec Prover Docker

Docker Compose for an Aztec Sequencer/Validator and optional monitoring sidecars.

Meant to be used with [central-proxy-docker](https://github.com/CryptoManufaktur-io/central-proxy-docker) for traefik
and Prometheus remote write; use `:ext-network.yml` in `COMPOSE_FILE` inside `.env` in that case.

## Quick setup for Sequencer / Validator

Run `cp default.env .env`, then `nano .env`, and update values like `L1_RPC`, `L1_REST`, `VALIDATOR_PRIVATE_KEYS`,
`L1_WALLET_PRIVATE_KEY`, `COINBASE`, and the `NETWORK` as well as the `PUBLIC_IP_ADDRESS`.

`L1_WALLET_PRIVATE_KEY` is the private key of an L1 wallet, and will be used to pay gas. This is the only wallet that
needs to have ETH, even when multiple validators are active via `VALIDATOR_PRIVATE_KEYS`.

`COINBASE` is a public address, which you will receive block rewards on.

`VALIDATOR_PRIVATE_KEYS` is a comma-separated list of L1 wallet private keys, one for each validator that should
be run by the sequencer/validator process. These wallets do not need to be funded with ETH.

Make sure that `COMPOSE_FILE` includes `validator.yml`

### Sequencer Keystore

The validator requires a keystore file at `aztec-validator-keystore/sequencer.json`. For disaster recovery testing with dummy keys (not actual sequencing), create the file manually:

```json
{
  "schemaVersion": 1,
  "validators": [
    {
      "attester": {
        "eth": "0x0000000000000000000000000000000000000000000000000000000000000001",
        "bls": "0x0000000000000000000000000000000000000000000000000000000000000001"
      },
      "publisher": ["0x0000000000000000000000000000000000000000000000000000000000000001"],
      "feeRecipient": "0x0000000000000000000000000000000000000000000000000000000000000000",
      "coinbase": "0x0000000000000000000000000000000000000001"
    }
  ]
}
```

For production use, generate proper keys using the Aztec CLI. See the [Aztec keystore documentation](https://docs.aztec.network/the_aztec_network/operation/keystore/creating_keystores) for details.

Wait for the validator to be fully synced: Check with `./aztecd logs -f validator` and look for a message telling
you that it's up and listening on the aztec port 8080, and has peers.

You can register the validator with the Aztec testnet using zkPassport at https://testnet.aztec.network/

## Install and updates

- `./aztecd install` brings in docker-ce, if you don't have Docker installed already.
- `./aztecd up`

To update the software manually, run `./aztecd update` and then `./aztecd up`

### Auto-updates

Aztec has a concept of auto-updates, where it will shut down the process if the rollup config changed and/or
the required minimum version changed. However, under Docker Compose, the `pull-policy: always` does not
apply when the container merely restarts: It needs to be recreated by Compose with `docker compose up -d` for
the pull policy to grab an updated image.

Aztec Prover Docker uses `--auto-update config` with Aztec, where it will terminate the process if the
config changed but the required version did not. `AZTEC_AUTOUPDATE=true` adds watchtower labels for installations
that already run a host-level watchtower service.

Note `AZTEC_AUTOUPDATE` only controls whether an external watchtower should update the Aztec images. The auto-update
function that does not pull a new image, `--auto-update config`, is always active.

## Architecture

The validator/sequencer is stand-alone and keeps its own data and keystore volumes. Optional monitoring sidecars can
be added to `COMPOSE_FILE` when those metrics are needed.

## Customization

`custom.yml` is not tracked by git and can be used to override anything in the provided yml files. If you use it,
add it to `COMPOSE_FILE` in `.env`

## Version

Aztec Prover Docker uses a semver scheme.

This is Aztec Prover Docker v3.0.0
