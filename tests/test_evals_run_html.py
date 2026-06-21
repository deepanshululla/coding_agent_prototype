"""The HTML report is wired into the shared CLI path, so it's produced for ANY
suite — not just a special-cased one. These tests drive `main()` end to end with
a stubbed agent (no model calls) and assert the report file appears.
"""

import evals.harness as harness
import evals.run as run


async def _fake_agent(task, **kwargs):
    # An agent that does nothing — the tasks "fail", but a report is still written.
    return [{"type": "agent_end"}], []


def _stub(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "run_agent_collecting", _fake_agent)
    monkeypatch.setattr(run, "_silence_transcript", lambda: None)  # don't touch global emit
    monkeypatch.chdir(tmp_path)


def test_report_written_by_default_for_a_local_suite(monkeypatch, tmp_path):
    _stub(monkeypatch, tmp_path)
    run.main(["smoke", "--limit", "1"])
    assert (tmp_path / "eval-report.html").exists()


def test_report_written_for_a_different_suite_too(monkeypatch, tmp_path):
    # A different suite goes through the same shared tail -> same report wiring.
    _stub(monkeypatch, tmp_path)
    run.main(["toolcall", "--limit", "1"])
    assert (tmp_path / "eval-report.html").exists()


def test_no_html_flag_skips_the_report(monkeypatch, tmp_path):
    _stub(monkeypatch, tmp_path)
    run.main(["smoke", "--limit", "1", "--no-html"])
    assert not (tmp_path / "eval-report.html").exists()


def test_custom_html_path_is_honoured(monkeypatch, tmp_path):
    _stub(monkeypatch, tmp_path)
    run.main(["smoke", "--limit", "1", "--html", "custom.html"])
    assert (tmp_path / "custom.html").exists()
    assert not (tmp_path / "eval-report.html").exists()


def test_comparison_path_also_writes_the_report(monkeypatch, tmp_path):
    _stub(monkeypatch, tmp_path)
    run.main(["smoke", "--limit", "1", "--models", "a,b"])
    html = (tmp_path / "eval-report.html").read_text()
    assert "<html" in html and "a" in html and "b" in html  # both models in the report
