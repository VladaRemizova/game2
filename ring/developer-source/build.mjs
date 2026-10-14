import {build} from 'esbuild';
import {createHash} from 'node:crypto';
import {readFile, readdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const developer = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(developer);

await build({
  absWorkingDir: developer,
  entryPoints: ['studio/RingBrightViewer.ts'],
  outfile: path.join(root, 'viewer.js'),
  bundle: true,
  minify: true,
  format: 'iife',
  target: 'es2020',
  legalComments: 'eof',
});

const read = (name) => readFile(path.join(root, name));
const escapedScript = (text) => text.replace(/<\/script/gi, '<\\/script');
const scripts = [
  '<script id="ring-data" type="application/octet-stream">' + (await read('ring-web-v1.glb')).toString('base64') + '</script>',
  '<script id="draco-wrapper" type="application/x-draco">' + escapedScript((await read('draco/draco_wasm_wrapper.js')).toString()) + '</script>',
  '<script id="draco-wasm" type="application/octet-stream">' + (await read('draco/draco_decoder.wasm')).toString('base64') + '</script>',
  '<script>' + escapedScript((await read('viewer.js')).toString()) + '</script>',
].join('\n');
const embed = (await read('embed.html')).toString();
const externalScript = '<script src="./viewer.js?v=bright-studio-v2"></script>';
if (!embed.includes(externalScript)) throw new Error('Viewer script tag not found in embed.html');
await writeFile(path.join(root, 'index.html'), embed.replace(externalScript, () => scripts));

const hashes = {};
async function collect(directory, prefix = '') {
  const entries = (await readdir(directory, {withFileTypes: true})).sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of entries) {
    if (['node_modules', '.git', 'sha256.json'].includes(entry.name) || entry.isSymbolicLink()) continue;
    const relative = prefix + entry.name;
    if (entry.isDirectory()) await collect(path.join(directory, entry.name), relative + '/');
    else if (entry.isFile()) hashes[relative] = createHash('sha256').update(await read(relative)).digest('hex');
  }
}
await collect(root);
await writeFile(path.join(root, 'sha256.json'), JSON.stringify(hashes, null, 2) + '\n');
console.log('Built bright studio viewer, standalone HTML and SHA-256 manifest.');
