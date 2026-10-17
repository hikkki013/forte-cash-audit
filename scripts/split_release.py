"""Split a large release ZIP; create a self-contained Windows CMD joiner.

Build-time only. Uses standard-library Python; the jury needs only Windows.
Never overwrites existing archives or parts.
"""
import argparse
import hashlib
from pathlib import Path
import re


def split_archive(archive, destination, part_size=1800 * 1024 * 1024):
    if not re.fullmatch(r'[A-Za-z0-9._-]+\.zip', archive.name):
        raise ValueError('Use a simple ASCII archive name')
    if part_size < 1: raise ValueError('part_size must be positive')
    destination.mkdir(parents=True, exist_ok=True)
    count=(archive.stat().st_size+part_size-1)//part_size
    parts=[destination/(archive.name+f'.part{i:02}') for i in range(1,count+1)]
    helper=destination/'Assemble-Forte.cmd'
    if any(p.exists() for p in [*parts,helper]):
        raise FileExistsError('Choose a fresh release directory')
    digest=hashlib.sha256()
    with archive.open('rb') as source:
        for part in parts:
            remaining=part_size
            with part.open('xb') as target:
                while remaining:
                    block=source.read(min(8*1024*1024,remaining))
                    if not block: break
                    target.write(block); digest.update(block); remaining-=len(block)
            print('Part ready:',part.name,part.stat().st_size,flush=True)
    expected=digest.hexdigest()
    # Fixed filenames; no arbitrary commands, installation, deletion or overwrite.
    ps=("$ErrorActionPreference='Stop'; "
        f"$name='{archive.name}'; $parts=1..{count} | ForEach-Object {{ $name+('.part{{0:D2}}' -f $_) }}; "
        "foreach($p in $parts){if(!(Test-Path -LiteralPath $p)){throw ('Missing file: '+$p)}}; "
        "if(Test-Path -LiteralPath $name){throw 'ZIP already exists. Use it or choose an empty folder.'}; "
        "Write-Host 'Assembling ZIP. Please wait...'; "
        "$out=[IO.File]::Open($name,[IO.FileMode]::CreateNew); "
        "try {foreach($p in $parts){$inputFile=[IO.File]::OpenRead($p); try{$inputFile.CopyTo($out)}finally{$inputFile.Dispose()}}}finally{$out.Dispose()}; "
        "$hasher=[Security.Cryptography.SHA256]::Create(); $checkFile=[IO.File]::OpenRead($name); "
        "try{$actual=[BitConverter]::ToString($hasher.ComputeHash($checkFile)).Replace('-','').ToLowerInvariant()}finally{$checkFile.Dispose(); $hasher.Dispose()}; "
        f"if($actual -ne '{expected}'){{throw 'Checksum mismatch. Do not use this ZIP.'}}; "
        "Write-Host 'CHECKSUM OK. Right-click the ZIP, Extract All, then open Start-Forte.cmd in the extracted folder.'")
    # A quoted CMD %~dp0 handles spaces; PowerShell resolves literal fixed filenames.
    text='@echo off\r\ncd /d "%~dp0"\r\npowershell -NoProfile -ExecutionPolicy Bypass -Command "'+ps+'"\r\nif errorlevel 1 (\r\n echo Assembly failed. Read the error above.\r\n pause\r\n exit /b 1\r\n)\r\npause\r\n'
    helper.write_bytes(text.encode('ascii'))
    (destination/(archive.name+'.sha256')).write_text(expected+'  '+archive.name+'\n',encoding='ascii')
    return parts,helper,expected


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('archive',type=Path)
    p.add_argument('destination',type=Path)
    a=p.parse_args()
    split_archive(a.archive,a.destination)
