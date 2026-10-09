from pathlib import Path

import pytest

from craft_dl import smb


def test_has_protocol_survives_path_collapsing() -> None:
    assert str(Path("smb://GoldenOak._smb._tcp.local/Shed/Apps")) == "smb:/GoldenOak._smb._tcp.local/Shed/Apps"
    assert smb.has_protocol(Path("smb://GoldenOak._smb._tcp.local/Shed/Apps"))
    assert smb.has_protocol("smb://host/share")
    assert not smb.has_protocol(Path("~/git/storytold"))
    assert not smb.has_protocol(Path("/Volumes/Shed"))


def test_parse() -> None:
    parsed = smb.parse(Path("smb://GoldenOak._smb._tcp.local/Shed/dir1/dir2"))
    assert parsed == smb.SmbPath("GoldenOak._smb._tcp.local", "Shed", "dir1/dir2")
    assert parsed.url == "smb://GoldenOak._smb._tcp.local/Shed"
    assert parsed.local_path == Path("/Volumes/Shed/dir1/dir2")
    assert smb.parse("smb://user@host/My Share").url == "smb://user@host/My%20Share"
    assert smb.parse("smb://host/Shed").local_path == Path("/Volumes/Shed")


@pytest.mark.parametrize("path", ["smb://host", "smb://host/", "smb:///share", "/Volumes/x"])
def test_parse_rejects_incomplete_paths(path: str) -> None:
    with pytest.raises(smb.SmbError):
        smb.parse(path)


def test_mount_opens_share_and_waits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smb, "VOLUMES", tmp_path)
    (tmp_path / "Shed" / "Apps").mkdir(parents=True)
    state = {"mounted": False, "opened": []}

    def fake_open(url: str) -> None:
        state["opened"].append(url)
        state["mounted"] = True

    monkeypatch.setattr(smb, "open_share", fake_open)
    monkeypatch.setattr(smb, "mounted_volumes", lambda: f"//host/Shed on {tmp_path}/Shed (smbfs)" if state["mounted"] else "")
    monkeypatch.setattr(smb.time, "sleep", lambda seconds: None)
    assert smb.mount(Path("smb://host._smb._tcp.local/Shed/Apps")) == tmp_path / "Shed" / "Apps"
    assert state["opened"] == ["smb://host._smb._tcp.local/Shed"]
    assert smb.mount(Path("smb://host._smb._tcp.local/Shed/Apps")) == tmp_path / "Shed" / "Apps"
    assert len(state["opened"]) == 1, "already mounted, so no second open"


def test_mount_times_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smb, "VOLUMES", tmp_path)
    monkeypatch.setattr(smb, "open_share", lambda url: None)
    monkeypatch.setattr(smb, "mounted_volumes", lambda: "")
    monkeypatch.setattr(smb.time, "sleep", lambda seconds: None)
    with pytest.raises(smb.SmbError, match="timed out"):
        smb.mount("smb://host/Shed/Apps", timeout=3)
