"""The frame and frames.json views."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .helpers import API_KEY, FakeDataHub, make_entry, setup_entry


async def loaded(hass: HomeAssistant):
    await async_setup_component(hass, "http", {})
    entry = make_entry()
    await setup_entry(hass, entry)
    return entry


async def test_auth_required(
    hass: HomeAssistant, datahub: FakeDataHub, hass_client_no_auth
) -> None:
    entry = await loaded(hass)
    client = await hass_client_no_auth()
    for path in (
        f"/api/metoffice_maps/{entry.entry_id}/frame/11.png",
        f"/api/metoffice_maps/{entry.entry_id}/frames.json",
    ):
        assert (await client.get(path)).status == 401


async def test_signed_path_works_without_a_token(
    hass: HomeAssistant, datahub: FakeDataHub, hass_client_no_auth
) -> None:
    entry = await loaded(hass)
    state = hass.states.get("sensor.met_office_maps_o000000000001_rain_forecast")
    url = state.attributes["frames"][0]["url"]
    client = await hass_client_no_auth()
    resp = await client.get(url)
    assert resp.status == 200
    assert resp.content_type == "image/png"
    body = await resp.read()
    assert body.startswith(b"\x89PNG")
    assert API_KEY.encode() not in body
    assert entry.entry_id in url


async def test_frame_with_etag(hass: HomeAssistant, datahub: FakeDataHub, hass_client) -> None:
    entry = await loaded(hass)
    client = await hass_client()
    resp = await client.get(f"/api/metoffice_maps/{entry.entry_id}/frame/12.png")
    assert resp.status == 200
    etag = resp.headers["ETag"]
    assert etag == '"2026110400-12"'
    assert resp.headers["Cache-Control"] == "private, no-cache"
    again = await client.get(
        f"/api/metoffice_maps/{entry.entry_id}/frame/12.png", headers={"If-None-Match": etag}
    )
    assert again.status == 304


async def test_unknown_frames_are_404(
    hass: HomeAssistant, datahub: FakeDataHub, hass_client
) -> None:
    entry = await loaded(hass)
    client = await hass_client()
    for path in (
        f"/api/metoffice_maps/{entry.entry_id}/frame/3.png",  # not on show
        f"/api/metoffice_maps/{entry.entry_id}/frame/x.png",
        "/api/metoffice_maps/nope/frame/11.png",
        "/api/metoffice_maps/nope/frames.json",
    ):
        assert (await client.get(path)).status == 404, path


async def test_frame_missing_on_disk_is_404(
    hass: HomeAssistant, datahub: FakeDataHub, hass_client
) -> None:
    entry = await loaded(hass)
    entry.runtime_data.coordinator.files.clear_frames()
    client = await hass_client()
    assert (await client.get(f"/api/metoffice_maps/{entry.entry_id}/frame/11.png")).status == 404


async def test_unloaded_entry_is_404(
    hass: HomeAssistant, datahub: FakeDataHub, hass_client
) -> None:
    entry = await loaded(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    client = await hass_client()
    assert (await client.get(f"/api/metoffice_maps/{entry.entry_id}/frame/11.png")).status == 404


async def test_frames_json(hass: HomeAssistant, datahub: FakeDataHub, hass_client) -> None:
    entry = await loaded(hass)
    client = await hass_client()
    resp = await client.get(f"/api/metoffice_maps/{entry.entry_id}/frames.json")
    assert resp.status == 200
    data = await resp.json()
    assert data["run"] == "2026-11-04T00:00:00+00:00"
    assert [f["valid_time"][11:16] for f in data["frames"]] == [
        "11:00",
        "12:00",
        "13:00",
        "14:00",
        "15:00",
        "16:00",
    ]
    assert all("authSig=" in f["url"] for f in data["frames"])
    assert API_KEY not in await resp.text()


async def test_frames_json_with_no_frames(
    hass: HomeAssistant, datahub: FakeDataHub, hass_client
) -> None:
    datahub.fail_next = [500]
    entry = await loaded(hass)
    client = await hass_client()
    data = await (await client.get(f"/api/metoffice_maps/{entry.entry_id}/frames.json")).json()
    assert data == {"run": None, "frames": []}
