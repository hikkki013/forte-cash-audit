import base64
import io
import time
import av
import numpy as np
import pytest
from PIL import Image
from forte.vision import sampled_frames
from forte.pipeline import evidence, in_zone

def test_real_decode_and_pts(tmp_path):
    path=tmp_path/'tiny.mp4'
    with av.open(str(path),'w') as c:
        s=c.add_stream('libx264',rate=10)
        s.width=s.height=64
        s.pix_fmt='yuv420p'
        for i in range(25):
            f=av.VideoFrame.from_ndarray(np.full((64,64,3),i*10,dtype=np.uint8),format='rgb24')
            for p in s.encode(f): c.mux(p)
        for p in s.encode(): c.mux(p)
    frames=list(sampled_frames(path,1))
    assert [t for t,_ in frames]==[0,1,2]
    assert all(im.size==(64,64) for _,im in frames)
    with pytest.raises(TimeoutError):
        list(sampled_frames(path,deadline=time.monotonic()-1))

def test_corrupt_video_not_success(tmp_path):
    path=tmp_path/'bad.mp4'
    path.write_bytes(b'not video')
    with pytest.raises(av.error.InvalidDataError):
        list(sampled_frames(path))

def test_evidence_is_valid_jpeg_with_original_timestamp():
    row=evidence(12.35,Image.new('RGB',(64,64),'red'))
    decoded=Image.open(io.BytesIO(base64.b64decode(row['image_base64'])))
    assert row['timestamp_sec']==12.35 and decoded.format=='JPEG'

def test_zone_normalization():
    assert in_zone([30,40,50,60],[.3,.4,.6,.7],100,100)
    assert not in_zone([0,0,10,10],[.3,.4,.6,.7],100,100)
