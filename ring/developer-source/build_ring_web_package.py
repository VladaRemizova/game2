"""Package a prepared ring using the frozen, accepted browser viewer."""
import argparse
import base64
import json
import shutil
import struct
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--label', required=True)
args = parser.parse_args()
root = Path.cwd()
reference = root / 'outputs/ring-webgl-v1'
asset = root / 'public/assets' / args.project
work = root / 'work' / args.project
out = root / 'outputs' / args.output
out.mkdir(parents=True, exist_ok=True)
raw = (asset / 'ring-draco-v1.glb').read_bytes()
json_size = struct.unpack_from('<I', raw, 12)[0]
doc = json.loads(raw[20:20 + json_size])
binary = raw[28 + json_size:]
for material in doc.get('materials', []):
    if material.get('name', '').startswith('Diamond'):
        material['doubleSided'] = False
        material.setdefault('extensions', {})['KHR_materials_volume'] = {
            'thicknessFactor': 0.001, 'attenuationColor': [0.99, 0.998, 1], 'attenuationDistance': 1,
        }
        material['extras'] = {'webViewer': 'Internal facet tracing in HTML; glTF uses standard transmissive PBR.'}
if 'KHR_materials_volume' not in doc.setdefault('extensionsUsed', []):
    doc['extensionsUsed'].append('KHR_materials_volume')
j = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode()
j += b' ' * (-len(j) % 4)
final = struct.pack('<III', 0x46546c67, 2, 28 + len(j) + len(binary))
final += struct.pack('<II', len(j), 0x4e4f534a) + j
final += struct.pack('<II', len(binary), 0x004e4942) + binary
(out / 'ring-web-v1.glb').write_bytes(final)
site = (reference / 'embed.html').read_text().replace('LE0211OV01', args.label)
js = (reference / 'viewer.js').read_text()
(out / 'embed.html').write_text(site)
(out / 'viewer.js').write_text(js)
shutil.copytree(reference / 'draco', out / 'draco', dirs_exist_ok=True)
shutil.copytree(reference / 'licenses', out / 'licenses', dirs_exist_ok=True)
shutil.copytree(reference / 'developer-source', out / 'developer-source', dirs_exist_ok=True)
shutil.copy2(root / 'presets/ring-webgl-studio-v1/preset.json', out / 'preset.json')
wrapper = (out / 'draco/draco_wasm_wrapper.js').read_text().replace('</script', '<\\/script')
wasm = base64.b64encode((out / 'draco/draco_decoder.wasm').read_bytes()).decode()
model = base64.b64encode(final).decode()
inline = '<script id="ring-data" type="application/octet-stream">' + model + '</script>\n'
inline += '<script id="draco-wrapper" type="application/x-draco">' + wrapper + '</script>\n'
inline += '<script id="draco-wasm" type="application/octet-stream">' + wasm + '</script>\n'
inline += '<script>' + js.replace('</script', '<\\/script') + '</script>'
(out / 'index.html').write_text(site.replace('<script src="./viewer.js"></script>', inline))
(work / 'glb-manifest.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2))
print(json.dumps({'glb_bytes': len(final), 'offline_html_bytes': (out / 'index.html').stat().st_size, 'meshes': len(doc['meshes']), 'images': len(doc.get('images', []))}))
