"""Preparation-time data pipeline for the Flame in Freefall research explorer.

Stages read saved PSI metadata and selected source files, and write JSON that the
application imports. Raw downloads and intermediate outputs live under the ignored
``res/`` directory; curated inputs and reviewed outputs live under ``data/``.
"""
