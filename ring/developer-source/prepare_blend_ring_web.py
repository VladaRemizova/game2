"""Prepare a jewellery Blender scene for the accepted GLB viewer.

Run with Blender --background --factory-startup --disable-autoexec INPUT.blend
--python src/three/prepare_blend_ring_web.py -- --project NAME --ratio 0.18.
The input file is never saved. Only evaluated copies are edited.
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np


def parse_arguments():
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--ratio', type=float, default=0.18)
    return parser.parse_args(args)


def select_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def main():
    args = parse_arguments()
    root = Path.cwd()
    asset = root / 'public/assets' / args.project
    work = root / 'work' / args.project
    textures = asset / 'textures'
    textures.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    preset = json.loads((root / 'presets/ring-webgl-studio-v1/preset.json').read_text())
    scene = bpy.context.scene
    # The supplied scene has compositor file outputs with paths in Downloads.
    scene.use_nodes = False
    for layer in list(scene.view_layers)[1:]:
        scene.view_layers.remove(layer)
    original_meshes = [o for o in scene.objects if o.type == 'MESH']
    source_metal = next(o for o in original_meshes if any(c.name == 'Metal' for c in o.users_collection))
    source_gems = [o for o in original_meshes if any(c.name == 'Gems' for c in o.users_collection)]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    originals = [source_metal] + source_gems
    copies = []
    for original in originals:
        evaluated = original.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        obj = bpy.data.objects.new('Prepared_' + original.name, mesh)
        scene.collection.objects.link(obj)
        obj.matrix_world = original.matrix_world.copy()
        copies.append(obj)
    for obj in list(scene.objects):
        if obj not in copies:
            bpy.data.objects.remove(obj, do_unlink=True)
    metal = copies[0]
    gems = copies[1:]
    select_only(metal)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    metal.data.calc_loop_triangles()
    original_triangles = len(metal.data.loop_triangles)
    high = bpy.data.objects.new('Original_Metal_QA', metal.data.copy())
    scene.collection.objects.link(high)
    high.hide_render = True
    high.hide_set(True)

    decimate = metal.modifiers.new('Measured conservative reduction', 'DECIMATE')
    decimate.ratio = args.ratio
    decimate.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=decimate.name)
    normals = metal.modifiers.new('Preserve original polished normals', 'DATA_TRANSFER')
    normals.object = high
    normals.use_loop_data = True
    normals.data_types_loops = {'CUSTOM_NORMAL'}
    normals.loop_mapping = 'POLYINTERP_NEAREST'
    bpy.ops.object.modifier_apply(modifier=normals.name)
    # The artist's generated cylindrical logo UVs overlap. Keep those for shader
    # sampling and bake to a second, unique UV atlas for portable GLB materials.
    source_uv = metal.data.uv_layers.active
    source_uv.name = 'SourceLogoUV'
    bake_material = metal.data.materials[0].copy()
    bake_material.name = 'Source material baking'
    metal.data.materials.clear()
    metal.data.materials.append(bake_material)
    for node in bake_material.node_tree.nodes:
        if node.type == 'UVMAP':
            node.uv_map = 'SourceLogoUV'
    bake_uv = metal.data.uv_layers.new(name='WebBakeUV')
    metal.data.uv_layers.active = bake_uv
    bake_uv.active_render = True
    select_only(metal)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.1519173, island_margin=0.012, correct_aspect=True, scale_to_bounds=True)
    bpy.ops.object.mode_set(mode='OBJECT')

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 16
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'METAL'
    scene.cycles.device = 'GPU'
    scene.render.bake.target = 'IMAGE_TEXTURES'
    scene.render.bake.margin = 16
    scene.render.bake.use_selected_to_active = False
    nodes = bake_material.node_tree.nodes
    links = bake_material.node_tree.links
    output = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
    emission = nodes.new('ShaderNodeEmission')
    target = nodes.new('ShaderNodeTexImage')
    nodes.active = target
    mask = nodes['Float Curve'].outputs['Value']
    # Mix has several sockets named Result; follow the actual RGB connection.
    base = nodes['Principled BSDF'].inputs['Base Color'].links[0].from_socket
    metallic = nodes.new('ShaderNodeMath')
    metallic.operation = 'SUBTRACT'
    metallic.inputs[0].default_value = 1
    links.new(mask, metallic.inputs[1])
    roughness = nodes.new('ShaderNodeMath')
    roughness.operation = 'MULTIPLY_ADD'
    original_roughness = nodes['Principled BSDF'].inputs['Roughness'].default_value
    engraving_roughness = nodes['Principled BSDF.001'].inputs['Roughness'].default_value
    links.new(mask, roughness.inputs[0])
    roughness.inputs[1].default_value = engraving_roughness - original_roughness
    roughness.inputs[2].default_value = original_roughness

    def reconnect_surface(socket):
        for link in list(output.inputs['Surface'].links):
            links.remove(link)
        links.new(socket, output.inputs['Surface'])

    def bake(name, socket=None, normal=False):
        image = bpy.data.images.new(name, width=2048, height=2048, alpha=False)
        image.colorspace_settings.name = 'sRGB' if name == 'base-color' else 'Non-Color'
        image.generated_color = (0.5, 0.5, 1, 1) if normal else (0.8, 0.8, 0.8, 1)
        target.image = image
        nodes.active = target
        if normal:
            # The original Bump node carries the engraving relief. A neutral
            # surface avoids the source's camera-dependent shader/alpha mixes.
            shader = nodes.new('ShaderNodeBsdfPrincipled')
            links.new(nodes['Bump'].outputs['Normal'], shader.inputs['Normal'])
            reconnect_surface(shader.outputs['BSDF'])
            scene.render.bake.normal_space = 'TANGENT'
            bpy.ops.object.bake(type='NORMAL')
        else:
            for link in list(emission.inputs['Color'].links):
                links.remove(link)
            links.new(socket, emission.inputs['Color'])
            reconnect_surface(emission.outputs[0])
            bpy.ops.object.bake(type='EMIT')
        image.filepath_raw = str(textures / (name + '.png'))
        image.file_format = 'PNG'
        image.save()
        print('BAKED', name, flush=True)
        return image

    maps = {
        'Base Color': bake('base-color', base),
        'Metallic': bake('metallic', metallic.outputs[0]),
        'Roughness': bake('roughness', roughness.outputs[0]),
    }
    normal_image = bake('normal', normal=True)
    portable = bpy.data.materials.new('Polished white gold · baked original engraving')
    portable.use_nodes = True
    pn = portable.node_tree.nodes
    pl = portable.node_tree.links
    principled = pn.get('Principled BSDF')
    principled.inputs['Metallic'].default_value = 1
    principled.inputs['Roughness'].default_value = 1
    for socket, image in maps.items():
        tex = pn.new('ShaderNodeTexImage')
        tex.image = image
        tex.extension = 'EXTEND'
        pl.new(tex.outputs['Color'], principled.inputs[socket])
    tex = pn.new('ShaderNodeTexImage')
    tex.image = normal_image
    tex.extension = 'EXTEND'
    normal = pn.new('ShaderNodeNormalMap')
    normal.uv_map = 'WebBakeUV'
    pl.new(tex.outputs['Color'], normal.inputs['Color'])
    pl.new(normal.outputs['Normal'], principled.inputs['Normal'])
    metal.data.materials.clear()
    metal.data.materials.append(portable)
    # Source UVs are no longer needed once the original logo shader is baked.
    metal.data.uv_layers.remove(metal.data.uv_layers['SourceLogoUV'])
    metal.data.uv_layers.active = metal.data.uv_layers['WebBakeUV']
    metal.data.uv_layers.active.active_render = True
    metal.name = 'WhiteGold_00'
    metal['role'] = 'metal'

    # Keep every supplied gemstone facet. Only split disconnected stones.
    for gem in gems:
        select_only(gem)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')
    gems = [o for o in scene.objects if o.type == 'MESH' and o not in [metal, high]]
    gems.sort(key=lambda o: max(o.dimensions), reverse=True)
    diamond = bpy.data.materials.new('Diamond · IOR 2.42')
    diamond.use_nodes = True
    dp = diamond.node_tree.nodes.get('Principled BSDF')
    dp.inputs['Base Color'].default_value = (1, 1, 1, 1)
    dp.inputs['Roughness'].default_value = preset['diamond']['standard_glb_fallback']['roughness']
    dp.inputs['IOR'].default_value = preset['diamond']['ior']
    dp.inputs['Transmission Weight'].default_value = 1
    for i, gem in enumerate(gems):
        gem.name = 'Diamond_Centre' if i == 0 else f'Diamond_Pave_{i:02d}'
        gem.data.materials.clear()
        gem.data.materials.append(diamond)
        for poly in gem.data.polygons:
            poly.use_smooth = False
        gem['role'] = 'diamond'
        gem['hero'] = i == 0
    bpy.data.objects.remove(high, do_unlink=True)

    # Bake contact shading while the source coordinates are still millimetres.
    ao_material = bpy.data.materials.new('Soft contact shading bake')
    ao_material.use_nodes = True
    an = ao_material.node_tree.nodes
    an.clear()
    al = ao_material.node_tree.links
    ao = an.new('ShaderNodeAmbientOcclusion')
    ao.inputs['Distance'].default_value = preset['metal']['contact_shading']['ao_distance_reference_meters'] / scene.unit_settings.scale_length
    ae = an.new('ShaderNodeEmission')
    ao_out = an.new('ShaderNodeOutputMaterial')
    al.new(ao.outputs['Color'], ae.inputs['Color'])
    al.new(ae.outputs[0], ao_out.inputs['Surface'])
    colors = metal.data.color_attributes.new(name='ContactShading', type='FLOAT_COLOR', domain='CORNER')
    metal.data.color_attributes.active_color = colors
    metal.data.materials.clear()
    metal.data.materials.append(ao_material)
    scene.cycles.samples = preset['metal']['contact_shading']['bake_samples']
    scene.render.bake.target = 'VERTEX_COLORS'
    select_only(metal)
    bpy.ops.object.bake(type='EMIT')
    corner_colors = np.empty(len(colors.data) * 4, dtype=np.float32)
    colors.data.foreach_get('color', corner_colors)
    indices = np.empty(len(metal.data.loops), dtype=np.int32)
    metal.data.loops.foreach_get('vertex_index', indices)
    sums = np.bincount(indices, weights=corner_colors.reshape(-1, 4)[:, 0], minlength=len(metal.data.vertices))
    counts = np.maximum(1, np.bincount(indices, minlength=len(metal.data.vertices)))
    values = 0.62 + 0.38 * np.clip(sums / counts, 0, 1)
    metal.data.color_attributes.remove(colors)
    colors = metal.data.color_attributes.new(name='ContactShading', type='FLOAT_COLOR', domain='POINT')
    metal.data.color_attributes.active_color = colors
    rgba = np.ones((len(values), 4), dtype=np.float32)
    rgba[:, :3] = values[:, None]
    colors.data.foreach_set('color', rgba.ravel())
    metal.data.materials.clear()
    metal.data.materials.append(portable)
    # Record the optimised source in a QA-only file, before unit conversion.
    metal.data.calc_loop_triangles()
    report = {
        'source_file': bpy.data.filepath, 'ratio': args.ratio,
        'source_metal_triangles': original_triangles,
        'optimized_metal_triangles': len(metal.data.loop_triangles),
        'gems': len(gems), 'gem_triangles': sum(sum(len(p.vertices) - 2 for p in g.data.polygons) for g in gems),
        'texture_resolution': 2048,
    }
    factor = scene.unit_settings.scale_length
    for obj in [metal] + gems:
        # All object transforms were applied, so converting vertices is enough.
        for vertex in obj.data.vertices:
            vertex.co *= factor
        select_only(obj)
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    scene.unit_settings.scale_length = 1
    bpy.ops.object.select_all(action='SELECT')
    output_glb = asset / 'ring-contact-v1.glb'
    bpy.ops.export_scene.gltf(
        filepath=str(output_glb), export_format='GLB', use_selection=True,
        export_extras=True, export_yup=True, export_texcoords=True,
        export_normals=True, export_tangents=True, export_vertex_color='ACTIVE',
        export_materials='EXPORT', export_image_format='AUTO',
        export_cameras=False, export_lights=False, export_animations=False,
    )
    report['uncompressed_glb_bytes'] = output_glb.stat().st_size
    (work / 'prepare-report.json').write_text(json.dumps(report, indent=2))
    print('PREPARED', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
