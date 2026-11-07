"""The historical driver contract must reject changes before native execution."""
import asyncio
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image

@pytest.mark.parametrize('driver,limits,expected', [
    ('610.57.04', 'matches_requested_hard_limits', 'hardware mismatch'),
    ('580.95.05', 'unavailable', 'Unable to confirm'),
    ('580.95.05', 'matches_requested_hard_limits', None),
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
        assert result['hardware']=='NVIDIA A10, 580.95.05'
    if driver!='580.95.05': assert calls==[]
