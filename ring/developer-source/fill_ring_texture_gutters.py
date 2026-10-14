"""Fill unused bake atlas texels before filtering, without altering logo texels."""
import argparse
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', required=True)
args = parser.parse_args()
root = Path.cwd()
asset = root / 'public/assets' / args.project
textures = asset / 'textures'
maps = {name: np.array(Image.open(textures / (name + '.png')).convert('RGB'))
        for name in ['base-color', 'metallic', 'roughness', 'normal']}
# Blank bake texels have zero roughness AND zero metallic. The original logo
# has nonzero roughness, including its dark/nonmetallic interior, so it stays.
coverage = (maps['roughness'][..., 0] > 0) | (maps['metallic'][..., 0] > 0)
neutral = {
    'base-color': [int(np.bincount(maps['base-color'][..., c][coverage]).argmax()) for c in range(3)],
    'metallic': [255, 255, 255],
    'roughness': [int(np.bincount(maps['roughness'][..., 0][coverage]).argmax())] * 3,
    'normal': [128, 128, 255],
}
for name, array in maps.items():
    # The baked 16-pixel margins are already valid. The remaining empty atlas
    # area must match polished metal rather than black when mipmaps blend it.
    array[~coverage] = neutral[name]
    Image.fromarray(array).save(textures / (name + '.png'), optimize=True)
raw = (asset / 'ring-contact-v1.glb').read_bytes()
json_size = struct.unpack_from('<I', raw, 12)[0]
doc = json.loads(raw[20:20 + json_size])
binary = raw[28 + json_size:]
metal = next(m for m in doc['materials'] if not m.get('name', '').startswith('Diamond'))
pbr = metal['pbrMetallicRoughness']
base_image = doc['textures'][pbr['baseColorTexture']['index']]['source']
normal_image = doc['textures'][metal['normalTexture']['index']]['source']
orm_image = doc['textures'][pbr['metallicRoughnessTexture']['index']]['source']
orm = np.full_like(maps['metallic'], 255)
orm[..., 1] = maps['roughness'][..., 0]
orm[..., 2] = maps['metallic'][..., 0]
packed = io.BytesIO()
Image.fromarray(orm).save(packed, format='PNG', optimize=True)
replacement = {
    doc['images'][base_image]['bufferView']: (textures / 'base-color.png').read_bytes(),
    doc['images'][normal_image]['bufferView']: (textures / 'normal.png').read_bytes(),
    doc['images'][orm_image]['bufferView']: packed.getvalue(),
}
new_binary = bytearray()
for i, view in enumerate(doc['bufferViews']):
    old_offset = view.get('byteOffset', 0)
    data = replacement.get(i, binary[old_offset:old_offset + view['byteLength']])
    new_binary.extend(b'\0' * (-len(new_binary) % 4))
    view['byteOffset'] = len(new_binary)
    view['byteLength'] = len(data)
    new_binary.extend(data)
new_binary.extend(b'\0' * (-len(new_binary) % 4))
doc['buffers'][0]['byteLength'] = len(new_binary)
j = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode()
j += b' ' * (-len(j) % 4)
result = struct.pack('<III', 0x46546c67, 2, 28 + len(j) + len(new_binary))
result += struct.pack('<II', len(j), 0x4e4f534a) + j
result += struct.pack('<II', len(new_binary), 0x004e4942) + new_binary
(asset / 'ring-contact-v1.glb').write_bytes(result)
print(json.dumps({'valid_texels': int(coverage.sum()), 'filled_gutter_texels': int((~coverage).sum()), 'uncompressed_glb_bytes': len(result)}))
