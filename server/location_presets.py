"""School/teaching-building map presets only; never account or study configuration."""
import math

SYSTEMS = {'bd09', 'gcj02', 'wgs84'}


def validate_school(value):
    if not isinstance(value, dict) or set(value) - {'version', 'school', 'coordinate_system', 'points'}:
        raise ValueError('配置只支持 version、school、coordinate_system 和 points 字段')
    if type(value.get('version', 1)) is not int or value.get('version', 1) != 1:
        raise ValueError('不支持的点位配置版本，需要 version: 1')
    def text(raw, label, maximum):
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > maximum:
            raise ValueError(f'{label}需要为 1～{maximum} 个字符的文本')
        return raw.strip()
    school = text(value.get('school'), '学校名称', 100)
    system = value.get('coordinate_system')
    if not isinstance(system, str) or system not in SYSTEMS:
        raise ValueError('coordinate_system 必须为 bd09、gcj02 或 wgs84，不能混用坐标系')
    points = value.get('points')
    if not isinstance(points, list):
        raise ValueError('points 必须为点位列表，可为空')
    result, names = [], set()
    for item in points:
        if not isinstance(item, dict) or set(item) - {'name', 'longitude', 'latitude', 'address', 'coordinate_system'}:
            raise ValueError('点位包含不支持的字段')
        name = text(item.get('name'), '教学楼 / 教学区名称', 100)
        if name in names:
            raise ValueError(f'点位名称重复：{name}')
        names.add(name)
        coords = {}
        for key, limit in [('longitude', 180), ('latitude', 90)]:
            raw = item.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)) or (isinstance(raw, str) and not raw.strip()):
                raise ValueError(f'{name} 的 {key} 无效')
            try:
                number = float(raw)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f'{name} 的 {key} 无效') from None
            if not math.isfinite(number) or abs(number) > limit:
                raise ValueError(f'{name} 的 {key} 超出范围')
            coords[key] = number
        address = text(item.get('address', f'{school} · {name}'), '位置说明', 200)
        point_system = item.get('coordinate_system', system)
        if not isinstance(point_system, str) or point_system not in SYSTEMS:
            raise ValueError('点位坐标系必须为 bd09、gcj02 或 wgs84')
        result.append({'name': name, **coords, 'address': address, 'coordinate_system': point_system})
    return {'version': 1, 'school': school, 'coordinate_system': system, 'points': result}


def validate_import(value):
    if isinstance(value, dict) and 'schools' in value:
        if set(value) - {'version', 'schools'} or type(value.get('version',1)) is not int or value.get('version', 1) != 1:
            raise ValueError('不支持的配置格式')
        schools = value['schools']
        if not isinstance(schools, list):
            raise ValueError('schools 需要包含学校配置')
        result = [validate_school(s) for s in schools]
    else:
        result = [validate_school(value)]
    if len({s['school'] for s in result}) != len(result):
        raise ValueError('导入文件含重复学校名称')
    return result
