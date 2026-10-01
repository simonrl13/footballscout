from scout.check_env import problems

SECRET = "sk-ant-api03-THIS-IS-A-FAKE-TEST-VALUE"


def test_flags_missing_equals_without_echoing_content(capsys):
    text = f"# comment\nPOSTGRES_DB=scout\nANTHROPIC_API_KEY{SECRET}\nLOADER_DATABASE_URL=postgresql://u:p@127.0.0.1:5432/scout\n"
    found = problems(text)
    assert found == [(3, "missing '=' between name and value")]
    assert all(SECRET not in what for _, what in found)


def test_flags_spaces_and_quotes():
    found = dict(problems('A = 1\nB= 2\nC="quoted value"\nD=ok\n'))
    assert set(found) == {1, 2, 3}


def test_clean_file_passes():
    assert problems("# x\n\nA=1\nB=postgresql://u:p@127.0.0.1:5432/db\nC=false   # inline comment\n") == []
