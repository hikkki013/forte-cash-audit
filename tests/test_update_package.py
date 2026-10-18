import json
import zipfile
import pytest
from scripts.build_update import build_update
from scripts.build_portable import sha256


def fixture(tmp_path):
    root=tmp_path/'source';base=tmp_path/'base'
    names=['requirements.txt','scripts/setup.ps1','scripts/download_model.py',
           'config/door_calibration.json','forte/access_checks.py',
           'models/grounding-dino-tiny/model.safetensors']
    for folder in [root,base]:
        for name in names+['runtime/api-key.txt','outputs/private.jpg','python/python.exe']:
            p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name)
    (base/'BUILD.json').write_text(json.dumps({'version':'0.2.0','platform':'Windows-x64',
        'source_sha256':{n:sha256(root/n) for n in names},'model_sha256':sha256(root/names[-1])}))
    return root,base,tmp_path/'update.zip'


def test_update_contains_code_and_calibration_not_runtime_secrets_or_weights(tmp_path):
    root,base,target=fixture(tmp_path)
    result=build_update(root,base,target,'a'*40)
    assert result['version']=='0.3.0' and result['runtime_base_version']=='0.2.0'
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        names=z.namelist()
        assert 'Forte-Update-v0.3.0/config/door_calibration.json' in names
        assert not any('/runtime/' in n or '/outputs/' in n or '/models/' in n or '/python/' in n for n in names)
    with pytest.raises(FileExistsError): build_update(root,base,target,'a'*40)


@pytest.mark.parametrize('change',['requirements.txt','scripts/setup.ps1','scripts/download_model.py',
                                     'models/grounding-dino-tiny/model.safetensors'])
def test_update_refuses_incompatible_runtime_or_model(tmp_path,change):
    root,base,target=fixture(tmp_path)
    (root/change).write_text('changed')
    with pytest.raises(ValueError): build_update(root,base,target,'a'*40)
    assert not target.exists()
