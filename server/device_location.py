"""Validate an explicit native-device fix; kept only for the current scan run."""
import math
import time

from .sign_coordinates import location_parameters


def device_location(value, *, input_mode, preset=None):
    if value is None:
        return None
    if input_mode != 'native' or preset is not None:
        raise ValueError('设备位置仅用于原生扫码，不能与预设点位同时选择')
    if not isinstance(value, dict) or set(value) != {'latitude','longitude','accuracy','captured_at'}:
        raise ValueError('设备定位格式无效')
    try:
        valid=all(type(v) in (int,float) and math.isfinite(v) for v in value.values())
    except OverflowError:
        valid=False
    if not valid:
        raise ValueError('设备定位数值无效')
    lat, lng = value['latitude'], value['longitude']
    if not -90 <= lat <= 90 or not -180 <= lng <= 180 or not 0 < value['accuracy'] <= 100000:
        raise ValueError('设备定位范围无效')
    if not -10 <= time.time()-value['captured_at'] <= 60:
        raise ValueError('设备定位已过期，请重新获取当前位置')
    return {'device': location_parameters(dict(latitude=lat, longitude=lng, coordinate_system='wgs84',
        address=f'设备当前位置（{lng:.6f}, {lat:.6f}）'))}
