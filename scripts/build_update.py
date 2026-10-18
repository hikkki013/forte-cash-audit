"""Small offline source update for the unchanged v0.2.0 Windows runtime.

The jury extracts this payload over an existing portable installation, after
stopping the server and backing up custom configuration. No runtime/user data
are shipped. Never overwrite an existing archive.
"""
import argparse
import json
from pathlib import Path
import re
import zipfile
from scripts.build_portable import ROOT, source_files, sha256


def build_update(root, base, target, commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Use the complete source Git commit SHA')
    manifest=json.loads((base/'BUILD.json').read_text(encoding='utf-8'))
    if manifest.get('version')!='0.2.0' or manifest.get('platform')!='Windows-x64':
        raise ValueError('Requires the v0.2.0 Windows base')
    if not (base/'python/python.exe').is_file():
        raise ValueError('Missing portable runtime')
    for name in ('requirements.txt','scripts/setup.ps1','scripts/download_model.py'):
        if sha256(root/name)!=manifest['source_sha256'].get(name):
            raise ValueError('Dependency or model setup changed: '+name)
    model='models/grounding-dino-tiny/model.safetensors'
    if sha256(root/model)!=manifest['model_sha256'] or sha256(base/model)!=manifest['model_sha256']:
        raise ValueError('Model weights differ from the base release')
    files=list(source_files(root))
    manifest.update(version='0.3.0',runtime_base_version='0.2.0',source_commit=commit,
                    source_sha256={p.relative_to(root).as_posix():sha256(p) for p in files})
    target.parent.mkdir(parents=True,exist_ok=True)
    prefix='Forte-Update-v0.3.0/'
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,prefix+p.relative_to(root).as_posix())
        z.writestr(prefix+'BUILD.json',json.dumps(manifest,indent=2))
    digest=sha256(target)
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    return manifest


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--commit',required=True)
    a=p.parse_args()
    build_update(ROOT,a.base,a.output,a.commit)
    print('Update:',a.output,'bytes:',a.output.stat().st_size)


if __name__=='__main__': main()
