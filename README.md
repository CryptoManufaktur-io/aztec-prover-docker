# Aztec Prover Docker

Docker Compose for an Aztec Prover.

Meant to be used with [central-proxy-docker](https://github.com/CryptoManufaktur-io/central-proxy-docker) for traefik
and Prometheus remote write; use `:ext-network.yml` in `COMPOSE_FILE` inside `.env` in that case.

## Quick setup

Run `cp default.env .env`, then `nano .env`, and update values like `L1_RPC`, `L1_REST`, `L1_WALLET_PRIVATE_KEY`, and the `L1_CHAIN_ID`.

`L1_WALLET_PRIVATE_KEY` is the private key of an L1 wallet, and will be used to pay gas.

If you want the broker node port exposed unencrypted to the host, use `broker-shared.yml` in `COMPOSE_FILE` inside `.env`.

- `./aztecd install` brings in docker-ce, if you don't have Docker installed already.
- `./aztecd up`

To update the software, run `./aztecd update` and then `./aztecd up`

## Architecture

You'll have one Broker and Node, and N agents. Only the Broker and Node keep state; they can also be on a relatively low-powered machine - 6 cores, 32 GiB RAM. The agents connect
to the broker and should be, for testnet, on 16-core/32-thread EPYC with 128 GiB RAM.

The broker can be exposed directly to the host or via traefik. In either case, it should only be reachable by your agents: Configure firewalling so it is not Internet-reachable.

## Version

Aztec Prover Docker uses a semver scheme.

This is Aztec Prover Docker v1.0.0
