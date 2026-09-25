from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_authoritative_v1_docs_exist_and_point_to_current_packages():
    architecture = (ROOT / "docs/V1_ARCHITECTURE.md").read_text(encoding="utf-8")
    status = (ROOT / "docs/V1_STATUS.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
    assert "Caddy HTTPS -> oauth2-proxy OIDC -> Streamlit" in architecture
    assert "Package 7" in roadmap and "Advanced Quantitative Model Library" in roadmap
    assert "Package 8" in roadmap and "clean-VM" in roadmap
    assert "Scientific maturity is deliberately independent" in status


def test_research_daemon_doc_no_longer_claims_holiday_calendar_missing():
    doc = (ROOT / "docs/research/RESEARCH_DAEMON_V1.md").read_text(encoding="utf-8")
    assert "not yet exchange-holiday" not in doc
    assert "XNYS holidays are skipped" in doc


def test_v1_status_records_quant_library_before_release_candidate():
    status = (ROOT / "docs/V1_STATUS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/V1_ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Package 7: advanced quantitative model library/research bench" in status
    assert "research-only challengers/diagnostics" in status
    assert "Quantitative-library boundary" in architecture
    assert "does not import the database repository" in architecture

def test_authoritative_status_no_longer_claims_package_b_is_active_build():
    status = (
        ROOT / "docs/V1_STATUS.md"
    ).read_text(
        encoding="utf-8"
    )
    roadmap = (
        ROOT / "docs/ROADMAP.md"
    ).read_text(
        encoding="utf-8"
    )

    assert "A–F intelligence sequence is implemented" in status
    assert "Package B — Forecasting + Surface Intelligence — is the active development package." not in status
    assert "Package D — Calibration + Model Tournament + Prospective Shadow — COMPLETE / DEPLOYED" in roadmap
    assert "Package E — Decision Engine + Discipline Leakage — COMPLETE / DEPLOYED" in roadmap
    assert "Package F — Casino + 0DTE Lab V1 — COMPLETE / DEPLOYED" in roadmap
    assert "current operational readiness is read from" in roadmap.lower()
