"""Shared pytest setup: the suite runs in test mode, so nothing rewrites the real network
adapters or browser registry of the machine running it (even under an admin shell)."""
import os

os.environ["OGK_TESTING"] = "1"
