"""Smoke test: the package is installed in the venv and importable."""

from importlib.metadata import version


def test_package_imports():
    import agent_apunts

    assert agent_apunts.__name__ == "agent_apunts"


def test_package_is_installed():
    assert version("agent-apunts") == "0.1.0"
