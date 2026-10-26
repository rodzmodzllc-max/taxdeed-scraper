"""The harvest workflow's queue (2026-10-26): every run that writes shares one
concurrency group, so two syncs never overlap; read-only evidence captures get
a group of their own, so they never queue behind - or knock out - a pending
harvest in that single slot."""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "harvest-and-sync.yml"


def test_writes_share_one_group_and_evidence_gets_its_own():
    c = yaml.safe_load(WF.read_text())["concurrency"]
    g = c["group"]
    assert c["cancel-in-progress"] is False
    assert "'harvest-and-sync'" in g
    assert "github.event.inputs.job == 'evidence'" in g and "github.run_id" in g


def test_evidence_job_never_writes():
    jobs = yaml.safe_load(WF.read_text())["jobs"]
    env = str(jobs["evidence"])
    assert "SUPABASE_SERVICE_KEY" not in env
