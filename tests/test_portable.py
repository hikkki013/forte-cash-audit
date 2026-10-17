from pathlib import Path
import json
import zipfile
import pytest
from scripts.build_portable import source_files, ignore_runtime, archive, refresh_source
from scripts.portable import configure


def test_source_bundle_allowlist_excludes_secrets_and_media(tmp_path):
    for name in ['README.md','forte/api.py','config/scene.json','runtime/api-key.txt',
                 '.env','.git/config','outputs/private.jpg','docs/private.pdf','docs/clip.mov']:
        p=tmp_path/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('test')
    names={p.relative_to(tmp_path).as_posix() for p in source_files(tmp_path)}
    assert names=={'README.md','forte/api.py','config/scene.json'}


def test_runtime_keeps_dlls_and_licenses_not_cpp_build_files():
    ignored=ignore_runtime('', ['a.dll','LICENSE','b.lib','x.pdb','x.h','__pycache__'])
    assert set(ignored)=={'b.lib','x.pdb','x.h','__pycache__'}


def test_archive_never_contains_test_run_secrets(tmp_path):
    root=tmp_path/'Forte'
    for name in ['Start-Forte.cmd','python/python.exe','runtime/api-key.txt','outputs/result.json','tests/__pycache__/x.pyc']:
        p=root/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('test')
    target=tmp_path/'Forte.zip'
    archive(root,target)
    with zipfile.ZipFile(target) as z:
        assert set(z.namelist())=={'Forte/Start-Forte.cmd','Forte/python/python.exe'}
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
