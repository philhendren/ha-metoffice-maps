"""Where frames are kept."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.metoffice_maps import storage

# Captured at import, before the autouse fixture points frame_root at a temp dir.
REAL_FRAME_ROOT = storage.frame_root


def test_frames_live_in_private_storage_not_www(hass: HomeAssistant) -> None:
    root = REAL_FRAME_ROOT(hass)
    assert root == Path(hass.config.config_dir) / ".storage" / "metoffice_maps"
    assert "www" not in root.parts


def test_file_names_are_safe(tmp_path: Path) -> None:
    files = storage.FrameFiles(tmp_path)
    files.ensure()
    files.write_raw("land_cover_ts0_+00", b"x")
    assert (tmp_path / "raw" / "land_cover_ts0_plus00.png").read_bytes() == b"x"
    assert files.read_frame("missing") is None
