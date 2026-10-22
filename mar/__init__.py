"""Provenance-gated recovery in multi-agent workflows.

Flat package, one module per concern. Only `run` has side effects (LLM calls, tool
execution, file writes); every other module is a function of its inputs.
"""
