"""Offline portable launcher. No package installation, downloads or system changes."""
import argparse
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import webbrowser


def configure(root):
    os.chdir(root)
    runtime=root/'runtime'
    runtime.mkdir(exist_ok=True)
    for name in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_HUB_DISABLE_TELEMETRY'):
        os.environ[name]='1'
    os.environ['HF_HOME']=str(runtime/'hf-cache')
    os.environ['FORTE_MODEL_DIR']=str(root/'models/grounding-dino-tiny')
    key=runtime/'api-key.txt'
    if not key.exists(): key.write_text(secrets.token_urlsafe(32),encoding='ascii')
    os.environ['FORTE_API_KEY']=key.read_text(encoding='ascii').strip()
    if not os.environ['FORTE_API_KEY']: raise RuntimeError('Empty runtime/api-key.txt')


def check(root):
    import av
    import torch
    from PIL import Image
    from forte.vision import Detector
    import json
    print('Python:',sys.version.split()[0],flush=True)
    print('PyTorch:',torch.__version__,'Video decoder:',av.__version__,flush=True)
    print('CUDA available:',torch.cuda.is_available(),flush=True)
    if torch.cuda.is_available():
        print('GPU:',torch.cuda.get_device_name(0),flush=True)
        print('CUDA calculation:',(torch.ones(2,device='cuda')+1).tolist(),flush=True)
    else:
        print('WARNING: CPU mode. The 5-minute video budget is NOT guaranteed.',flush=True)
    print('Loading bundled model offline and running one image...',flush=True)
    detector=Detector(root/'models/grounding-dino-tiny')
    detector.detect(Image.new('RGB',(464,848),'gray'),['person'])
    config=json.loads((root/'config/scene.json').read_text(encoding='utf-8'))
    print('Enabled visual checks:',len(config['enabled_rules']),flush=True)
    print('CHECK OK. Start Start-Forte.cmd and upload your own video.',flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--check',action='store_true')
    p.add_argument('--no-browser',action='store_true')
    p.add_argument('--port',type=int,default=8000)
    args=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    configure(root)
    if args.check:
        check(root)
        return
    if not 1024<=args.port<=65535: raise ValueError('Use a port between 1024 and 65535')
    # Never open an unrelated service already using our local port.
    with socket.socket() as probe:
        try: probe.bind(('127.0.0.1',args.port))
        except OSError as exc:
            raise RuntimeError(f'Port {args.port} is busy. Stop the previous Forte server first.') from exc
    import uvicorn
    from forte.api import app
    url=f'http://127.0.0.1:{args.port}/'
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,workers=1))
    if not args.no_browser:
        def open_when_ready():
            for _ in range(100):
                if server.started:
                    webbrowser.open(url)
                    return
                if server.should_exit: return
                time.sleep(.1)
        threading.Thread(target=open_when_ready,daemon=True).start()
    print('Forte local server:',url,'\nKeep this window open. Stop with Ctrl+C.',flush=True)
    server.run()


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('START/CHECK FAILED:',type(exc).__name__,str(exc),file=sys.stderr)
        sys.exit(1)
