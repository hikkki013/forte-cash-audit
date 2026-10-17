from pathlib import Path
import json
import zipfile
import pytest
from scripts.build_portable import source_files, ignore_runtime, archive, refresh_source
from scripts.portable import configure
from scripts.split_release import split_archive
from scripts.refresh_portable_zip import refresh_archive


def test_source_bundle_allowlist_excludes_secrets_and_media(tmp_path):
    for name in ['README.md','forte/api.py','config/scene.json','runtime/api-key.txt',
                 '.env','.git/config','outputs/private.jpg','docs/private.pdf','docs/clip.mov']:
        p=tmp_path/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('test')
    names={p.relative_to(tmp_path).as_posix() for p in source_files(tmp_path)}
    assert names=={'README.md','forte/api.py','config/scene.json'}


def test_release_parts_reconstruct_archive_and_refuse_overwrite(tmp_path):
    import hashlib
    original=tmp_path/'example.zip'; original.write_bytes(b'abcdefg'*10)
    parts,helper,digest=split_archive(original,tmp_path/'parts',part_size=16)
    assert b''.join(p.read_bytes() for p in parts)==original.read_bytes()
    assert digest==hashlib.sha256(original.read_bytes()).hexdigest()
    command=helper.read_text()
    assert '[Security.Cryptography.SHA256]::Create()' in command and digest in command
    assert 'CreateNew' in command and '1..5' in command
    with pytest.raises(FileExistsError): split_archive(original,tmp_path/'parts',part_size=16)


def test_refresh_zip_preserves_runtime_replaces_docs_and_has_no_duplicates(tmp_path):
    folder=tmp_path/'Forte'; folder.mkdir()
    manifest={'source_sha256':{'README.md':'example'}}
    old=tmp_path/'old.zip'; target=tmp_path/'new.zip'
    with zipfile.ZipFile(old,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('Forte/README.md','old')
        z.writestr('Forte/BUILD.json',json.dumps(manifest))
        z.writestr('Forte/python/runtime.bin',b'abc'*10000)
    (folder/'BUILD.json').write_text(json.dumps(manifest))
    (folder/'README.md').write_text('updated')
    (folder/'python').mkdir()
    (folder/'python/runtime.bin').write_bytes(b'abc'*10000)
    (folder/'python/runtime').mkdir()
    (folder/'python/runtime/required.py').write_text('required dependency')
    (folder/'runtime').mkdir()
    (folder/'runtime/api-key.txt').write_text('must not ship')
    refresh_archive(old,folder,target)
    with zipfile.ZipFile(target) as z:
        assert z.read('Forte/README.md')==b'updated'
        assert z.read('Forte/python/runtime.bin')==b'abc'*10000
        assert z.read('Forte/python/runtime/required.py')==b'required dependency'
        assert len(z.namelist())==4
        assert z.testzip() is None
    with pytest.raises(FileExistsError): refresh_archive(old,folder,target)


def test_runtime_keeps_dlls_and_licenses_not_cpp_build_files():
    ignored=ignore_runtime('', ['a.dll','LICENSE','b.lib','x.pdb','x.h','__pycache__'])
    assert set(ignored)=={'b.lib','x.pdb','x.h','__pycache__'}


def test_archive_never_contains_test_run_secrets(tmp_path):
    root=tmp_path/'Forte'
    for name in ['Start-Forte.cmd','python/python.exe','python/Lib/site-packages/torch/_inductor/runtime/hints.py','runtime/api-key.txt','outputs/result.json','tests/__pycache__/x.pyc']:
        p=root/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('test')
    target=tmp_path/'Forte.zip'
    archive(root,target)
    with zipfile.ZipFile(target) as z:
        assert set(z.namelist())=={'Forte/Start-Forte.cmd','Forte/python/python.exe','Forte/python/Lib/site-packages/torch/_inductor/runtime/hints.py'}
    with pytest.raises(FileExistsError): archive(root,target)


def test_configure_is_offline_and_generates_own_secret(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ['HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_HUB_DISABLE_TELEMETRY','HF_HOME','FORTE_MODEL_DIR','FORTE_API_KEY']:
        monkeypatch.delenv(key,raising=False)
    configure(tmp_path)
    import os
    key=(tmp_path/'runtime/api-key.txt').read_text()
    assert len(key)>32 and os.environ['FORTE_API_KEY']==key
    assert os.environ['HF_HUB_OFFLINE']=='1' and os.environ['TRANSFORMERS_OFFLINE']=='1'
    configure(tmp_path)
    assert (tmp_path/'runtime/api-key.txt').read_text()==key


def test_refresh_cannot_overwrite_unrelated_folder(tmp_path):
    with pytest.raises(ValueError): refresh_source(tmp_path)
