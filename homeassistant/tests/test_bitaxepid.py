"""End-to-end tests of the integration against a real Home Assistant core."""
from datetime import timedelta

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.bitaxepid.const import (
    CONF_SCAN_INTERVAL,
    CONF_VARIABLES,
    DOMAIN,
    VARIABLES,
)

URL = "http://10.0.0.5:8093/metrics"
MAC1 = "AA:BB:CC:DD:EE:01"
MAC2 = "AA:BB:CC:DD:EE:02"


def miner(mac, temp=61.5):
    # Same keys as the metrics dict built in bitaxepid.py start_tuning().
    return {
        "mac_address": mac,
        "timestamp": "2026-11-03 10:00:00",
        "target_frequency": 640,
        "target_voltage": 1150.0,
        "hashrate": 1234.5,
        "temp": temp,
        "pid_settings": {"CONTROL_STRATEGY": "tcontrol", "TARGET_TEMP": 65.0},
        "power": 18.2,
        "board_voltage": 5100,
        "current": 3600,
        "core_voltage_actual": 1138,
        "frequency": 640,
        "fanrpm": 4200,
    }


def entry(variables=None, **extra):
    data = {CONF_HOST: "10.0.0.5", CONF_PORT: 8093, CONF_SCAN_INTERVAL: 30,
            CONF_VARIABLES: list(VARIABLES) if variables is None else variables, **extra}
    return MockConfigEntry(domain=DOMAIN, data=data, unique_id="10.0.0.5:8093")


def ids(hass, mac):
    reg = er.async_get(hass)
    m = mac.lower()
    return {e.unique_id.split("_", 1)[1]: e.entity_id
            for e in reg.entities.values() if e.unique_id.startswith(m)}


async def test_config_flow_creates_entry(hass, aioclient_mock):
    aioclient_mock.get(URL, json={"endpoints": []})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        CONF_HOST: " 10.0.0.5 ", CONF_PORT: 8093.0, CONF_SCAN_INTERVAL: 15.0,
        CONF_VARIABLES: ["temp", "hashrate"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "10.0.0.5", CONF_PORT: 8093,
                              CONF_SCAN_INTERVAL: 15, CONF_VARIABLES: ["hashrate", "temp"]}


async def test_config_flow_cannot_connect(hass, aioclient_mock):
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        CONF_HOST: "10.0.0.5", CONF_PORT: 8093, CONF_SCAN_INTERVAL: 30, CONF_VARIABLES: ["temp"]})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_all_sensors_two_miners(hass, aioclient_mock):
    aioclient_mock.get(URL, json={"endpoints": [miner(MAC1), miner(MAC2, temp=70)]})
    e = entry(); e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    one, two = ids(hass, MAC1), ids(hass, MAC2)
    assert set(one) == set(VARIABLES) == set(two)
    assert hass.states.get(one["temp"]).state == "61.5"
    assert hass.states.get(two["temp"]).state == "70.0"
    assert hass.states.get(one["temp"]).attributes["unit_of_measurement"] == "°C"
    assert hass.states.get(one["hashrate"]).state == "1234.5"
    cs = hass.states.get(one["control_strategy"])
    assert cs.state == "tcontrol" and cs.attributes["TARGET_TEMP"] == 65.0
    assert hass.states.get(one["timestamp"]).state == "2026-11-03 10:00:00"
    print({k: hass.states.get(v).state for k, v in one.items()})
    print(sorted(one.values()))


async def test_disabled_variables_not_created(hass, aioclient_mock):
    aioclient_mock.get(URL, json={"endpoints": [miner(MAC1)]})
    e = entry(variables=["temp", "power"]); e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    assert set(ids(hass, MAC1)) == {"temp", "power"}


async def test_options_change_removes_unticked_and_sets_interval(hass, aioclient_mock):
    aioclient_mock.get(URL, json={"endpoints": [miner(MAC1)]})
    e = entry(); e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(e.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_HOST: "10.0.0.5", CONF_PORT: 8093, CONF_SCAN_INTERVAL: 10, CONF_VARIABLES: ["temp"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert set(ids(hass, MAC1)) == {"temp"}
    assert e.runtime_data.update_interval == timedelta(seconds=10)


async def test_options_port_change(hass, aioclient_mock):
    aioclient_mock.get(URL, json={"endpoints": [miner(MAC1)]})
    aioclient_mock.get("http://10.0.0.6:8091/metrics", json={"endpoints": [miner(MAC1, temp=50)]})
    e = entry(variables=["temp"]); e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(e.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_HOST: "10.0.0.6", CONF_PORT: 8091, CONF_SCAN_INTERVAL: 30, CONF_VARIABLES: ["temp"]})
    await hass.async_block_till_done()
    assert hass.states.get(ids(hass, MAC1)["temp"]).state == "50.0"


async def test_new_miner_appears_and_outage(hass, aioclient_mock):
    aioclient_mock.get(URL, json={"endpoints": []})
    e = entry(variables=["temp"]); e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    assert ids(hass, MAC1) == {}
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json={"endpoints": [miner(MAC1)]})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    eid = ids(hass, MAC1)["temp"]
    assert hass.states.get(eid).state == "61.5"
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=62))
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == STATE_UNAVAILABLE


async def test_setup_retries_when_unreachable(hass, aioclient_mock):
    aioclient_mock.get(URL, exc=aiohttp.ClientError())
    e = entry(); e.add_to_hass(hass)
    await hass.config_entries.async_setup(e.entry_id)
    assert e.state is config_entries.ConfigEntryState.SETUP_RETRY
