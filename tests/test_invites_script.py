import importlib.util
import os

spec = importlib.util.spec_from_file_location("invites", os.path.join("scripts", "invites.py"))
invites = importlib.util.module_from_spec(spec)
spec.loader.exec_module(invites)


def test_new_then_list(dynamo_table, capsys):
    assert invites.main(["new", "--count", "2", "--note", "lab"]) == 0
    codes = capsys.readouterr().out.split()[:2]
    assert all(len(c) == 8 for c in codes)
    invites.main(["list"])
    out = capsys.readouterr().out
    assert all(c in out for c in codes) and out.count("unused") == 2
