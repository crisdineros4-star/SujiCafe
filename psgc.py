"""Offline address lists from the supplied Philippine address dataset.
Avoids network waits during registration. Delivery validation is separate.
"""
import json
from pathlib import Path
from functools import lru_cache
from flask import Blueprint, request, jsonify
bp = Blueprint('psgc', __name__, url_prefix='/psgc')

@lru_cache(maxsize=1)
def address_data():
    data = json.loads((Path(__file__).parent / 'data' / 'ph_address.json').read_text(encoding='utf-8'))
    places, barangays = [], {}
    for region in data['regions']:
        for province in region.get('provinces', [{'n': 'Metro Manila', 'cities': region.get('cities', [])}]):
            for city in province['cities']:
                code = str(len(places))
                places.append(dict(c=code, n=city['n'], p=province['n'], r=region['n']))
                barangays[code] = city['b']
    return places, barangays

@bp.get('/places')
def places():
    response = jsonify(items=address_data()[0], src='local')
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    return response

@bp.get('/barangays')
def barangays():
    items = address_data()[1].get(request.args.get('c', ''), [])
    response = jsonify(items=[{'n': name} for name in items], src='local')
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    return response
