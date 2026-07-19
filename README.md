# Sentinel documentation

Public documentation for Sentinel, built with [Mintlify](https://mintlify.com).

Pages are MDX files. Site navigation and appearance are configured in `docs.json`.

## Preview locally

Install the Mintlify CLI:

```bash
npm install --global mint
```

Start the local preview from this directory:

```bash
mint dev
```

Open `http://localhost:3000`.

## Validate changes

Run these checks before opening a pull request:

```bash
mint broken-links
mint validate
```

## Content scope

This repository contains public, customer-facing documentation. Document observable behavior, supported interfaces, configuration, and workflows here. Put implementation details, internal sequencing, and design rationale in the private internal documentation repository.
