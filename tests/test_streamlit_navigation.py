from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_production_streamlit_pages_are_focused_and_ordered() -> None:
    """Filename ordering is Streamlit's default sidebar navigation ordering."""
    pages = [path.name for path in sorted((APP_ROOT / "pages").glob("*.py"))]

    assert pages == [
        "1_Exchange_Market_Cap.py",
        "2_Benchmark_Lab.py",
        "3_Modular_Scatterplot_Explorer.py",
        "4_Correlation_Structure_Lab.py",
        "5_Rally_Leaderboards.py",
        "6_Derivatives_Lab.py",
        "7_Integer_Index_Replication.py",
    ]


def test_home_page_links_use_production_page_paths() -> None:
    home = (APP_ROOT / "Home.py").read_text(encoding="utf-8")

    assert 'st.page_link("pages/6_Derivatives_Lab.py"' in home
    assert 'st.page_link("pages/7_Integer_Index_Replication.py"' in home
    assert "pages/19_Derivatives_Lab.py" not in home
    assert "pages/20_Integer_Index_Replication.py" not in home
