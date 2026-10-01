"""Package small, verifiable completion evidence without raw client binaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--acceptance',type=Path)
    parser.add_argument('--bake',type=Path)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('choose a new evidence directory')
    research=ROOT/'.local/research/incarnon-completion-20261001'
    names=['charged-ground-modes.json','charged-trace-final.json','charged-profiles-trace-final.json',
           'co-reference-ground-final.json','incarnon-mode-identities.json','onos-sequence-final.json',
           'native-event-conditions-final.json','runtime-links-probabilities-final.json',
           'onos-schema-symbols.json','shield-schema-verification.json','mq-proxy-scale-callers.json',
           'charged-delegates-final-20261001.json','co-reference-delegates-final-20261001.json',
           'native-condition-tail-final-20261001.json','runtime-links-tail-20261001.json',
           'incarnon-radials-final-20261001.json','incarnon-radials-compression-final-20261001.json',
           'zylok-profiles-final-20261001.json','tail-native-bindings.json']
    files={f'native/{name}':research/name for name in names}
    for folder in ['ir','actor-ir','energy-ir','stat-conversion-ir','latron-ir','utility-ir','tail-ir-v2','double-tap-ir']:
        files.update({f'luau/{folder}/{p.name}':p for p in (research/folder).glob('*.txt')})
    for folder,native_names in [('decompiled-shield-apply',['140a3e6c0.c']),
                               ('decompiled-shield-pipeline',['141095210.c']),
                               ('decompiled-stack-fraction',['1404ac060.c']),
                               ('decompiled-onos-mq-final',['140ef69d0.c']),
                               ('decompiled-canonical',['1415a16b0.c'])]:
        files.update({f'native/code/{name}':research/folder/name for name in native_names})
    for folder in ['burston-completion-20261001','archgun-board-current-20261001','archgun-charge-verified-20261001',
                   'archgun-charge-no-enervate-20261001','nonmelee-untransformed-current-20261001',
                   'incarnon-board-final2-20261001','latron-double-tap-20261001',
                   'incarnon-cycle-board-final-20261001','latron-compression-cycle-final-20261001']:
        source=ROOT/'.local/reports'/folder/'comparison.json'
        if source.is_file():
            payload=json.loads(source.read_bytes())
            if folder!='burston-completion-20261001':
                for case in payload.get('cases',[]):
                    case.get('local',{}).get('replay',{}).pop('timeline',None)
                    case.get('reference',{}).pop('timeline',None)
            target=args.output/'comparisons'/f'{folder}.json'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    burston=ROOT/'.local/reports/burston-completion-20261001'
    for name in ['case-0-request.json','case-1-request.json','wfsim-current-response.json']:
        files[f'comparisons/burston/{name}']=burston/name
    source=ROOT/'.local/wfsim-live-20261001/source.json'
    files['reference-runtime.json']=source
    files['ui-desktop.png']=ROOT/'.local/reports/incarnon-ui-desktop-final-20261001.png'
    files['ui-mobile.png']=ROOT/'.local/reports/incarnon-ui-mobile-final-20261001.png'
    for name in ['incarnon-completion-20261001-final4.xml']:
        source=ROOT/'.local/reports'/name
        if source.is_file():
            suite=next(ET.parse(source).getroot().iter('testsuite'))
            result=dict(suite.attrib)
            result['failures']=[dict(classname=t.get('classname'),name=t.get('name')) for t in suite.iter('testcase') if t.find('failure') is not None]
            (args.output/'tests.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for path,label in [(args.acceptance,'riven-search'),(args.bake,'cache-bake')]:
        if path:
            files.update({f'{label}/{p.name}':p for p in path.glob('*.json')})
    for relative,source in files.items():
        if source.is_file():
            destination=args.output/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination)
    import app
    manifest=dict(engineFingerprint=app._analysis_inputs_fingerprint(),cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
                  clientSha256='45fa6ad0769cc8ca7fa7e0ffdee65c0c0932e11744146781ad18c45b16e4a81c',
                  sourceBuild='2026.09.22.16.46',files=[dict(path=p.relative_to(args.output).as_posix(),bytes=p.stat().st_size,
                  sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(args.output.rglob('*')) if p.is_file()])
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print('packaged',len(manifest['files']),'files',sum(f['bytes'] for f in manifest['files']),'bytes')


if __name__=='__main__':
    main()
