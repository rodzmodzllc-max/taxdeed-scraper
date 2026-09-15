"""Makes `harvesters/` an importable package (needed so tests can do
`from harvesters.governance import registry` without relying on sys.path
tricks). Purely additive - texas_harvester.py is still run directly as a
script in production (`python3 harvesters/texas_harvester.py`, see
.github/workflows/harvest-and-sync.yml's `texas` job) and this file changes
nothing about that; it only makes the same directory ALSO importable as a
package for test code. No behavior change to any existing harvester.
"""
