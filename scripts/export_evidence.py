"""Export actual API evidence as a contact sheet for a human reviewer."""
import base64
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw

if __name__=='__main__':
    root=Path('outputs/api-smoke')
    data=json.loads((root/'response.json').read_text(encoding='utf-8'))
    frames=data['result']['violations'][0]['evidence_frames']
    tiles=[]
    for f in frames:
        im=Image.open(io.BytesIO(base64.b64decode(f['image_base64']))).convert('RGB')
        tile=Image.new('RGB',(im.width,im.height+28),'white')
        tile.paste(im,(0,28))
        ImageDraw.Draw(tile).text((8,6),f"X-26 | {f['timestamp_sec']:.2f}s | actual API evidence",fill='black')
        tiles.append(tile)
    sheet=Image.new('RGB',(sum(im.width for im in tiles),max(im.height for im in tiles)),'white')
    offset=0
    for im in tiles:
        sheet.paste(im,(offset,0))
        offset+=im.width
    sheet.save(root/'evidence.jpg',quality=90)
    print(root/'evidence.jpg')
