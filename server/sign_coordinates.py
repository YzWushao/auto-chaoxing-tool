"""Python adaptation of coordtransform's WGS84 -> GCJ02 -> BD09 formulas.

Copyright (c) 2015 记忆的残骸, MIT; see licenses/coordtransform-MIT.txt.
Adapted 2026-10-27. QQ uses the same BD-09 default as the web signing form.
"""
import math


def location_parameters(point):
    lng, lat = float(point['longitude']), float(point['latitude'])
    if not math.isfinite(lng) or not math.isfinite(lat) or abs(lng) > 180 or abs(lat) > 90:
        raise ValueError('预设点位坐标无效，请在设置中修正')
    system = point.get('coordinate_system', 'bd09')
    if system not in {'bd09', 'gcj02', 'wgs84'}:
        raise ValueError('预设点位坐标系无效')
    if system == 'wgs84' and 73.66 < lng < 135.05 and 3.86 < lat < 53.55:
        x, y, pi = lng - 105, lat - 35, math.pi
        dlat = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
        dlat += (20*math.sin(6*x*pi) + 20*math.sin(2*x*pi))*2/3
        dlat += (20*math.sin(y*pi) + 40*math.sin(y/3*pi))*2/3
        dlat += (160*math.sin(y/12*pi) + 320*math.sin(y*pi/30))*2/3
        dlng = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
        dlng += (20*math.sin(6*x*pi) + 20*math.sin(2*x*pi))*2/3
        dlng += (20*math.sin(x*pi) + 40*math.sin(x/3*pi))*2/3
        dlng += (150*math.sin(x/12*pi) + 300*math.sin(x/30*pi))*2/3
        rad = lat*pi/180
        magic = 1-0.00669342162296594323*math.sin(rad)**2
        dlat = dlat*180/((6378245*(1-0.00669342162296594323))/(magic*math.sqrt(magic))*pi)
        dlng = dlng*180/(6378245/math.sqrt(magic)*math.cos(rad)*pi)
        lng, lat = lng+dlng, lat+dlat
    if system != 'bd09':
        xpi = math.pi*3000/180
        z = math.sqrt(lng*lng+lat*lat) + 0.00002*math.sin(lat*xpi)
        angle = math.atan2(lat,lng) + 0.000003*math.cos(lng*xpi)
        lng, lat = z*math.cos(angle)+0.0065, z*math.sin(angle)+0.006
    return {'longitude': f'{lng:.6f}', 'latitude': f'{lat:.6f}', 'address': point['address']}
