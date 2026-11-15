"""Build country-code lookup separately from strictly valid display outlines."""
import argparse
import hashlib
import json
from pathlib import Path
import shapefile
from shapely.geometry import shape, mapping


def build(source_zip, release, output):
    output=Path(output)
    if output.exists():
        raise ValueError('Choose a new output directory.')
    manifest=json.loads((Path(release)/'manifest.json').read_text())
    codes=set(manifest['countries']); areas={}; aliases={}; continents={}; rejected=[]
    reader=shapefile.Reader(str(source_zip));fields=[field[0] for field in reader.fields[1:]]
    for record, geometry in zip(reader.iterRecords(),reader.iterShapes(),strict=True):
        row=dict(zip(fields,record));code=row['ADM0_A3']
        if code not in codes:continue
        area_id=f'country:{code}';name=row['ADMIN'];continent=row['CONTINENT']
        polygon=shape(geometry.__geo_interface__)
        display=polygon.simplify(0.04,preserve_topology=True) if polygon.is_valid else None
        if display is None or not display.is_valid:
            display=None;rejected.append(code)
        areas[area_id]={'id':area_id,'name':name,'country_codes':[code],
            'bbox':list(polygon.bounds),'geometry':mapping(display) if display is not None else None}
        continents.setdefault(continent,[]).append(code)
        for value in [name,row['NAME'],code,row['ISO_A2'],row['ISO_A3']]:
            if value and value!='-99':aliases.setdefault(' '.join(str(value).casefold().split()),set()).add(area_id)
    unmatched=sorted(codes-{value['country_codes'][0] for value in areas.values()})
    for code in unmatched:
        areas[f'country:{code}']={'id':f'country:{code}','name':code,'country_codes':[code],'bbox':[-180,-85,180,85],'geometry':None}
        aliases[code.casefold()]={f'country:{code}'}
    for name, members in continents.items():
        area_id='continent:'+name.lower().replace(' ','-')
        bounds=[areas[f'country:{code}']['bbox'] for code in members]
        areas[area_id]={'id':area_id,'name':name,'country_codes':sorted(members),
            'bbox':[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)],'geometry':None}
        aliases[name.casefold()]={area_id}
    areas['world']={'id':'world','name':'World','country_codes':sorted(codes),'bbox':[-180,-85,180,85],'geometry':None}
    aliases.update({'world':{'world'},'global':{'world'},'earth':{'world'},'usa':{'country:USA'},'viet nam':{'country:VNM'},'vietnam':{'country:VNM'}})
    data={'areas':areas,'aliases':{key:sorted(values) for key,values in aliases.items()},
        'unmapped_codes':unmatched,'rejected_display_polygons':rejected,
        'boundary_source_sha256':hashlib.sha256(Path(source_zip).read_bytes()).hexdigest()}
    raw=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    output.mkdir(parents=True)
    (output/'area-catalog.json').write_bytes(raw)
    (output/'catalog-sha256.txt').write_text(hashlib.sha256(raw).hexdigest()+'\n')
    print(json.dumps({'countries':len(codes),'continents':list(continents),'unmapped_codes':unmatched,'rejected_display_polygons':rejected}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip',required=True);parser.add_argument('--release',required=True);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();build(args.source_zip,args.release,args.output_dir)
