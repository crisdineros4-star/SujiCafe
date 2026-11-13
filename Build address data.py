"""Makes data/ph_address.json: every region, province, city / municipality and barangay of the Philippines.

Run it ONE time on a PC that has internet, from this folder:

    python build_address_data.py

After that the site works fully offline. The data comes from the public PSGC list
(https://psgc.gitlab.io/api). Run it again only if you want newer data.
"""
import json, os, sys, time, urllib.request

BASE = 'https://psgc.gitlab.io/api'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ph_address.json')


def fetch(name):
    last = None
    for url in (f'{BASE}/{name}/', f'{BASE}/{name}.json'):
        for _ in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'SujiCafe/1.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read().decode('utf-8'))
                if isinstance(data, list) and data: return data
            except Exception as e:
                last = e; time.sleep(2)
    raise SystemExit(f'Could not download {name} ({last}). Check the internet connection and try again.')


def code(v):
    return str(v) if v else ''


def build(regions, provinces, cities, barangays):
    brgys = {}
    for b in barangays:
        parent = code(b.get('cityCode')) or code(b.get('municipalityCode'))
        if parent and b.get('name'): brgys.setdefault(parent, []).append(b['name'])

    reg_nodes, reg_by = [], {}
    for r in regions:
        name = f"{r['name']} ({r['regionName']})" if r.get('regionName') and r.get('name') else (r.get('regionName') or r.get('name'))
        node = {'n': name, 'provinces': [], 'cities': []}
        reg_nodes.append(node); reg_by[code(r['code'])] = node
    prov_by = {}
    for p in provinces:
        reg = reg_by.get(code(p.get('regionCode')))
        if not reg: continue
        node = {'n': p['name'], 'cities': []}
        reg['provinces'].append(node); prov_by[code(p['code'])] = node

    for c in cities:
        item = {'n': c['name'], 'b': sorted(set(brgys.get(code(c['code']), [])), key=str.lower)}
        prov = prov_by.get(code(c.get('provinceCode')))
        reg = reg_by.get(code(c.get('regionCode')))
        if prov: prov['cities'].append(item)
        elif reg: reg['cities'].append(item)

    for reg in reg_nodes:
        if reg['provinces'] and reg['cities']:           # cities that belong to no province of a region that has provinces
            reg['provinces'].append({'n': 'Independent / Highly Urbanized Cities', 'cities': reg['cities']})
            reg['cities'] = []
        for node in reg['provinces'] + [reg]:
            node['cities'].sort(key=lambda x: x['n'].lower())
        reg['provinces'].sort(key=lambda x: x['n'].lower())
        if not reg['provinces']: del reg['provinces']
        if not reg['cities']: del reg['cities']
    return {'regions': reg_nodes}


def main():
    print('Downloading the Philippine address lists (one time only)...')
    parts = {}
    for n in ('regions', 'provinces', 'cities-municipalities', 'barangays'):
        print('  ', n, '...', end=' ', flush=True)
        parts[n] = fetch(n); print(len(parts[n]))
    data = build(parts['regions'], parts['provinces'], parts['cities-municipalities'], parts['barangays'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)                      # the site only ever sees a finished file
    nb = sum(len(c['b']) for r in data['regions'] for c in (r.get('cities', []) + [c for p in r.get('provinces', []) for c in p['cities']]))
    print(f"Done: {len(data['regions'])} regions, {nb} barangays saved to data/ph_address.json")
    print('Restart the site (flask run --debug) and press Ctrl+F5.')


if __name__ == '__main__':
    main()