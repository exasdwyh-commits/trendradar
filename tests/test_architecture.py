from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_frontend_app_is_navigation_shell_not_view_monolith():
    source=(ROOT/"frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "function App()" in source
    for forbidden in (
        "function Today(",
        "function Research(",
        "function Studio(",
        "function BlindEval(",
        "function Sources(",
        "function System(",
    ):
        assert forbidden not in source


def test_web_is_composition_root_not_business_route_monolith():
    source=(ROOT/"src/trendradar/web.py").read_text(encoding="utf-8")
    assert "build_editorial_router" in source
    assert "build_content_router" in source
    assert "build_ops_router" in source
    for forbidden in (
        "from .writing import",
        "from .content import",
        "from .evaluation import",
        '@app.post("/api/candidates',
        '@app.post("/api/documents',
    ):
        assert forbidden not in source


def test_legacy_parallel_product_tree_is_not_present():
    assert not (ROOT/"coin-workbench").exists()
