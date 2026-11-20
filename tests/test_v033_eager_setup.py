"""Mock fresh eager install, shared-cache isolation, deduplication and cleanup."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import subprocess

spec=importlib.util.spec_from_file_location('test_v033_base',Path(__file__).with_name('test_offline.py'))
module=importlib.util.module_from_spec(spec)
sys.modules['test_v033_base']=module
spec.loader.exec_module(module)
a=sys.modules['addon']
a._ACTIVE=True  # emulate the enabled add-on after test_offline unregister smoke

with TemporaryDirectory() as work:
    root=Path(work)
    private=root/'TiinyAIForBlender'
    envdir=private/'image-prep-py312'
    python=envdir/'bin'/'python'
    shared=root/'shared-rembg'/'isnet-general-use.onnx'
    shared.parent.mkdir()
    shared.write_bytes(b'1'*1000003)
    ops=[]
    old = (a._image_prep_runtime,a._uv_executable,a._run_prep_command,
           a._run_image_prep_process,a._copy_shared_weights_once)
    a._image_prep_runtime=lambda:(envdir,python)
    a._uv_executable=lambda:'uv-test'
    def fake_cmd(cmd, timeout, explanation):
        ops.append(explanation)
        if 'venv' in cmd:
            python.parent.mkdir(parents=True,exist_ok=True)
            python.touch()
        return subprocess.CompletedProcess(cmd,0,'','')
    a._run_prep_command=fake_cmd
    def fake_migrate():
        private_model=a._model_cache_root()/'isnet-general-use.onnx'
        private_model.parent.mkdir(parents=True,exist_ok=True)
        private_model.write_bytes(shared.read_bytes())
        return True
    a._copy_shared_weights_once=fake_migrate
    def fake_download(cmd,timeout,**kw):
        ops.append('model validated')
        assert a._image_prep_environment()['U2NET_HOME']==str(a._model_cache_root())
        assert a._image_prep_environment()['REMBG_HOME']==str(a._model_cache_root())
        return subprocess.CompletedProcess(cmd,0,'TIINY_MODEL_READY','')
    a._run_image_prep_process=fake_download
    try:
        a._setup_worker()
        assert a._status_get('setup')['state']=='ok'
        assert a._status_get('setup')['phase']==a._SETUP_TOTAL_STAGES
        status=a._prep_install_status()
        assert status['python'] and status['rembg'] and status['weights'] and status['validated']
        assert len(ops)==4, ops
        a._begin_background_setup()
        assert len(ops)==4, 'Second add-on startup must not reinstall tools'
        assert shared.exists(), 'Shared weights must never be removed'
        a._status_set('prep', state='not_ready', message='Ready')
        a._JOBS.clear()
        a._remove_private_tools()
        assert not private.exists() and shared.exists(), 'Only private data may be removed'
        assert a._prep_install_status()['weights']==False
        assert a._status_get('setup')['state']=='not_ready'
        assert a._begin_background_setup()
        a._SETUP_THREAD.join(2)
        assert a._status_get('setup')['state']=='ok', a._status_get('setup')
    finally:
        (a._image_prep_runtime,a._uv_executable,a._run_prep_command,
         a._run_image_prep_process,a._copy_shared_weights_once)=old
print('PASS: eager first-run setup, private weights, cached restart, confirmable cleanup, test reinstall')
