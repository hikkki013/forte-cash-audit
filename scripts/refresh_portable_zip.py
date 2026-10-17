"""Replace application files without recompressing multi-GB runtime DLLs.

Build-time utility for our unencrypted, sequential ZIPs, using CPython 3.12's
zipfile central-directory writer. Validate output CRC before publishing.
"""
import argparse
import copy
import json
from pathlib import Path
import zipfile
from scripts.build_portable import sha256


def refresh_archive(original, folder, target):
    manifest=json.loads((folder/'BUILD.json').read_text(encoding='utf-8'))
    prefix=folder.name+'/'
    with zipfile.ZipFile(original) as old:
        previous=json.loads(old.read(prefix+'BUILD.json'))
        replace=set(previous['source_sha256']) | set(manifest['source_sha256']) | {'BUILD.json'}
        infos=old.infolist()
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as new:
            for index,info in enumerate(infos):
                if not info.filename.startswith(prefix) or info.flag_bits & 1:
                    raise ValueError('Unexpected archive layout/encryption')
                if info.filename[len(prefix):] in replace: continue
                end=infos[index+1].header_offset if index+1<len(infos) else old.start_dir
                length=end-info.header_offset
                if length<=0: raise ValueError('Nonsequential ZIP')
                entry=copy.copy(info); entry.header_offset=new.fp.tell()
                old.fp.seek(info.header_offset)
                while length:
                    block=old.fp.read(min(8*1024*1024,length))
                    if not block: raise EOFError('Truncated ZIP')
                    new.fp.write(block); length-=len(block)
                new.filelist.append(entry); new.NameToInfo[entry.filename]=entry
                new.start_dir=new.fp.tell(); new._didModify=True
            for name in sorted(set(manifest['source_sha256']) | {'BUILD.json'}):
                new.write(folder/name,prefix+name)
    with zipfile.ZipFile(target) as check:
        if len(check.namelist())!=len(set(check.namelist())): raise ValueError('Duplicate ZIP entries')
        bad=check.testzip()
        if bad: raise ValueError('CRC failed: '+bad)
    digest=sha256(target)
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print('Refreshed archive; all CRCs passed:',target,target.stat().st_size,digest,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('original',type=Path); p.add_argument('folder',type=Path); p.add_argument('target',type=Path)
    a=p.parse_args(); refresh_archive(a.original,a.folder,a.target)
