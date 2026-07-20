import pytest

from other_cluster.cli.main import main


def test_help_lists_planned_commands(capsys):
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    for command in ("template", "validate", "estimate", "preview", "run", "cache"):
        assert command in output
