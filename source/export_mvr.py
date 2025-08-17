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
    if '@' not in name:
        gdtf_name = '@'.join(name.split())
    else:
        name = name.replace(' ', '_')
        split_name = name.split('@')
        if len(split_name) >= 2:
            gdtf_name = '@'.join((split_name[0], split_name[1]))
        else:
            gdtf_name = split_name[0]
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


def trans_matrix(trans_mtx):
    mtx = list(trans_mtx)
    matrix = mathutils.Matrix((mtx[:3]+[0], mtx[3:6]+[0], mtx[6:9]+[0], mtx[9:]+[1])).transposed()

    return matrix


def get_transmatrix(matrix, obj=None):
    if obj:
        mtx_copy = obj.matrix_world.copy()
        matrix = mtx_copy @ matrix
    if isinstance(matrix, tuple):
        matrix = trans_matrix(matrix)
    translate = matrix.to_translation()
    scale = mathutils.Matrix().to_scale()
    rotate = mathutils.Matrix.LocRotScale(translate, matrix.to_3x3(), scale).transposed().to_3x3()
    trans_mtx = list((rotate[0][:], rotate[1][:], rotate[2][:], translate[:]))

    return trans_mtx


def export_3ds(context, path, objects, SELECT, CONVERSE, collection=""):
    save_3ds(context, path, collection, objects, 1000, CONVERSE, SELECT)


def get_fixture(context, fixture, file_list, profiles, folders, SELECT, TARGETS, CONVERSE):
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
    transmtx = Matrix(get_transmatrix(CONVERSE, base))

    for root, dirs, files in os.walk(profiles):
        for file in files:
            fixture_type = get_gdtf_name(file)
            if (fixture_type == gdtf_specs) or (fixture_type.replace(' ', '_') == gdtf_specs):
                file_path = os.path.join(root, file)
                break

    if target and TARGETS:
        target_uid = target.get("UUID")
        target_name = target.get("Fixture Name")
        focus_name = target_name + " FocusPoint"
        focus_mtx = Matrix(get_transmatrix(CONVERSE, target))
        print("exporting FocusPoint... %s" % focus_name)
        focus_point = pymvr.FocusPoint(uuid=target_uid, name=focus_name, matrix=focus_mtx).to_xml()
        if target.children:
            geometries = pymvr.Geometries()
            
            for ob in target.children_recursive:
                if ob.type == 'MESH':
                    file_list.extend(get_material_images(ob.active_material, folders))

            target_mesh = '.'.join((' '.join((target_name, "Target")), "3ds"))
            print("exporting Geometry3D... %s" % target_mesh)
            mvr_object = pymvr.Geometry3D(file_name=target_mesh)
            geometries.geometry3d.append(mvr_object)
            file_path = os.path.join(folders, target_mesh)
            export_3ds(context, file_path, target.children_recursive, SELECT, CONVERSE, fixture.name)
            file_list.append((file_path, target_mesh))
            geometries.to_xml(parent=focus_point)
            geometries.geometry3d.clear()
            geometries.symbol.clear()
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

    return file_list, fix_object, file_path, focus_point      


def export_mvr(context, items, filename, fixturepath, folder_path, asset_path, SELECT, FIXTURES, TARGETS, CONVERSE):
    scene_name = Path(filename).stem
    child_list = group_list = None
    file_list = []

    print("creating Scene... %s" % scene_name)
    mvr = pymvr.GeneralSceneDescriptionWriter()
    user = pymvr.UserData().to_xml(parent=mvr.xml_root)
    scene = pymvr.SceneElement().to_xml(parent=mvr.xml_root)
    layers = pymvr.LayersElement().to_xml(parent=scene)
    pymvr.Data().to_xml(parent=user)
    auxdata = pymvr.AUXData()


    def export_fixture(profile, parent_name, child_list, file_list):
        if child_list is None:
            print("exporting Layer... %s" % parent_name)
            layer = pymvr.Layer(name=parent_name).to_xml(parent=layers)
            child_list = pymvr.ChildList().to_xml(parent=layer)
        print("exporting Fixture... %s" % profile.name)
        profile_path = asset_path
        if fixturepath:
            profile_path = fixturepath
        fixture_data = get_fixture(context, profile, file_list, profile_path,
                                   folder_path, SELECT, TARGETS, CONVERSE)
        file_list, fix_object, file_path, focus_point = fixture_data
        if file_path:
            file_list.append((file_path, Path(file_path).name))
        child_list.append(fix_object.to_xml())
        if focus_point:
            child_list.append(focus_point)


    def export_geometry(scene_obj, obj_name, file_list):
        class_name = scene_obj.__class__.__name__
        print("exporting Geometry3D... %s" % obj_name)
        file_path = os.path.join(folder_path, obj_name)
        file_list.append((file_path, obj_name))
        transmtx = Matrix(get_transmatrix(CONVERSE))
        geometry = pymvr.Geometry3D(file_name=obj_name)

        if isinstance(scene_obj, list):
            for obj in scene_obj:
                if obj.type == 'MESH' and (not SELECT and not ob.select_get()):
                    file_list.extend(get_material_images(ob.active_material, folder_path))
            trans = scene_obj.get("Transform")
            if trans:
                transmtx = Matrix(list(trans[:3], trans[3:6], trans[6:9], trans[9:]))
            else:
                transmtx = Matrix(get_transmatrix(CONVERSE, scene_obj))
            export_3ds(context, file_path, scene_obj, SELECT, CONVERSE)
                
        elif class_name == "Collection":
            average = CONVERSE.to_translation()
            for ob in scene_obj.objects:
                if ob.type == 'MESH' and (not SELECT and not ob.select_get()):
                    file_list.extend(get_material_images(ob.active_material, folder_path))
                transform = ob.get("Transform")
                if transform:
                    average += mathutils.Vector(tuple(trans[9:]))
                else:
                    average += ob.matrix_world.copy().to_translation()
            export_3ds(context, file_path, scene_obj.all_objects, SELECT, CONVERSE, scene_obj.name)
            amount = mathutils.Vector.Fill(3, len(scene_obj.objects))
            vector = tuple(average[i] / amount[i] for i in range(3))
            translate = mathutils.Matrix.Translation(vector)
            transmtx = Matrix(get_transmatrix(translate))

        elif class_name == "Object":
            object_list = [scene_obj]
            if scene_obj.type == 'MESH':
                file_list.extend(get_material_images(scene_obj.active_material, folder_path))
            for child in scene_obj.children_recursive:
                object_list.append(child)
                if child.type == 'MESH':
                    get_material_images(child.active_material, folder_path)
            trans = scene_obj.get("Transform")
            if trans:
                transmtx = Matrix(list(trans[:3], trans[3:6], trans[6:9], trans[9:]))
            else:
                transmtx = Matrix(get_transmatrix(CONVERSE, scene_obj))
            export_3ds(context, file_path, object_list, SELECT, CONVERSE)

        if scene_obj.get("MVR Class") == "SceneObject":
            uid = layer.get("UUID")
            scene_object = pymvr.SceneObject(name=scene_obj.name, uuid=uid, matrix=transmtx).to_xml()
        else:
            scene_object = pymvr.SceneObject(name=scene_obj.name, matrix=transmtx).to_xml()

        return scene_object, geometry


    def create_scene_object(scene_layer, child_list, file_list, single=False):
        mesh_list = pymvr.Geometries()
        if isinstance(scene_layer, list):
            for obj in scene_layer:
                if not (SELECT and not obj.select_get()):
                    print("creating SceneObject... %s" % obj.name)
                    mesh_name = '.'.join((obj.name, "3ds"))
                    scene_object, mvr_object = export_geometry(obj, mesh_name, file_list)
                    mesh_list.geometry3d.append(mvr_object)
                    mesh_list.to_xml(parent=scene_object)
                    child_list.append(scene_object)
                    mesh_list.geometry3d.clear()
                    mesh_list.symbol.clear()
        elif single:
            for obj in scene_layer.objects:
                if not (SELECT and not obj.select_get()):
                    if obj.parent is None:
                        print("creating SceneObject... %s" % obj.name)
                        mesh_name = '.'.join((obj.name, "3ds"))
                        scene_object, mvr_object = export_geometry(obj, mesh_name, file_list)
                        mesh_list.geometry3d.append(mvr_object)
                        mesh_list.to_xml(parent=scene_object)
                        child_list.append(scene_object)
                        mesh_list.geometry3d.clear()
                        mesh_list.symbol.clear()
        else:
            print("creating SceneObject... %s" % scene_layer.name)
            mesh_name = '.'.join((scene_obj.name, "3ds"))
            scene_object, mvr_object = export_geometry(scene_layer, mesh_name, file_list)
            mesh_list.geometry3d.append(mvr_object)
            mesh_list.to_xml(parent=scene_object)
            child_list.append(scene_object)
            mesh_list.geometry3d.clear()
            mesh_list.symbol.clear()

        return child_list, file_list


    print("exporting Layers... %s" % items.name)
    for item in items.children:
        is_gdtf = item.get("Company")
        if item.get("MVR Class") == "Layer":
            print("exporting Layer... %s" % item.name)
            layer = pymvr.Layer(name=item.get("MVR Name"), uuid=item.get("UUID")).to_xml(parent=layers)
            child_list = pymvr.ChildList().to_xml(parent=layer)
            for ob in item.objects:
                print("creating SceneObject... %s" % ob.name)
                geometries = pymvr.Geometries()
                if ob.get("MVR Class") == "Symbol":
                    symbol_name = ob.get("MVR Name")
                    print("exporting Symbol... %s" % symbol_name)
                    uid = ob.get("Reference")
                    meshes = geometries.symbol
                    transform = ob.get("Transform")
                    transmtx = Matrix(get_transmatrix(transform))
                    scene_object = pymvr.SceneObject(uuid=ob.get("UUID"), name=symbol_name, matrix=transmtx).to_xml()
                    instance = ob.instance_collection.get("Reference") if ob.instance_collection else ob.get("Reference")
                    mvr_object = pymvr.Symbol(uuid=uid, symdef=instance)
                else:
                    meshes = geometries.geometry3d
                    scene_object, mvr_object = export_geometry(item, child_list, file_list)
                meshes.append(mvr_object)
                geometries.to_xml(parent=scene_object)
                child_list.append(scene_object)

        elif item.name == "AUXData":
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
                            filepath = get_filepath(geo_name, asset_path)
                            if filepath and file_path is None:
                                file_path = filepath
                            file_list.extend(get_material_images(ob.active_material, folder_path))
                    if file_path is None:
                        geo_name = '.'.join((ob.name, "3ds"))
                        file_path = os.path.join(folder_path, geo_name)
                        export_3ds(context, file_path, geo.all_objects, SELECT, CONVERSE, geo.name)
                    print("exporting Geometry3D... %s" % geo_name)
                    mvr_object = pymvr.Geometry3D(file_name=geo_name).to_xml()
                    file_list.append((file_path, geo_name))
                    symlist.append(mvr_object)
                auxdata.symdefs.append(symdef)

        elif item.children or item.objects:
            geometries = pymvr.Geometries()
            if FIXTURES and is_gdtf:
                export_fixture(item, items.name, child_list, file_list)
            elif item.objects and not item.children and not is_gdtf:
                print("exporting Layer... %s" % item.name)
                layer = pymvr.Layer(name=item.name).to_xml(parent=layers)
                child_list = pymvr.ChildList().to_xml(parent=layer)
                root_objects = [ob for ob in item.objects if ob.parent is None]
                child_list, file_list = create_scene_object(root_objects, child_list, file_list)
            elif item.children or item.objects:
                print("exporting Layer... %s" % item.name)
                layer = pymvr.Layer(name=item.name).to_xml(parent=layers)
                child_list = pymvr.ChildList().to_xml(parent=layer)
                if item.objects:
                    child_list, file_list = create_scene_object(group, child_list, file_list, True)
                for group in item.children:
                    if FIXTURES and group.get("Company"):
                        export_fixture(group, item.name, child_list, file_list)
                    elif group.objects and not group.children and not group.get("Company"):
                        group_list, file_list = create_scene_object(group, group_list, file_list, True)
                    elif group.children or group.objects:
                        if group.objects:
                            group_list, file_list = create_scene_object(group, group_list, file_list)
                        if group.children:
                            print("exporting GroupObject... %s" % group.name)
                            group_object = pymvr.GroupObject(name=group.name).to_xml(parent=layer)
                            group_list = pymvr.ChildList().to_xml(parent=group_object)
                            group_models = pymvr.Geometries()
                            for child in group.children:
                                if FIXTURES and child.get("Company"):
                                    export_fixture(group, group.name, group_list, file_list)
                                elif child.objects and not child.children and not child.get("Company"):
                                    obj_list, file_list = create_scene_object(child, group_list, file_list)
                                elif child.children or child.objects:
                                    if child.objects:
                                        obj_list, file_list = create_scene_object(child, group_list, file_list)
                                    for col in child.children:
                                        if FIXTURES and col.get("Company"):
                                            export_fixture(collection, collection.name, object_list, file_list)
                                        elif (col.children or col.objects) and not is_gdtf:
                                            models = pymvr.Geometries()
                                            if col.objects:
                                                scene_object, mvr_object = export_geometry(col, col.name, file_list)
                                                models.geometry3d.append(mvr_object)
                                                models.to_xml(parent=scene_object)
                                                object_list.append(scene_object)
                                                models.geometry3d.clear()
                                                models.symbol.clear()
                                            if col.children:
                                                for cl in col.children:
                                                    if FIXTURES and col.get("Company"):
                                                        export_fixture(collection, collection.name, group_list, file_list)
                                                    elif not col.get("Company") and cl.objects:
                                                        scene_object, mvr_object = export_geometry(cl, col.name, file_list)
                                                        models.geometry3d.append(mvr_object)
                                                        geometries.to_xml(parent=scene_object)
                                                        collect_list.append(scene_object)
                                                        models.geometry3d.clear()
                                                        models.symbol.clear()

    auxdata.to_xml(parent=scene)
    mvr.files_list = list(set(file_list))
    mvr.write_mvr(filename)
    file_size = Path(filename).stat().st_size
    geometries.geometry3d.clear()
    auxdata.symdefs.clear()

    return scene, file_list


def save_mvr(context, items, filename, fixturepath="", SELECT=False, FIXTURES=True, TARGETS=True, CONVERSE=mathutils.Matrix()):

    start_time = time.time()
    current_path = os.path.dirname(os.path.realpath(__file__))
    asset_path = os.path.join(current_path, "assets", "mvr")
    folder_path = os.path.join(asset_path, Path(filename).stem)
    Path(folder_path).mkdir(parents=True, exist_ok=True)

    try:
        scene, file_list = export_mvr(context, items, filename, fixturepath, folder_path,
                                      asset_path,SELECT, FIXTURES, TARGETS, CONVERSE)

    except Exception as exc:
        print(exc)

    if os.path.isdir(folder_path):
        [fl.unlink() for fl in Path(folder_path).iterdir() if fl.is_file()]
        Path(folder_path).rmdir()

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

    save_mvr(context, items, filepath, fixture_path, SELECT=use_selection,
             FIXTURES=use_fixtures, TARGETS=use_targets, CONVERSE=global_matrix)

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
