# 1. Record architecture decisions

Date: 2026-07-15

## Status

Accepted

## Context

This project has several consequential, hard-to-reverse architectural choices (CBS
integration approach, data stack, engine design, deployment posture). We want the reasoning
behind them to be discoverable later, not lost in chat history or commit messages.

## Decision

We record significant decisions as Architecture Decision Records (ADRs) — short,
numbered, append-only Markdown files in `docs/adr/`, following Michael Nygard's format.
Superseded decisions are marked as such rather than deleted.

## Consequences

- Each significant decision gets a numbered file (`NNNN-title.md`).
- Reversing a decision means adding a new ADR that supersedes the old one.
- The deep-research report remains the background rationale; ADRs capture the specific
  choices we commit to.
