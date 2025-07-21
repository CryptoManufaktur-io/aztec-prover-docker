# Aztec Prover Docker

Docker Compose for an Aztec Prover and/or Sequencer.

Meant to be used with [central-proxy-docker](https://github.com/CryptoManufaktur-io/central-proxy-docker) for traefik
and Prometheus remote write; use `:ext-network.yml` in `COMPOSE_FILE` inside `.env` in that case.

## Quick setup for Prover

Run `cp default.env .env`, then `nano .env`, and update values like `L1_RPC`, `L1_REST`, `L1_WALLET_PRIVATE_KEY`,
and the `NETWORK` as well as the `BLOB_SINK_URL` and `PUBLIC_IP_ADDRESS`.

`L1_WALLET_PRIVATE_KEY` is the private key of an L1 wallet, and will be used to pay gas.

If you want the broker node port exposed unencrypted to the host, use `broker-shared.yml` in `COMPOSE_FILE` inside `.env`.

## Quick setup for Sequencer / Validator

Run `cp default.env .env`, then `nano .env`, and update values like `L1_RPC`, `L1_REST`, `VALIDATOR_PRIVATE_KEYS`,
`L1_WALLET_PRIVATE_KEY`, `COINBASE`, and the `NETWORK` as well as the `PUBLIC_IP_ADDRESS`.

`L1_WALLET_PRIVATE_KEY` is the private key of an L1 wallet, and will be used to pay gas. This is the only wallet that
needs to have ETH, even when multiple validators are active via `VALIDATOR_PRIVATE_KEYS`.

`COINBASE` is a public address, which you will receive block rewards on.

`VALIDATOR_PRIVATE_KEYS` is a comma-separated list of L1 wallet private keys, one for each validator that should
be run by the sequencer/validator process. These wallets do not need to be funded with ETH.

Make sure that `COMPOSE_FILE` includes `validator.yml`

Wait for the validator to be fully synced: Check with `./aztecd logs -f validator` and look for a message telling
you that it's up and listening on the aztec port 8080, and has peers.

NB: Registration is changing, README will be updated with new instructions

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
config changed but the required version did not, and offers watchtower to handle the Docker image update on a
tag like `latest`. `watchtower.yml` should run with one and only one copy on the host in that case, and
`AZTEC_AUTOUPDATE=true` should be set in `.env`, which it is by default.

Note `AZTEC_AUTOUPDATE` only controls whether the Aztec images will be updated by watchtower. The auto-update
function that does not pull a new image, `--auto-update config`, is always active.

## Architecture

You'll have one Broker and Node, and N agents. Only the Broker and Node keep state; they can also be on a relatively low-powered machine - 6 cores, 32 GiB RAM. The agents connect
to the broker and should be, for testnet, on 16-core/32-thread EPYC with 128 GiB RAM.

The broker can be exposed directly to the host or via traefik. In either case, it should only be reachable by your agents: Configure firewalling so it is not Internet-reachable.

The validator/sequencer is stand-alone. While it is possible to have the prover node use the sequencer node, instead
of having its own P2P, we've opted not to do that. That way, the prover does not depend on the sequencer being live.

## Customization

`custom.yml` is not tracked by git and can be used to override anything in the provided yml files. If you use it,
add it to `COMPOSE_FILE` in `.env`

## Version

Aztec Prover Docker uses a semver scheme.

This is Aztec Prover Docker v2.0.0
