"""Repair degenerate tangent vectors before Draco encoding and remove unused gem UVs."""
from pathlib import Path
import json,struct,math,ctypes as c,argparse,copy
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project',default='ring-webgl-v1')
arguments=parser.parse_args()
root=Path.cwd();asset=root/'public/assets'/arguments.project;work=root/'work'/arguments.project
work.mkdir(parents=True,exist_ok=True)
path=asset/'ring-contact-v1.glb'
raw=path.read_bytes();size=struct.unpack_from('<I',raw,12)[0]
doc=json.loads(raw[20:20+size]);binary=bytearray(raw[28+size:])
views=doc['bufferViews'];accessors=doc['accessors']
# Blender can share index/attribute accessors between identical pave stones.
# Each Draco stream needs its own accessor metadata before counts are updated.
seen_accessors=set()
for mesh in doc['meshes']:
 for primitive in mesh['primitives']:
  references=[('indices',primitive['indices'])]+list(primitive['attributes'].items())
  for semantic,index in references:
   if index in seen_accessors:
    accessors.append(copy.deepcopy(accessors[index]));new_index=len(accessors)-1
    if semantic=='indices':primitive['indices']=new_index
    else:primitive['attributes'][semantic]=new_index
   seen_accessors.add(index)
def read_accessor(index):
 a=accessors[index];v=views[a['bufferView']];offset=v.get('byteOffset',0)+a.get('byteOffset',0)
 return a,v,offset
fixed=0
for mesh in doc['meshes']:
 for p in mesh['primitives']:
  attrs=p['attributes']
  material_name=doc['materials'][p['material']].get('name','')
  if material_name.startswith('Diamond'):
   attrs.pop('TANGENT',None);attrs.pop('TEXCOORD_0',None)
  if 'TANGENT' not in attrs:continue
  a,v,offset=read_accessor(attrs['TANGENT']);n,nv,noffset=read_accessor(attrs['NORMAL'])
  for i in range(a['count']):
   t=struct.unpack_from('<4f',binary,offset+i*16)
   length=math.sqrt(sum(x*x for x in t[:3]))
   if length>0.00001:continue
   nx,ny,nz=struct.unpack_from('<3f',binary,noffset+i*12)
   # An orthogonal basis is sufficient where the UV triangle has zero area.
   if abs(nx)<0.8:tx,ty,tz=0,nz,-ny
   else:tx,ty,tz=-nz,0,nx
   length=math.sqrt(tx*tx+ty*ty+tz*tz)
   struct.pack_into('<4f',binary,offset+i*16,tx/length,ty/length,tz/length,1)
   fixed+=1

def glb(document,data):
 data=bytes(data)+b'\0'*((-len(data))%4);document['buffers']=[{'byteLength':len(data)}]
 j=json.dumps(document,separators=(',',':'),ensure_ascii=False).encode();j+=b' '*((-len(j))%4)
 return struct.pack('<III',0x46546c67,2,28+len(j)+len(data))+struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(data),0x004e4942)+data
(work/'ring-corrected-uncompressed.glb').write_bytes(glb(doc,binary))
lib=c.CDLL(str(root/'work/tools/blender/Blender.app/Contents/Resources/4.3/python/lib/python3.11/site-packages/libextern_draco.dylib'))
functions={
 'encoderCreate':(c.c_void_p,[c.c_uint32]),'encoderRelease':(None,[c.c_void_p]),
 'encoderSetCompressionLevel':(None,[c.c_void_p,c.c_uint32]),
 'encoderSetQuantizationBits':(None,[c.c_void_p]+[c.c_uint32]*5),
 'encoderSetIndices':(None,[c.c_void_p,c.c_size_t,c.c_uint32,c.c_void_p]),
 'encoderSetAttribute':(c.c_uint32,[c.c_void_p,c.c_char_p,c.c_size_t,c.c_char_p,c.c_void_p,c.c_bool]),
 'encoderEncode':(c.c_bool,[c.c_void_p,c.c_uint8]),
 'encoderGetEncodedVertexCount':(c.c_uint32,[c.c_void_p]),'encoderGetEncodedIndexCount':(c.c_uint32,[c.c_void_p]),
 'encoderGetByteLength':(c.c_uint64,[c.c_void_p]),'encoderCopy':(None,[c.c_void_p,c.c_void_p])}
for name,(result,args) in functions.items():f=getattr(lib,name);f.restype=result;f.argtypes=args
new_data=bytearray();new_views=[]
def append(data):
 new_data.extend(b'\0'*((-len(new_data))%4));offset=len(new_data);new_data.extend(data)
 new_views.append({'buffer':0,'byteOffset':offset,'byteLength':len(data)})
 return len(new_views)-1
for image in doc['images']:
 view=views[image['bufferView']];offset=view.get('byteOffset',0)
 image['bufferView']=append(binary[offset:offset+view['byteLength']])
component_sizes={5121:1,5122:2,5123:2,5125:4,5126:4};dimensions={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}
for mesh in doc['meshes']:
 for p in mesh['primitives']:
  attrs=p['attributes'];count=accessors[attrs['POSITION']]['count'];encoder=lib.encoderCreate(count)
  keep=[];ids={}
  for name,index in attrs.items():
   a,v,offset=read_accessor(index)
   length=a['count']*dimensions[a['type']]*component_sizes[a['componentType']]
   buffer=c.create_string_buffer(bytes(binary[offset:offset+length]));keep.append(buffer)
   ids[name]=lib.encoderSetAttribute(encoder,name.encode(),a['componentType'],a['type'].encode(),buffer,a.get('normalized',False))
  a,v,offset=read_accessor(p['indices']);length=a['count']*component_sizes[a['componentType']]
  indices=c.create_string_buffer(bytes(binary[offset:offset+length]));keep.append(indices)
  lib.encoderSetIndices(encoder,a['componentType'],a['count'],indices)
  lib.encoderSetCompressionLevel(encoder,7);lib.encoderSetQuantizationBits(encoder,16,14,16,12,16)
  if not lib.encoderEncode(encoder,0):raise RuntimeError('Draco encoding failed')
  size=lib.encoderGetByteLength(encoder);encoded=c.create_string_buffer(size);lib.encoderCopy(encoder,encoded)
  p.setdefault('extensions',{})['KHR_draco_mesh_compression']={'bufferView':append(encoded.raw),'attributes':ids}
  a['count']=lib.encoderGetEncodedIndexCount(encoder);a.pop('bufferView',None);a.pop('byteOffset',None)
  for index in attrs.values():
   accessors[index]['count']=lib.encoderGetEncodedVertexCount(encoder);accessors[index].pop('bufferView',None);accessors[index].pop('byteOffset',None)
  lib.encoderRelease(encoder)
used=set()
for mesh in doc['meshes']:
 for p in mesh['primitives']:used.add(p['indices']);used.update(p['attributes'].values())
remap={old:new for new,old in enumerate(sorted(used))};doc['accessors']=[accessors[i] for i in sorted(used)]
for mesh in doc['meshes']:
 for p in mesh['primitives']:
  p['indices']=remap[p['indices']];p['attributes']={k:remap[i] for k,i in p['attributes'].items()}
doc['bufferViews']=new_views
for field in ['extensionsUsed','extensionsRequired']:
 if 'KHR_draco_mesh_compression' not in doc.setdefault(field,[]):doc[field].append('KHR_draco_mesh_compression')
output=glb(doc,new_data);(asset/'ring-draco-v1.glb').write_bytes(output)
print(json.dumps({'corrected_tangents':fixed,'compressed_bytes':len(output)}))
