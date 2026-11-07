"""The historical driver contract must reject changes before native execution."""
import asyncio
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image

@pytest.mark.parametrize('driver,limits,expected', [
    ('580.95.05', 'matches_requested_hard_limits', 'hardware mismatch'),
    ('610.57.04', 'unavailable', 'Unable to confirm'),
    ('610.57.04', 'matches_requested_hard_limits', None),
])
def test_actual_hardware_contract(monkeypatch, driver, limits, expected):
    calls=[]
    async def gpu(sb): return ('NVIDIA A10', driver)
    async def placement(sb):
        calls.append('placement')
        return {'cloud_provider':'oci', 'region':'eu-west'}
    async def resources(sb):
        calls.append('resources')
        return {'measured':{'limit_check':limits}}
    monkeypatch.setattr(image,'inspect_gpu',gpu)
    monkeypatch.setattr(image,'inspect_placement',placement)
    monkeypatch.setattr(image,'inspect_resources',resources)
    if expected:
        with pytest.raises(RuntimeError,match=expected):asyncio.run(image.verify_hardware(object()))
    else:
        result=asyncio.run(image.verify_hardware(object()))
        assert result['hardware']=='NVIDIA A10, 610.57.04'
    if driver!='610.57.04': assert calls==[]


def test_exploratory_driver_retains_gpu_and_resource_checks(monkeypatch):
    async def gpu(sb): return ('NVIDIA A10', '580.95.05')
    async def placement(sb): return {'cloud_provider':'oci','region':'eu-west'}
    async def resources(sb): return {'measured':{'limit_check':'matches_requested_hard_limits'}}
    monkeypatch.setattr(image,'inspect_gpu',gpu)
    monkeypatch.setattr(image,'inspect_placement',placement)
    monkeypatch.setattr(image,'inspect_resources',resources)
    result=asyncio.run(image.verify_hardware(object(), driver_policy='observed'))
    assert result['driver_matches_reference'] is False
    assert result['driver_policy']=='observed'
    async def wrong_gpu(sb): return ('NVIDIA A100','580.95.05')
    monkeypatch.setattr(image,'inspect_gpu',wrong_gpu)
    with pytest.raises(RuntimeError,match='hardware mismatch'):
        asyncio.run(image.verify_hardware(object(), driver_policy='observed'))
