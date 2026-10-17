"""Build a fresh Windows offline distribution from an explicit tested environment.

Never copies user videos, outputs, runtime secrets, Git history or model cache.
No downloads; destination must be new. Static C++ .lib/.pdb/.h files are omitted,
not runtime DLLs. Preserve dependency licences/metadata and Python stdlib.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parent.parent
SOURCE_DIRS=('forte','config','frontend','docs','scripts','tests','licenses')
SOURCE_FILES=('README.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md','requirements.txt',
              'Start-Forte.cmd','Check-Forte.cmd','Test-Forte.cmd','pytest.ini','pyproject.toml',
              'PLAN.md','CONTRIBUTING.md')


def ignore_runtime(directory,names):
    return [n for n in names if n in {'__pycache__','.cache','.pytest_cache'}
            or Path(n).suffix.lower() in {'.pyc','.pdb','.lib','.h','.hpp'}]


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def source_files(root):
    for name in SOURCE_FILES:
        path=root/name
        if path.is_file(): yield path
    for directory in SOURCE_DIRS:
        for path in sorted((root/directory).rglob('*')):
            if path.is_file() and not set(path.parts)&{'__pycache__','.pytest_cache'}:
                if path.suffix.lower() in {'.pyc','.mov','.mp4','.xlsx','.docx','.pdf'}: continue
                yield path


def refresh_source(destination):
    destination=destination.resolve()
    if not destination.is_relative_to((ROOT/'dist').resolve()) or not (destination/'BUILD.json').is_file():
        raise ValueError('Only an existing Forte build below dist can be refreshed')
    for source in source_files(ROOT):
        target=destination/source.relative_to(ROOT); target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    manifest=json.loads((destination/'BUILD.json').read_text(encoding='utf-8'))
    manifest['source_sha256']={p.relative_to(ROOT).as_posix():sha256(p) for p in source_files(ROOT)}
    (destination/'BUILD.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Application source refreshed; runtime and model unchanged',flush=True)


def build(destination,python_home,site_packages,crt,ms_licenses):
    destination=destination.resolve()
    if destination.exists(): raise FileExistsError('Choose a NEW destination; existing files are never removed')
    if not destination.is_relative_to((ROOT/'dist').resolve()):
        raise ValueError('Build destination must be below this checkout/dist')
    if not (python_home/'python312.dll').is_file(): raise ValueError('CPython 3.12 x64 is required')
    if not (site_packages/'torch').is_dir(): raise ValueError('Tested torch environment missing')
    if not (crt/'msvcp140.dll').is_file(): raise ValueError('Explicit licensed x64 MSVC CRT directory required')
    destination.mkdir(parents=True)
    print('Copying application (allowlist)...',flush=True)
    for source in source_files(ROOT):
        target=destination/source.relative_to(ROOT); target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    py=destination/'python'; py.mkdir()
    for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','LICENSE.txt'):
        shutil.copy2(python_home/name,py/name)
    for directory in ('DLLs','Lib'):
        def exclude(path,names):
            return ignore_runtime(path,names)+(['site-packages'] if Path(path)==python_home/'Lib' else [])
        shutil.copytree(python_home/directory,py/directory,ignore=exclude)
    print('Copying installed inference dependencies (without C++ build libraries)...',flush=True)
    shutil.copytree(site_packages,py/'Lib/site-packages',ignore=ignore_runtime)
    for dll in crt.glob('*.dll'): shutil.copy2(dll,py/dll.name)
    notices=destination/'licenses/MSVC'; notices.mkdir(parents=True,exist_ok=True)
    for source in ms_licenses.glob('*'):
        if source.is_file(): shutil.copy2(source,notices/source.name)
    (py/'python312._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n..\nimport site\n',encoding='ascii')
    print('Copying local model weights...',flush=True)
    shutil.copytree(ROOT/'models/grounding-dino-tiny',destination/'models/grounding-dino-tiny',ignore=ignore_runtime)
    # Copy the complete Apache 2.0 text already distributed with Transformers.
    apache=next((site_packages/'transformers-4.57.3.dist-info').rglob('LICENSE'))
    shutil.copy2(apache,destination/'models/grounding-dino-tiny/LICENSE')
    versions=sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions(path=[str(site_packages)]))
    (destination/'DEPENDENCIES.json').write_text(json.dumps(dict(versions),indent=2),encoding='utf-8')
    source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):sha256(p) for p in source_files(ROOT)}
    manifest={'version':'0.2.0','platform':'Windows-x64','python':'3.12',
              'source_sha256':source_hashes,
              'model_sha256':sha256(destination/'models/grounding-dino-tiny/model.safetensors'),
              'excluded':['private videos','runtime keys','outputs','Git history','C++ build-only libraries']}
    (destination/'BUILD.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Build ready:',destination,flush=True)


def archive(folder,target):
    if target.exists(): raise FileExistsError(target)
    files=sorted(p for p in folder.rglob('*') if p.is_file()
                 and not set(p.relative_to(folder).parts)&{'runtime','outputs','__pycache__','.pytest_cache'})
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as out:
        for i,path in enumerate(files):
            out.write(path,Path(folder.name)/path.relative_to(folder))
            if i%2000==0: print('Archive files:',i,'/',len(files),flush=True)
    digest=sha256(target)
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print('Archive:',target,'bytes:',target.stat().st_size,'sha256:',digest,flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--python-home',type=Path,default=Path(sys.base_prefix))
    p.add_argument('--site-packages',type=Path,default=ROOT/'.venv/Lib/site-packages')
    p.add_argument('--crt',type=Path)
    p.add_argument('--ms-licenses',type=Path)
    p.add_argument('--archive-only',action='store_true')
    p.add_argument('--refresh-source',action='store_true')
    args=p.parse_args()
    if args.refresh_source:
        refresh_source(args.destination)
    elif args.archive_only:
        if not args.destination.resolve().is_relative_to((ROOT/'dist').resolve()): raise ValueError('Use dist')
        archive(args.destination,args.destination.parent/(args.destination.name+'.zip'))
    else:
        if not args.crt or not args.ms_licenses: p.error('--crt and --ms-licenses are required')
        build(args.destination,args.python_home,args.site_packages,args.crt,args.ms_licenses)


if __name__=='__main__': main()
