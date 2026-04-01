from jingyantai import __version__
from jingyantai.cli import app


def test_package_exposes_version_and_cli_name():
    assert __version__ == "0.1.0"
    assert app.info.name == "jingyantai"
