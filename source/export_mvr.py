# SPDX-FileCopyrightText: 2025 Sebastian Schrand
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Export is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import time
import mathutils
import bpy_extras
import py_mvr as pymvr
from pathlib import Path
from py_mvr.value import Matrix, Color
from bpy_extras import node_shader_utils
from io_scene_3ds.export_3ds import save_3ds


def get_filepath(file, assets):
    filepath = None

    for root, dirs, files in os.walk(assets):
        if file in files or file.replace(' ','_') in files:
            filepath = os.path.join(root, file)

    return filepath


def get_gdtf_name(name):
    gdtf_name = name.replace(' ', '_')

    if '@' not in name:
        gdtf_name = '@'.join(name.split('_'))
    else:
        split_name = name.split('@')
        if len(split_name) > 2:
            gdtf_name = '@'.join((split_name[0], split_name[1]))
    if not gdtf_name.split('.')[-1] == "gdtf":
        gdtf_name = '.'.join((gdtf_name, "gdtf"))

    return gdtf_name


def convert_rgb(rgb):
    red = rgb[0]
    green = rgb[1]
    blue = rgb[2]

    def invert_gamma(color):
        if color > 0.04045:
            return ((color + 0.055) / 1.055) ** 2.4
        else:
            return color / 12.92

    r_linear = invert_gamma(red)
    g_linear = invert_gamma(green)
    b_linear = invert_gamma(blue)

    r_linear *= 100
    g_linear *= 100
    b_linear *= 100

    X = r_linear * 0.4124 + g_linear * 0.3576 + b_linear * 0.1805
    Y = r_linear * 0.2126 + g_linear * 0.7152 + b_linear * 0.0722
    Z = r_linear * 0.0193 + g_linear * 0.1192 + b_linear * 0.9505

    denom = X + Y + Z
    if denom == 0:
        x = 0
        y = 0
    else:
        x = X / denom
        y = Y / denom

    return (x, y, Y)


def get_material_images(material, path):
    images = []

    def get_image(image):
        if image:
            img_name = Path(image.filepath).name
            file_path = os.path.join(path, img_name)
            if not os.path.isfile(file_path):
                image.save(filepath=file_path)
            images.append((file_path, img_name))

    if material and material.node_tree and not (material.get("Geometry Type") == "Gobo"):
        mtype = 'MIX', 'MIX_RGB'
        links = material.node_tree.links
        mtex = [lk.from_node for lk in links if lk.from_node.type == 'TEX_IMAGE' and lk.to_node.type in mtype]
        bsdf = node_shader_utils.PrincipledBSDFWrapper(material)

        if bsdf.base_color_texture:
            get_image(bsdf.base_color_texture.image)
        if mtex:
            for tex in mtex:
                get_image(tex.image)
        if bsdf.specular_tint_texture:
            get_image(bsdf.specular_tint_texture.image)
        if bsdf.alpha_texture:
            get_image(bsdf.alpha_texture.image)
        if bsdf.metallic_texture:
            get_image(bsdf.metallic_texture.image)
        if bsdf.roughness_texture:
            get_image(bsdf.roughness_texture.image)
        if bsdf.normalmap_texture:
            get_image(bsdf.normalmap_texture.image)

    return list(set(images))


def get_trans_matrix(mtx, obj=None):
    if obj:
        mtx_copy = obj.matrix_world.copy()
        mtx = mtx_copy @ mtx
    translate = mtx.to_translation()
    scale = mathutils.Matrix().to_scale()
    rotate = mathutils.Matrix.LocRotScale(translate, mtx.to_3x3(), scale).transposed().to_3x3()
    trans_mtx = Matrix(list((rotate[0][:], rotate[1][:], rotate[2][:], translate[:])))
    return trans_mtx


def export_3ds(context, path, objects, selection, matrix, collection=""):
    save_3ds(context, path, collection, objects, 1000, matrix, selection)


def get_fixture(context, fixture, objects, profiles, folders, selection, targets, matrix):
    Path(folders).mkdir(parents=True, exist_ok=True)
    patch_numbers = []
    uid = fixture.get("UUID")
    file_path = focus_point = None
    gdtf_name = fixture.get("GDTF Name")
    gdtf_specs = get_gdtf_name(gdtf_name)
    fixture_name = fixture.get("Fixture Name")
    props = ["Patch Break", "Patch Universe", "Patch Address"]
    base = next((ob for ob in fixture.objects if ob.get("Use Root")), None)
    target = next((ob for ob in fixture.objects if ob.get("Geometry Type") == "Target"), None)
    fix_id = fixture.get("Fixture ID")
    fix_mode = base.get("Fixture Mode")
    transmtx = get_trans_matrix(matrix, base)

    for root, dirs, files in os.walk(profiles):
        for file in files:
            fixture_type = get_gdtf_name(file)
            if (fixture_type == gdtf_specs) or (fixture_type.replace(' ', '_') == gdtf_specs):
                file_path = os.path.join(root, file)
                break

    if target and targets:
        target_uid = target.get("UUID")
        target_name = target.get("Fixture Name")
        target_mtx = get_trans_matrix(matrix, target)
        print("exporting FocusPoint... %s" % target_name)
        focus_point = pymvr.FocusPoint(uuid=target_uid, name=target_name, matrix=target_mtx).to_xml()
        if target.children:
            geometries = pymvr.Geometries()
            
            for ob in target.children_recursive:
                if ob.type == 'MESH':
                    objects.extend(get_material_images(ob.active_material, folders))

            target_mesh = '.'.join((' '.join((target_name, "Target")), "3ds"))
            mvr_object = pymvr.Geometry3D(file_name=target_mesh)
            geometries.geometry3d.append(mvr_object)
            file_path = os.path.join(folders, target_mesh)
            export_3ds(context, file_path, target.children_recursive, selection, matrix)
            objects.append((file_path, target_mesh))
            geometries.to_xml(parent=focus_point)
        fix_object = pymvr.Fixture(name=fixture_name, uuid=uid, gdtf_spec=gdtf_specs, gdtf_mode=fix_mode,
                                   matrix=transmtx, fixture_id=str(fix_id), fixture_id_numeric=fix_id, focus=target_uid)
    else:
        fix_object = pymvr.Fixture(name=fixture_name, uuid=uid, gdtf_spec=gdtf_specs, gdtf_mode=fix_mode,
                                   matrix=transmtx, fixture_id=str(fix_id), fixture_id_numeric=fix_id)

    fix_object.addresses.clear()
    for prop in props:
        patch_numbers.append(fixture.get(prop) if fixture.get(prop) is not None else 0)

    patch = pymvr.Address(dmx_break=patch_numbers[0], universe=patch_numbers[1], address=patch_numbers[2])
    fix_object.addresses.append(patch)
    patch_numbers.clear()

    if base and base.get("RGB Beam") is not None:
        color_xy = convert_rgb(base.get("RGB Beam"))
    elif base and base.get("RGB Glow") is not None:
        color_xy = convert_rgb(base.get("RGB Glow"))
    else:
        color_xy = convert_rgb((1.0, 1.0, 1.0))
    fix_object.color = Color(x=color_xy[0], y=color_xy[1], Y=color_xy[2])

    return objects, fix_object, file_path, focus_point


def export_geometry(context, obj, objects, assets, folder, selection, matrix):

    def get_3ds(ob, name):
        file_path = os.path.join(folder, name)
        export_3ds(context, file_path, [ob], selection, matrix)

    mesh_export = True
    if obj.active_material and not (obj.parent and obj.parent.get("Geometry Type") == "Target"):
        objects.extend(get_material_images(obj.active_material, folder))
    geometry = '.'.join((obj.name, "3ds"))
    file_path = os.path.join(folder, geometry)
    if obj.data and obj.get("MVR Class") in {"Symdef", "SceneObject"}:
        mesh_file = obj.data.get("Reference")
        mesh_path = get_filepath(mesh_file, assets)
        if mesh_path:
            mesh_export = False
            geometry = mesh_file
            file_path = mesh_path
    if mesh_export:
        get_3ds(obj, geometry)

    mvr_object = pymvr.Geometry3D(file_name=geometry)
    if (file_path, geometry) not in objects:
        objects.append((file_path, geometry))

    return objects, mvr_object
             

                   
def save_mvr(context, items, filename, fixturepath="", selection=False, fixtures=True, targets=True, matrix=mathutils.Matrix()):

    layer = None
    file_list = []
    start_time = time.time()

    current_path = os.path.dirname(os.path.realpath(__file__))
    assets_path = os.path.join(current_path, "assets", "mvr")
    folder_path = os.path.join(assets_path, Path(filename).stem)
    Path(folder_path).mkdir(parents=True, exist_ok=True)

    def export_fixture(profile, collect, filelist):
        print("exporting Fixture... %s" % profile.name)
        profile_path = assets_path
        if fixturepath:
            profile_path = fixturepath
        fixture_data = get_fixture(context, profile, filelist, profile_path,
                                   folder_path, selection, targets, matrix)
        filelist, fix_object, file_path, focuspoint = fixture_data
        if file_path:
            filelist.append((file_path, Path(file_path).name))
        collect.append(fix_object.to_xml())
        if focuspoint:
            collect.append(focuspoint)

    try:
        mvr = pymvr.GeneralSceneDescriptionWriter()
        user = pymvr.UserData().to_xml(parent=mvr.xml_root)
        scene = pymvr.SceneElement().to_xml(parent=mvr.xml_root)
        layers = pymvr.LayersElement().to_xml(parent=scene)
        pymvr.Data().to_xml(parent=user)
        auxdata = pymvr.AUXData()
        auxdata.symdefs.clear()
        for item in items.children:
            is_gdtf = True if item.get("Company") else False
            if item.get("MVR Class") == "Layer":
                print("exporting Layer... %s" % item.name)
                layer = pymvr.Layer(name=item.get("MVR Name"), uuid=item.get("UUID")).to_xml(parent=layers)
                child_list = pymvr.ChildList().to_xml(parent=layer)
                for ob in item.objects:
                    print("creating SceneObject... %s" % ob.name)
                    if ob.get("MVR Class") == "Symbol":
                        uid = ob.get("Reference")
                        trans = ob.get("Transform")
                        symbol_name = ob.get("MVR Name")
                        transmtx = Matrix(list((trans[:3], trans[3:6], trans[6:9], trans[9:])))
                        scene_object = pymvr.SceneObject(uuid=ob.get("UUID"), name=symbol_name, matrix=transmtx).to_xml()
                        geometries = pymvr.Geometries()
                        print("exporting Symbol... %s" % symbol_name)
                        instance = ob.instance_collection.get("Reference") if ob.instance_collection else ob.get("Reference")
                        mvr_object = pymvr.Symbol(uuid=uid, symdef=instance)
                        geometries.symbol.append(mvr_object)
                        geometries.to_xml(parent=scene_object)
                    else:
                        transmtx = get_trans_matrix(matrix, ob)
                        scene_object = pymvr.SceneObject(name=ob.name, matrix=transmtx).to_xml()
                        geometries = pymvr.Geometries()
                        print("exporting Geometry3D... %s.3ds" % ob.name)
                        file_list, mvr_object = export_geometry(context, ob, file_list, assets_path, folder_path, selection, matrix)
                        geometries.geometry3d.append(mvr_object)
                        geometries.to_xml(parent=scene_object)
                    child_list.append(scene_object)
                    geometries.geometry3d.clear()
                    geometries.symbol.clear()

            if item.name == "AUXData":
                print("exporting AUXData...")
                for child in item.children:
                    symdef_uid = child.get("UUID")
                    print("creating Symdef... %s" % child.name)
                    symdef = pymvr.Symdef(uuid=symdef_uid, name=child.name).to_xml()
                    symlist = pymvr.ChildList().to_xml(parent=symdef)

                    for geo in child.children:
                        geo_name = geo.name
                        file_path = None
                        for ob in geo.objects:
                            if ob.type == 'MESH':
                                geo_name = ob.data.get("Reference")
                                filepath = get_filepath(geo_name, assets_path)
                                if filepath and file_path is None:
                                    file_path = filepath
                                file_list.extend(get_material_images(ob.active_material, folder_path))
                        if file_path is None:
                            geo_name = '.'.join((ob.name, "3ds"))
                            file_path = os.path.join(folder_path, geo_name)
                            export_3ds(context, file_path, geo.all_objects, selection, matrix, geo.name)
                        print("exporting Geometry3D... %s" % geo_name)
                        mvr_object = pymvr.Geometry3D(file_name=geo_name).to_xml()
                        file_list.append((file_path, geo_name))
                        symlist.append(mvr_object)
                    auxdata.symdefs.append(symdef)

            elif fixtures and is_gdtf:
                print("exporting Layer... %s" % items.name)
                layer = pymvr.Layer(name=items.name).to_xml(parent=layers)
                child_list = pymvr.ChildList().to_xml(parent=layer)
                export_fixture(item, child_list, file_list)
            elif not is_gdtf and any(ob.type in {'MESH', 'EMPTY'} for ob in item.objects):
                print("creating SceneObject... %s" % item.name)
                layer = pymvr.Layer(name=items.name).to_xml(parent=layers)
                child_list = pymvr.ChildList().to_xml(parent=layer)
                transmtx = get_trans_matrix(matrix, item.objects[0])
                scene_object = pymvr.SceneObject(name=item.name, matrix=transmtx).to_xml()
                geometries = pymvr.Geometries()
                geo_name = '.'.join((item.name, "3ds"))
                file_path = os.path.join(folder_path, geo_name)
                print("exporting Geometry3D... %s" % geo_name)
                export_3ds(context, file_path, item.all_objects, selection, matrix, item.name)
                mvr_object = pymvr.Geometry3D(file_name=geo_name)
                geometries.geometry3d.append(mvr_object)
                file_list.append((file_path, geo_name))
                geometries.to_xml(parent=scene_object)
                geometries.geometry3d.clear()
                geometries.symbol.clear()

                for ob in item.objects:
                    if ob.type == 'MESH':
                        file_list.extend(get_material_images(ob.active_material, folder_path))
                child_list.append(scene_object)

            for child in item.children:
                is_fixture = child.get("Company")
                if fixtures and is_fixture:
                    export_fixture(child, child_list, file_list)
                elif child.objects and not is_fixture:
                    print("creating SceneObject... %s" % child.name)
                    geometries = pymvr.Geometries()
                    transmtx = get_trans_matrix(matrix)
                    trs = matrix[:3] + matrix[3:6] + matrix[6:9] + matrix[9:]
                    for ob in child.objects:
                        print("exporting Geometry3D... %s.3ds" % ob.name)
                        transform = ob.get("Transform")
                        if transform:
                            trs = transform[:9]
                            transmtx = Matrix(list((trs[:3], trs[3:6], trs[6:], transform[9:])))
                        else:
                            transmtx = get_trans_matrix(matrix, ob)
                        file_list, mvr_object = export_geometry(context, ob, file_list, assets_path, folder_path, selection, matrix)
                        geometries.geometry3d.append(mvr_object)
                    if child.get("MVR Class") == "SceneObject":
                        uid = child.get("UUID")
                        scene_object = pymvr.SceneObject(name=child.name, uuid=uid, matrix=transmtx).to_xml()
                    else:
                        scene_object = pymvr.SceneObject(name=child.name, matrix=transmtx).to_xml()
                    geometries.to_xml(parent=scene_object)
                    child_list.append(scene_object)
                    geometries.geometry3d.clear()
                    geometries.symbol.clear()

        auxdata.to_xml(parent=scene)
        auxdata.symdefs.clear()
        mvr.files_list = list(set(file_list))
        mvr.write_mvr(filename)
        file_size = Path(filename).stat().st_size

        if os.path.isdir(folder_path):
            [fl.unlink() for fl in Path(folder_path).iterdir() if fl.is_file()]
            Path(folder_path).rmdir()

    except Exception as exc:
        print(exc)

    print("MVR scene exported in %.4f sec.\n" % (time.time() - start_time))


def save(operator, context, filepath="", collection="", use_selection=False, use_fixtures=True,
         use_collection=False, use_targets=True, fixture_path="", global_matrix=None):

    context.window.cursor_set('WAIT')

    if global_matrix is None:
        global_matrix = mathutils.Matrix()

    layer_objects = []
    scene = context.scene
    viewlayer = context.view_layer
    items = viewlayer.layer_collection.collection
    depsgraph = context.evaluated_depsgraph_get()

    if use_collection:
        items = layer.active_layer_collection.collection
    elif collection:
        item_collection = bpy.data.collections.get(collection)
        if item_collection:
            items = item_collection

    save_mvr(context, items, filepath, fixture_path, use_selection, use_fixtures, use_targets, global_matrix)

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
