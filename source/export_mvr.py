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
from py_mvr.value import Matrix
from bpy_extras import node_shader_utils
from io_scene_3ds.export_3ds import save_3ds


def get_filepath(file, assets):
    filepath = None

    for root, dirs, files in os.walk(assets):
        if file in files:
            filepath = os.path.join(root, file)

    return filepath


def get_material_images(material, path):

    images = []
    if material:
        mtype = 'MIX', 'MIX_RGB'
        links = material.node_tree.links
        mtex = [lk.from_node for lk in links if lk.from_node.type == 'TEX_IMAGE' and lk.to_node.type in mtype]
        bsdf = node_shader_utils.PrincipledBSDFWrapper(material)

        def get_image(image):
            if image:
                img_name = Path(image.filepath).name
                file_path = os.path.join(path, img_name)
                img = image.copy()
                img.save(filepath=file_path)
                images.append((file_path, img_name))

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

    return images


def get_trans_matrix(mtx, obj=None):
    if obj:
        mtx_copy = obj.matrix_world.copy()
        mtx = mtx_copy @ mtx
    translate = mtx.to_translation()
    rotate = mtx.transposed().to_3x3()
    trans_mtx = Matrix(list((rotate[0][:], rotate[1][:], rotate[2][:], translate[:])))
    return trans_mtx


def get_fixture(fixture, assets, matrix):
    uid = fixture.get("UUID")
    focus_point = None
    fix_name = fixture.get("Fixture Name")
    specs = '@'.join((fixture.get("Company"), fix_name))
    base = next((ob for ob in fixture.objects if ob.get("Use Root")), fixture.objects[0])
    target = next((ob for ob in fixture.objects if ob.get("Geometry Type") == "Target"), None)
    fix_id = fixture.get("Fixture ID")
    fix_mode = base.get("Fixture Mode")
    transmtx = get_trans_matrix(matrix, base)
    file_path = get_filepath(specs, assets)

    if target:
        target_uid = target.get("UUID")
        target_name = target.get("Fixture Name")
        target_mtx = get_trans_matrix(matrix, target)
        focus_point = pymvr.FocusPoint(uuid=target_uid, name=target_name, matrix=target_mtx).to_xml()
        fix_object = pymvr.Fixture(name=fix_name, uuid=uid, gdtf_spec=specs, gdtf_mode=fix_mode, matrix=transmtx,
                                   fixture_id=str(fix_id), fixture_id_numeric=fix_id, focus=target_uid).to_xml()
    else:
        fix_object = pymvr.Fixture(name=fix_name, uuid=uid, gdtf_spec=specs, gdtf_mode=fix_mode,
                                   matrix=transmtx, fixture_id=str(fix_id), fixture_id_numeric=fix_id).to_xml()

    return fix_object, file_path, focus_point


def export_3ds(context, path, objects, selection, matrix, collection=None):
    save_3ds(context, path, collection, objects, 1000, matrix, selection)


def export_mvr(context, obj, objects, assets, folder, selection, matrix):

    def get_3ds(ob, name):
        file_path = os.path.join(folder, name)
        export_3ds(context, file_path, [ob], selection, matrix)

    mvr_object = None
    if obj.active_material:
        objects.extend(get_material_images(obj.active_material, folder))
    if obj.get("MVR Class") in {"Symdef", "SceneObject"}:
        geometry = obj.data.get("Reference")
        file_path = get_filepath(geometry, assets)
        if file_path is None:
            geometry = '.'.join((obj.name, "3ds"))
            file_path = os.path.join(folder, geometry)
            get_3ds(obj, geometry)
        if (file_path, geometry) not in objects:
            mvr_object = pymvr.Geometry3D(file_name=geometry)
            objects.append((file_path, geometry))     
    else:
        geometry = '.'.join((obj.name, "3ds"))
        get_3ds(obj, geometry)
        mvr_object = pymvr.Geometry3D(file_name=geometry)
        file_path = os.path.join(folder, geometry)
        objects.append((file_path, geometry))

    return objects, mvr_object
             

                   
def save_mvr(operator, context, items, filename, selection=False, matrix=mathutils.Matrix()):

    objects_list = []
    start_time = time.time()

    current_path = os.path.dirname(os.path.realpath(__file__))
    assets_path = os.path.join(current_path, "assets", "mvr")
    folder_path = os.path.join(assets_path, Path(filename).stem)
    Path(folder_path).mkdir(parents=True, exist_ok=True)

    try:
        mvr = pymvr.GeneralSceneDescriptionWriter()
        user = pymvr.UserData().to_xml(parent=mvr.xml_root)
        scene = pymvr.SceneElement().to_xml(parent=mvr.xml_root)
        layers = pymvr.LayersElement().to_xml(parent=scene)
        pymvr.Data().to_xml(parent=user)
        auxdata = pymvr.AUXData()
        auxdata.symdefs.clear()
        for item in items.children:
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
                        geometries.geometry3d.clear()
                        geometries.symbol.clear()
                        print("exporting Symbol... %s" % symbol_name)
                        instance = ob.instance_collection.get("Reference") if ob.instance_collection else ob.get("Reference")
                        mvr_object = pymvr.Symbol(uuid=uid, symdef=instance)
                        geometries.symbol.append(mvr_object)
                        geometries.to_xml(parent=scene_object)
                    else:
                        transmtx = get_trans_matrix(matrix, ob)
                        scene_object = pymvr.SceneObject(name=ob.name, matrix=transmtx).to_xml()
                        geometries = pymvr.Geometries()
                        geometries.geometry3d.clear()
                        geometries.symbol.clear()
                        print("exporting Geometry3D... %s.3ds" % ob.name)
                        objects_list, mvr_object = export_mvr(context, ob, objects_list, assets_path, folder_path, selection, matrix)
                        geometries.geometry3d.append(mvr_object)
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
                                filepath = get_filepath(geo_name, assets_path)
                                if filepath and file_path is None:
                                    file_path = filepath
                                objects_list.extend(get_material_images(ob.active_material, folder_path))
                        if file_path is None:
                            geo_name = '.'.join((ob.name, "3ds"))
                            file_path = os.path.join(folder_path, geo_name)
                            export_3ds(context, file_path, geo.all_objects, selection, matrix, geo.name)
                        print("exporting Geometry3D... %s" % geo_name)
                        mvr_object = pymvr.Geometry3D(file_name=geo_name).to_xml()
                        objects_list.append((file_path, geo_name))
                        symlist.append(mvr_object)
                    auxdata.symdefs.append(symdef)

            elif any(ob.type in {'MESH', 'EMPTY'} for ob in item.objects):
                print("creating SceneObject... %s" % item.name)
                layer = pymvr.Layer(name=item.name).to_xml(parent=layers)
                child_list = pymvr.ChildList().to_xml(parent=layer)
                transmtx = get_trans_matrix(matrix, item.objects[0])
                scene_object = pymvr.SceneObject(name=item.name, matrix=transmtx).to_xml()
                geometries = pymvr.Geometries()
                geometries.geometry3d.clear()
                geometries.symbol.clear()
                geo_name = '.'.join((item.name, "3ds"))
                file_path = os.path.join(folder_path, geo_name)
                print("exporting Geometry3D... %s" % geo_name)
                export_3ds(context, file_path, item.all_objects, selection, matrix, item.name)
                mvr_object = pymvr.Geometry3D(file_name=geo_name)
                geometries.geometry3d.append(mvr_object)
                objects_list.append((file_path, geo_name))
                geometries.to_xml(parent=scene_object)

                for ob in item.objects:
                    if ob.type == 'MESH':
                        objects_list.extend(get_material_images(ob.active_material, folder_path))
                child_list.append(scene_object)

            for child in item.children:
                is_fixture = child.get("Company")
                if is_fixture:
                    print("exporting Fixture... %s" % child.name)
                    fix_object, file_path, focuspoint = get_fixture(child, assets_path, matrix)
                    if file_path:
                        objects_list.append((file_path, Path(file_path).name))
                    child_list.append(fix_object)
                    if focuspoint:
                        child_list.append(focuspoint)
                elif child.objects:
                    print("creating SceneObject... %s" % child.name)
                    if child.get("MVR Class") == "SceneObject":
                        uid = child.get("UUID")
                        child_obj = child.objects[0]
                        transform = child_obj.get("Transform")
                        scale_vec = child_obj.matrix_world.copy().to_scale()
                        if all(abs(vec) < 0.01 for vec in scale_vec):
                            trs = [1000 * vec for vec in transform[:9]]
                        else:
                            trs = transform[:9]
                        transmtx = Matrix(list((trs[:3], trs[3:6], trs[6:], transform[9:])))
                        scene_object = pymvr.SceneObject(name=child.name, uuid=uid, matrix=transmtx).to_xml()
                    else:
                        transmtx = get_trans_matrix(matrix, child.objects[0])
                        scene_object = pymvr.SceneObject(name=child.name, matrix=transmtx).to_xml()
                    geometries = pymvr.Geometries()
                    geometries.geometry3d.clear()
                    geometries.symbol.clear()

                    for ob in child.objects:
                        print("exporting Geometry3D... %s.3ds" % ob.name)
                        objects_list, mvr_object = export_mvr(context, ob, objects_list, assets_path, folder_path, selection, matrix)
                        if mvr_object is not None:
                            geometries.geometry3d.append(mvr_object)
                    geometries.to_xml(parent=scene_object)
                    child_list.append(scene_object)

        auxdata.to_xml(parent=scene)
        mvr.files_list = list(set(objects_list))
        mvr.write_mvr(filename)
        file_size = Path(filename).stat().st_size
        [fl.unlink() for fl in Path(folder_path).iterdir() if fl.is_file()]
        Path(folder_path).rmdir()

    except Exception as exc:
        print(exc)

    print("MVR scene exported in %.4f sec.\n" % (time.time() - start_time))


def save(operator, context, filepath="", collection="", use_selection=False, use_collection=False, global_matrix=None):

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

    save_mvr(operator, context, items, filepath, use_selection, global_matrix)
    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
