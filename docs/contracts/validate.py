"""Validate the S0 contract bundle offline. This does not run a backend."""
import copy
import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path
from urllib.parse import quote

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CON = Path(__file__).resolve().parent
FIX = CON.parents[1] / 'data/fixtures/s0'
PIN = '680a9f1bbc5748c9f228cdd5bc9da61a9e2b37bf'
FORMATS = FormatChecker()
NS = {'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdfs': 'http://www.w3.org/2000/01/rdf-schema#', 'sosa': 'http://www.w3.org/ns/sosa/', 'ssn': 'http://www.w3.org/ns/ssn/', 'qudt': 'http://qudt.org/schema/qudt/', 'unit': 'http://qudt.org/vocab/unit/', 'prov': 'http://www.w3.org/ns/prov#', 'dct': 'http://purl.org/dc/terms/', 'xsd': 'http://www.w3.org/2001/XMLSchema#'}
BASE = 'https://flameinfreefall.local/resource/'
VOCAB = 'https://flameinfreefall.local/vocab/'
UNITS = {'percent': 'PERCENT', 'kPa': 'KiloPA', 'cm/s': 'CentiM-PER-SEC', 's': 'SEC', 'mm': 'MilliM', 'cm': 'CentiM', 'mm/s': 'MilliM-PER-SEC'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registry():
    result = Registry()
    paths = [*sorted((CON / 'schemas').glob('*.schema.json')), CON / 'storage-input.schema.json', CON / 'openapi.json', CON / 'openapi-document.schema.json']
    for path in paths:
        document = read(path)
        resource = Resource.from_contents(document, default_specification=DRAFT202012)
        aliases = [path.as_uri()]
        if path.parent == CON:
            aliases.append('https://flameinfreefall.local/contracts/' + path.name)
        if '$id' in document:
            aliases.append(document['$id'])
        if path.parent.name == 'schemas':
            aliases.append('https://flameinfreefall.local/contracts/schemas/' + path.name)
        for alias in aliases:
            result = result.with_resource(alias, resource)
    return result


REGISTRY = registry()


def validate(instance, path, pointer=''):
    target = path.as_uri() + ('#' + pointer if pointer else '')
    Draft202012Validator({'$ref': target}, registry=REGISTRY, format_checker=FORMATS).validate(instance)


def schema_checks():
    provenance = read(CON / 'schemas/provenance.json')
    require(provenance['commit'] == PIN and len(provenance['files']) == 8, 'Wrong upstream schema pin')
    for entry in provenance['files']:
        path = CON / entry['path']
        raw = path.read_bytes()
        require(sha(path) == entry['sha256'], 'Changed upstream schema: ' + path.name)
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        require(blob == entry['git_blob_sha1'], 'Git blob mismatch: ' + path.name)
        Draft202012Validator.check_schema(read(path))
    spec_source = read(CON / 'openapi-document.provenance.json')
    require(sha(CON / 'openapi-document.schema.json') == spec_source['sha256'], 'Changed OpenAPI document schema')
    validate(read(CON / 'openapi.json'), CON / 'openapi-document.schema.json')
    Draft202012Validator.check_schema(read(CON / 'storage-input.schema.json'))
    api = read(CON / 'openapi.json')
    for schema in api['components']['schemas'].values():
        Draft202012Validator.check_schema(schema)

    def refs(value, base):
        if isinstance(value, dict):
            base = value.get('$id', base)
            if '$ref' in value:
                REGISTRY.resolver(base).lookup(value['$ref'])
            for item in value.values():
                refs(item, base)
        elif isinstance(value, list):
            for item in value:
                refs(item, base)

    for path in [*sorted((CON / 'schemas').glob('*.schema.json')), CON / 'storage-input.schema.json', CON / 'openapi.json']:
        refs(read(path), path.as_uri())


def manifest_checks():
    manifest = read(FIX / 'manifest.json')
    require(manifest['schema_commit'] == PIN, 'Wrong fixture pin')
    require(manifest['scientific_review']['status'] == 'pending', 'Fixture approval was fabricated')
    listed = {entry['path'] for entry in manifest['artifacts']}
    actual = {p.relative_to(FIX).as_posix() for p in FIX.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    require(listed == actual and len(listed) == len(manifest['artifacts']), 'Artifact inventory differs')
    for entry in [*manifest['artifacts'], *manifest['sources']]:
        path = (FIX / entry['path']).resolve()
        require(path.is_relative_to(FIX.resolve()), 'Artifact path escapes fixture directory')
        require(sha(path) == entry['sha256'], 'Hash mismatch: ' + entry['path'])
    return manifest


def evidence_checks(card, packet, metadata):
    require(card['accession'] == packet['investigation'] == metadata['accession'], 'Investigation mismatch')
    require(card['source_version'] == packet['metadata_version'] == metadata['version'], 'Metadata version mismatch')
    require(card['title'] == packet['title'] == metadata['title'], 'Title mismatch')
    require(card['acronym'] == packet['acronym'] == metadata['investigationAcronym'], 'Acronym mismatch')
    passages = {p['id']: p for p in packet['passages']}
    require(len(passages) == len(packet['passages']), 'Duplicate passage ID')
    for p in passages.values():
        require(p['id'] == card['accession'] + ':meta:' + p['locator']['field'], 'Passage ID/locator mismatch')
        require(p['text'] == metadata[p['locator']['field']], 'Passage differs from saved metadata')
    evidence = {e['id']: e for e in card['evidence']}
    require(len(evidence) == len(card['evidence']), 'Duplicate evidence ID')
    for e in evidence.values():
        p = passages[e['passage_id']]
        suffix = hashlib.sha256(' '.join(e['excerpt'].split()).encode()).hexdigest()[:12]
        require(e['id'] == p['id'] + '#' + suffix, 'Evidence suffix mismatch')
        require(e['excerpt'] in p['text'], 'Unsupported excerpt')
        require(e['locator'] == p['locator'] and e['investigation'] == card['accession'], 'Evidence locator mismatch')
        require(e['source_url'] == packet['source_url'], 'Evidence URL mismatch')

    def citations(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'evidence_ids':
                    require(all(eid in evidence for eid in item), 'Unresolved evidence reference')
                else:
                    citations(item)
        elif isinstance(value, list):
            for item in value:
                citations(item)

    citations(card)
    claims = {c['id']: c for c in card['claims']}
    require(len(claims) == len(card['claims']), 'Duplicate claim ID')
    for finding in card['findings']:
        require(claims[finding['observation']]['type'] == 'reported_observation', 'Wrong finding observation type')
        require(claims[finding['implication']]['type'] == 'potential_application', 'Wrong finding implication type')
    require(card['summary']['text'] == metadata['objective'], 'Fixture summary must quote the objective')
    require(len(card['claims']) == 1 and card['claims'][0]['type'] == 'objective' and card['claims'][0]['text'] == metadata['objective'], 'Fixture invented a finding')
    require(not card['findings'] and not card['safety_categories'], 'Fixture invented a safety assertion')
    require(card['review']['status'] == 'pending' and card['review']['reviewer'] is None, 'Fixture review is not pending')


def check_measure(value, expected, unit, column, row):
    require(value['unit'] == unit and value['columns'] == [column], 'Quantity unit/source mismatch')
    require(value['quote'] == row[column], 'Quantity quote mismatch')
    for bound in ['min', 'max']:
        got = value[bound]
        require(got is None if expected is None else got is not None and math.isclose(got, expected, rel_tol=0, abs_tol=1e-9), 'Numeric conversion mismatch: ' + column)


def table_checks(table, manifest):
    source = table['source']
    entry = next(e for e in manifest['sources'] if e['path'] == 'sources/' + source['filename'])
    require(source['sha256'] == entry['sha256'], 'Run source hash mismatch')
    require(source['encoding'] == entry['encoding'], 'Run source encoding mismatch')
    reader = csv.DictReader(io.StringIO((FIX / entry['path']).read_bytes().decode(source['encoding']), newline=''))
    rows = list(reader)
    require(reader.fieldnames == source['columns'], 'CSV headers changed')
    require(len(rows) == entry['source_data_rows'], 'Source row count changed')
    require([r['row'] for r in table['records']] == entry['selected_rows'], 'Selected source rows changed')
    require(table['counts'] == {'runs': len(table['records']), 'notes': 0, 'empty_rows_skipped': 0}, 'Subset counts changed')
    for record in table['records']:
        row = rows[record['row'] - 1]
        require(record['original'] == row, 'Original source cells changed')
        require(record['id'] == f"{table['investigation']}:{table['table']}:{record['row']}", 'Row identity changed')
        require(record['review_status'] == 'pending', 'Run review is not pending')
        cond = record['conditions']
        values = [*cond.values(), *(o['result'] for o in record['outcomes'])]
        for value in values:
            require(value['review_status'] == 'pending', 'Value approval was fabricated')
            require(all(c in row for c in value['columns']), 'Unknown source column')
            if value['columns']:
                require(len(value['columns']) == 1 and value['quote'] == row[value['columns'][0]], 'Value quote is not exact')
            if 'min' in value:
                require(value['min'] is None and value['max'] is None or value['min'] is not None and value['max'] is not None and value['min'] <= value['max'], 'Invalid quantity bounds')
        for field in ['fuel_class', 'geometry', 'flow_direction', 'diluent']:
            require(cond[field]['value'] is None and cond[field]['method'] == 'unknown', 'Unreviewed categorical inference')
        if table['investigation'] == 'PSI-69':
            require(cond['material']['value'] == row['Fuel'], 'FLEX material changed')
            check_measure(cond['o2_percent'], float(row['O initial ambient composition; mole fraction']) * 100, 'percent', 'O initial ambient composition; mole fraction', row)
            pressure = float(row['Ambient pressure; mmHg'])
            check_measure(cond['pressure_kpa'], round(pressure * 101.325 / 760, 9) if pressure > 0 else None, 'kPa', 'Ambient pressure; mmHg', row)
            require(cond['flow_cm_s']['min'] is None, 'FLEX flow was invented')
            require([o['type'] for o in record['outcomes']] == ['burn_time', 'extinction_diameter', 'test_end'], 'FLEX outcome fields changed')
            require(all(o['gravity'] == 'microgravity' for o in record['outcomes']), 'FLEX gravity changed')
            for outcome, column, unit in zip(record['outcomes'][:2], ['Burn time; s', 'Visible flame extinction diameter; mm'], ['s', 'mm']):
                check_measure(outcome['result'], float(row[column]) if row[column] else None, unit, column, row)
            require(record['outcomes'][2]['result']['value'] == row['Test end'], 'FLEX test-end text changed')
        else:
            require(cond['material']['value'] == (row['Material'] or None), 'Blank material was inherited')
            check_measure(cond['o2_percent'], float(row['Percent O2 (Note 1)'].replace('~', '').strip()), 'percent', 'Percent O2 (Note 1)', row)
            require(cond['o2_percent']['qualifier'] == 'approximate', 'Approximation lost')
            check_measure(cond['flow_cm_s'], float(row['Air Flow (cm/s)'].split()[0]), 'cm/s', 'Air Flow (cm/s)', row)
            require(cond['pressure_kpa']['min'] is None, 'Saffire pressure was invented')
            expected = [('burn_time', 'microgravity', 'Burn Time (s)', 's'), ('burn_length', 'microgravity', '?-g Burn Length', 'cm'), ('burn_length', 'normal', '1-g Burn Length', 'cm'), ('spread_rate', 'normal', '1-g Spread Rate', 'mm/s')]
            require(len(record['outcomes']) == len(expected), 'Paired outcomes missing')
            for outcome, (kind, gravity, column, unit) in zip(record['outcomes'], expected):
                require((outcome['type'], outcome['gravity']) == (kind, gravity), 'Outcome gravity/type changed')
                if row[column].endswith(' ' + unit):
                    check_measure(outcome['result'], float(row[column].split()[0]), unit, column, row)
                else:
                    require(outcome['result']['value'] == row[column], 'Qualitative outcome changed')


def input_checks(manifest):
    investigations = read(FIX / 'inputs/investigations.json')
    files = read(FIX / 'inputs/remote-files.json')
    validate(investigations, CON / 'storage-input.schema.json', '/$defs/investigations')
    validate(files, CON / 'storage-input.schema.json', '/$defs/remoteFiles')
    require(len({i['accession'] for i in investigations}) == len(investigations) == 2, 'Investigation identities differ')
    require(len({(f['accession'], f['file_id'], f['version']) for f in files}) == len(files) == 2, 'File identities differ')
    cards, tables = [], []
    downloads = read(FIX / 'sources/download-records.json')['files']
    for investigation in investigations:
        accession = investigation['accession']
        metadata = read(FIX / investigation['metadata_path'])
        provenance = read(FIX / 'sources' / (accession + '-provenance.json'))
        require(investigation['metadata_sha256'] == sha(FIX / investigation['metadata_path']) == provenance[0]['sha256'], 'Metadata hash mismatch')
        require(investigation['metadata_version'] == metadata['version'], 'Investigation version mismatch')
        require(investigation['snapshot_retrieved_at'] == provenance[0]['retrieved_at'] and investigation['source_url'] == provenance[0]['url'], 'Snapshot provenance mismatch')
        require(all(value == metadata[key] for key, value in investigation['scientific_metadata'].items()), 'Scientific metadata differs')
        card = read(FIX / 'inputs' / (accession + '-card.json'))
        packet = read(FIX / 'inputs' / (accession + '-evidence-packet.json'))
        table = read(FIX / 'inputs' / (accession + '-runs.json'))
        for instance, schema in [(card, 'research-card'), (packet, 'evidence-packet'), (table, 'run-table')]:
            validate(instance, CON / 'schemas' / (schema + '.schema.json'))
        require(packet['snapshot_retrieved_at'] == investigation['snapshot_retrieved_at'], 'Packet retrieval date differs')
        evidence_checks(card, packet, metadata)
        table_checks(table, manifest)
        file = next(f for f in files if f['accession'] == accession)
        source = next(e for e in manifest['sources'] if e['role'] == 'downloaded_table' and e['file']['id'] == file['file_id'])
        download = next(e for e in downloads if e['file']['id'] == file['file_id'])
        original = next(e for e in metadata['experimentalTable'] if e['_id']['$oid'] == file['file_id'])
        require(file['key'] == source['file']['key'] == original['s3_path'], 'File key mismatch')
        require(file['version'] == source['file']['version'] == original['version'], 'File version mismatch')
        require(file['bytes'] == original['file_size'] == (FIX / source['path']).stat().st_size, 'File size mismatch')
        require(file['download_sha256'] == download['sha256'] == source['sha256'], 'Downloaded bytes hash differs')
        require(file['filename'] == original['file_name'] and file['category'] == source['file']['category'], 'File display fields differ')
        require(file['access'] == ('hidden' if not original['visible'] else 'restricted' if original['restricted'] else 'public'), 'Access state differs')
        cards.append(card)
        tables.append(table)
    return investigations, files, cards, tables


def response_pointer(path, status):
    escaped = path.replace('~', '~0').replace('/', '~1')
    return f'/paths/{escaped}/get/responses/{status}/content/application~1json/schema'


def request_errors(case, operation):
    errors = set()
    allowed = {p['name']: p for p in operation['parameters'] if p['in'] == 'query'}
    for name, value in case['query'].items():
        if name not in allowed or not Draft202012Validator(allowed[name]['schema'], format_checker=FORMATS).is_valid(value):
            errors.add(name)
    for parameter in operation['parameters']:
        if parameter['in'] == 'path':
            value = case['path_parameters'].get(parameter['name'])
            if not Draft202012Validator(parameter['schema']).is_valid(value):
                errors.add(parameter['name'])
    for prefix in ['o2', 'pressure', 'flow']:
        low, high = prefix + '_min', prefix + '_max'
        if low in case['query'] and high in case['query'] and case['query'][low] > case['query'][high]:
            errors.update([low, high])
    return errors


def http_checks(files, cards, tables):
    api = read(CON / 'openapi.json')
    cases = read(FIX / 'expected/http.json')['cases']
    require(len(api['paths']) == 8, 'Endpoint inventory differs')
    require(len({c['name'] for c in cases}) == len(cases), 'Duplicate HTTP case name')
    runs = [r for table in tables for r in table['records']]
    evidence = {e['id']: e for card in cards for e in card['evidence']}
    covered = set()
    for case in cases:
        operation = api['paths'][case['path']]['get']
        covered.add(case['path'])
        require(case['method'] == 'GET', 'Unexpected HTTP method')
        validate(case['body'], CON / 'openapi.json', response_pointer(case['path'], case['status']))
        errors = request_errors(case, operation)
        require((case['status'] == 400) == bool(errors), 'Request/status validation disagrees: ' + case['name'])
        if errors:
            require(set(case['body']['error']['details']['parameters']) == errors, 'Invalid parameter list differs')
        request_path = case['path']
        for key, value in case['path_parameters'].items():
            request_path = request_path.replace('{' + key + '}', quote(value, safe=''))
        require(request_path == case['request_path'] and '#' not in request_path, 'Path ID was not percent encoded')
        if case['status'] != 200:
            continue
        data, meta, query = case['body']['data'], case['body']['meta'], case['query']
        if 'limit' in meta:
            require(meta['limit'] == query.get('limit', 20) and meta['offset'] == query.get('offset', 0), 'Pagination echo differs')
            require(len(data) <= meta['limit'], 'Response exceeds page size')
        if case['path'] == '/api/studies':
            terms = query.get('q', '').strip().casefold().split()
            matched = []
            for card in cards:
                content = ' '.join([card['title'], card['acronym'], card['summary']['text'], *(c['text'] for c in card['claims']), *(e['excerpt'] for e in card['evidence'])]).casefold()
                categories = [c['category'] for c in card['safety_categories']]
                if all(term in content for term in terms) and ('safety_category' not in query or query['safety_category'] in categories):
                    matched.append(card)
            require(meta['total'] == len(matched), 'Study total differs from supported query')
            require(data == matched[meta['offset']:meta['offset'] + meta['limit']], 'Study page differs')
            require(meta['query'] == query.get('q', '').strip() and meta['safety_category'] == query.get('safety_category'), 'Search metadata differs')
            if terms:
                require([m['accession'] for m in meta['matches']] == [c['accession'] for c in data], 'Missing search match metadata')
                for match in meta['matches']:
                    require(all(e == evidence[e['id']] for e in match['evidence']), 'Matching evidence was changed')
        elif case['path'] == '/api/studies/{accession}':
            require(data == next(c for c in cards if c['accession'] == case['path_parameters']['accession']), 'Card response changed upstream record')
        elif case['path'] == '/api/evidence/{id}':
            require(data == evidence[case['path_parameters']['id']], 'Evidence response changed upstream record')
        elif case['path'] == '/api/studies/{accession}/files':
            matched = [f for f in files if f['accession'] == case['path_parameters']['accession'] and query.get('filename', '').casefold() in f['filename'].casefold() and ('category' not in query or (f['category'] or '').casefold() == query['category'].casefold()) and ('extension' not in query or f['extension'] == query['extension'].lower())]
            require(meta['total'] == len(matched) and data == matched[meta['offset']:meta['offset'] + meta['limit']], 'File page/filter differs')
        elif case['path'] == '/api/runs':
            require(data == runs[meta['offset']:meta['offset'] + meta['limit']] and meta['total'] == len(runs), 'Run page differs')
            require(meta['sources'] == [{k: t[k] for k in ['investigation', 'table', 'source']} for t in tables], 'Run source context differs')
        elif case['path'] == '/api/runs/{id}':
            require(data == next(r for r in runs if r['id'] == case['path_parameters']['id']), 'Run response changed upstream record')
            table = next(t for t in tables if data['id'].startswith(t['investigation'] + ':' + t['table'] + ':'))
            require(meta['source'] == {k: table[k] for k in ['investigation', 'table', 'source']}, 'Run detail source differs')
        elif case['path'] == '/api/health':
            require(data['investigation_count'] == (len(cards) if data['catalog'] == 'loaded' else None), 'Health study count differs')
            require(data['run_record_count'] == (len(runs) if data['graph'] == 'loaded' else None), 'Health loaded row count differs')
            require(data['snapshot_date'] == '2026-11-14' and data['verified_run_count'] is None, 'Health snapshot/classification differs')
    require(covered == set(api['paths']), 'Missing endpoint examples')
    return len(cases)


def expand(term):
    prefix, suffix = term.split(':', 1)
    return NS[prefix] + suffix


def parse_rdf(content):
    # The fixture deliberately uses only absolute IRIs and escaped string literals.
    pattern = re.compile(r'^<([^<>\s]+)> <([^<>\s]+)> (<[^<>\s]+>|"(?:[^"\\\r\n]|\\["\\nrt]|\\u[0-9a-fA-F]{4})*"(?:\^\^<[^<>\s]+>)?) \.$')
    triples = set()
    for number, line in enumerate(content.splitlines(), 1):
        require(bool(pattern.fullmatch(line)), 'Invalid fixture Turtle subset at line ' + str(number))
        subject, predicate, value = pattern.fullmatch(line).groups()
        require(subject.startswith('https://') and predicate.startswith(('https://', 'http://')), 'RDF requires absolute identifiers')
        if value.startswith('"'):
            literal, _, datatype = value.partition('^^')
            parsed = json.loads(literal)
            if datatype:
                require(datatype == '<' + expand('xsd:decimal') + '>' and re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?', parsed), 'Invalid decimal literal')
        triples.add((subject, predicate, value))
    require(len(triples) == len(content.splitlines()), 'Duplicate RDF triples')
    return triples


def rdf_checks(tables, files, content=None):
    content = (FIX / 'expected/runs.ttl').read_text(encoding='utf-8') if content is None else content
    remaining = parse_rdf(content)
    total = len(remaining)

    def take(subject, predicate, value, literal=False, decimal=False):
        predicate = expand(predicate)
        if literal or decimal:
            target = json.dumps(str(value), ensure_ascii=True)
            if decimal:
                target += '^^<' + expand('xsd:decimal') + '>'
        else:
            if value.split(':')[0] in NS:
                value = expand(value)
            target = '<' + value + '>'
        triple = (subject, predicate, target)
        require(triple in remaining, 'Missing/changed RDF assertion: ' + str(triple))
        remaining.remove(triple)

    def provenance(entity, value, row):
        take(entity, 'prov:wasDerivedFrom', row)
        take(entity, 'prov:wasGeneratedBy', BASE + 'activity/' + value['method'])
        take(entity, 'prov:value', json.dumps(value, ensure_ascii=True, sort_keys=True), literal=True)

    def measurement(entity, value):
        take(entity, 'rdf:type', 'qudt:QuantityValue')
        take(entity, 'qudt:unit', 'unit:' + UNITS[value['unit']])
        if value['min'] == value['max']:
            take(entity, 'qudt:numericValue', value['min'], decimal=True)
        else:
            for bound in ['min', 'max']:
                child = entity + '/' + bound
                take(entity, 'dct:hasPart', child)
                take(child, 'dct:identifier', bound, literal=True)
                take(child, 'rdf:type', 'qudt:QuantityValue')
                take(child, 'qudt:unit', 'unit:' + UNITS[value['unit']])
                take(child, 'qudt:numericValue', value[bound], decimal=True)
        if value['qualifier']:
            take(entity, 'dct:description', 'qualifier=' + value['qualifier'], literal=True)

    for method in ['parsed', 'unknown']:
        take(BASE + 'activity/' + method, 'rdf:type', 'prov:Activity')
        take(BASE + 'activity/' + method, 'rdfs:label', 'Fixture extraction method: ' + method, literal=True)
    shared_materials, outcome_types = set(), set()
    for table in tables:
        source = BASE + 'source/sha256/' + table['source']['sha256']
        take(source, 'rdf:type', 'prov:Entity')
        take(source, 'dct:identifier', table['source']['sha256'], literal=True)
        take(source, 'dct:title', table['source']['filename'], literal=True)
        file = next(f for f in files if f['accession'] == table['investigation'])
        take(source, 'prov:value', json.dumps(file, sort_keys=True), literal=True)
        for record in table['records']:
            row = BASE + 'row/' + quote(record['id'], safe='')
            take(row, 'rdf:type', 'prov:Entity')
            take(row, 'dct:identifier', record['id'], literal=True)
            take(row, 'dct:isPartOf', BASE + 'investigation/' + table['investigation'])
            take(row, 'prov:wasDerivedFrom', source)
            take(row, 'prov:value', json.dumps({k: record[k] for k in ['row', 'original', 'kind', 'review_status']}, ensure_ascii=True, sort_keys=True), literal=True)
            for key, value in record['conditions'].items():
                child = row + '/condition/' + key
                if value.get('min') is not None and value.get('max') is not None:
                    take(row, 'ssn:hasProperty', child)
                    take(child, 'rdf:type', 'ssn:Property')
                    take(child, 'dct:identifier', key, literal=True)
                    measurement(child, value)
                    provenance(child, value, row)
                elif key == 'material' and value['value'] is not None:
                    material = VOCAB + 'material/' + quote(value['value'], safe='')
                    take(row, 'dct:subject', material)
                    take(row, 'dct:hasPart', child)
                    take(child, 'rdf:type', 'prov:Entity')
                    take(child, 'dct:identifier', key, literal=True)
                    take(child, 'dct:subject', material)
                    provenance(child, value, row)
                    if material not in shared_materials:
                        take(material, 'rdf:type', 'http://www.w3.org/2004/02/skos/core#Concept')
                        take(material, 'rdfs:label', value['value'], literal=True)
                        shared_materials.add(material)
            for index, outcome in enumerate(record['outcomes']):
                value = outcome['result']
                if ('min' in value and (value['min'] is None or value['max'] is None)) or ('value' in value and value['value'] is None):
                    continue
                observation = row + '/outcome/' + str(index)
                result = observation + '/result'
                take(observation, 'rdf:type', 'sosa:Observation')
                take(observation, 'sosa:hasFeatureOfInterest', row)
                term = VOCAB + 'outcome/' + outcome['type']
                take(observation, 'sosa:observedProperty', term)
                if term not in outcome_types:
                    take(term, 'rdf:type', 'sosa:ObservableProperty')
                    outcome_types.add(term)
                take(observation, 'sosa:hasResult', result)
                take(observation, 'dct:description', 'gravity=' + outcome['gravity'], literal=True)
                take(observation, 'dct:description', 'Source-reported outcome; review pending; individual-experiment classification unresolved.', literal=True)
                if 'min' in value:
                    measurement(result, value)
                else:
                    take(result, 'rdf:type', 'sosa:Result')
                    take(result, 'prov:value', value['value'], literal=True)
                provenance(result, value, row)
    require(not remaining, 'Unsupported RDF assertions: ' + str(sorted(remaining)[:1]))
    return total


def rejection_checks(cards, tables, files, manifest):
    checks = []
    bad = copy.deepcopy(cards[0])
    bad['invented_field'] = True
    checks.append(lambda: validate(bad, CON / 'schemas/research-card.schema.json'))
    broken = copy.deepcopy(cards[0])
    broken['summary']['evidence_ids'] = ['PSI-69:meta:objective#000000000000']
    packet = read(FIX / 'inputs/PSI-69-evidence-packet.json')
    metadata = read(FIX / 'sources/PSI-69-metadata.json')
    checks.append(lambda: evidence_checks(broken, packet, metadata))
    converted = copy.deepcopy(tables[0])
    converted['records'][0]['conditions']['pressure_kpa']['min'] = 0
    checks.append(lambda: table_checks(converted, manifest))
    response = copy.deepcopy(read(FIX / 'expected/http.json')['cases'][0]['body'])
    response['data'][0]['rank'] = 1
    checks.append(lambda: validate(response, CON / 'openapi.json', response_pointer('/api/studies', 200)))
    health = {'readiness': 'degraded', 'snapshot_date': '2026-11-14', 'catalog': 'loaded', 'graph': 'unavailable', 'investigation_count': 2, 'run_record_count': 0, 'verified_run_count': None}
    checks.append(lambda: validate(health, CON / 'openapi.json', '/components/schemas/Health'))
    rdf = (FIX / 'expected/runs.ttl').read_text(encoding='utf-8')
    fabricated = rdf + '<' + BASE + 'row/PSI-69%3Aflex%3A114/condition/pressure_kpa> <' + expand('qudt:numericValue') + '> "0"^^<' + expand('xsd:decimal') + '> .\n'
    checks.append(lambda: rdf_checks(tables, files, fabricated))
    for index, check in enumerate(checks, 1):
        try:
            check()
        except (ValueError, KeyError, ValidationError) as error:
            # Schema, reference and semantic failures all reject an altered fixture.
            require(bool(str(error)), 'Unexplained rejection')
        else:
            raise ValueError('Altered fixture was accepted: ' + str(index))
    return len(checks)


def main():
    schema_checks()
    manifest = manifest_checks()
    investigations, files, cards, tables = input_checks(manifest)
    http_count = http_checks(files, cards, tables)
    rdf_count = rdf_checks(tables, files)
    rejected = rejection_checks(cards, tables, files, manifest)
    print('PASS: 8 pinned schemas; official OpenAPI 3.1 document schema; all local references resolve offline.')
    print(f'PASS: {len(investigations)} investigations, {len(files)} catalog entries, 2 cards, 2 evidence packets, 2 run tables, 6 selected source rows.')
    print(f'PASS: source/artifact hashes, evidence/claim references, original cells, units, {http_count} HTTP cases, {rdf_count} RDF triples.')
    print(f'PASS: {rejected} altered fixtures rejected. Scientific review remains pending; S0 #6 remains open.')


if __name__ == '__main__':
    main()
