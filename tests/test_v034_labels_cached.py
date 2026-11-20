"""Regression: narrow sidebar labels, error visibility and cached ISNet setup."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import time

spec=importlib.util.spec_from_file_location('v034_base',Path(__file__).with_name('test_offline.py'))
module=importlib.util.module_from_spec(spec)
sys.modules['v034_base']=module
spec.loader.exec_module(module)
a=sys.modules['addon']

class Layout:
    def __init__(self):
        self.labels=[]
        self.bars=[]
    def label(self,*,text='',icon=None):
        self.labels.append(text)
    def progress(self,**kwargs):
        self.bars.append(kwargs)
    def row(self,*args,**kwargs):
        return self
    def operator(self,*args,**kwargs):
        return SimpleNamespace()
    def __setattr__(self,key,value):
        object.__setattr__(self,key,value)

old=a._prep_install_status
try:
    a._prep_install_status=lambda:{'python':True,'rembg':True,'weights':False,'validated':False,'log':Path('nonexistent')}
    start=time.monotonic()-86
    a._status_set('setup',state='working',phase=5,started_at=start,
                  message='Checking/downloading ISNet model weights (download percentage unavailable)')
    for compact in (True,False):
        layout=Layout()
        a._draw_local_setup(layout,compact=compact)
        assert len(layout.bars)==1 and layout.bars[0]['factor']<1
        assert any('ISNet' in item for item in layout.labels)
        assert any('Elapsed:' in item for item in layout.labels)
        assert all(len(item)<=33 for item in layout.labels),layout.labels
        assert not any('percentage unavailable)' in item for item in layout.labels)
    # Existing local files should not overwrite a recorded installation failure.
    a._prep_install_status=lambda:{'python':True,'rembg':True,'weights':True,'validated':True,'log':Path('nonexistent')}
    a._status_set('setup',state='error',phase=0,message='ISNet validation failed: unreachable network')
    layout=Layout()
    a._draw_local_setup(layout,compact=True)
    assert not layout.bars and 'Local tools setup failed' in layout.labels,layout.labels
    # Cached tools must appear ready but should not be reinstalled by UI rendering.
    a._status_set('setup',state='ok',phase=6,message='Local image tools ready')
    layout=Layout()
    a._draw_local_setup(layout,compact=True)
    assert layout.bars[0]['factor']==1.0 and 'ISNet ready (cached)' in layout.labels
    # No ordinary message is split mid-word to fit an arbitrary substring limit.
    words=a._ui_message_lines('ISNet weights loaded and validated with no network access',width=26,max_lines=3)
    assert words[0]=='ISNet weights loaded and',words
    assert all(len(item)<=26 for item in words),words
finally:
    a._prep_install_status=old
print('PASS: short whole-word labels, phase progress, cached readiness and visible errors')
