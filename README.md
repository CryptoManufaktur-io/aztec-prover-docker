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

Run `cp default.env .env`, then `nano .env`, and update values like `L1_RPC`, `L1_REST`, `VALIDATOR_PRIVATE_KEY`,
`COINBASE`, and the `NETWORK` as well as the `BLOB_SINK_URL` and `PUBLIC_IP_ADDRESS`.

`VALIDATOR_PRIVATE_KEY` is the private key of an L1 wallet, and will be used to pay gas. `COINBASE` is its public
address.

Make sure that `COMPOSE_FILE` includes `validator.yml`

## Install and updates

- `./aztecd install` brings in docker-ce, if you don't have Docker installed already.
- `./aztecd up`

To update the software, run `./aztecd update` and then `./aztecd up`

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

This is Aztec Prover Docker v1.1.0
