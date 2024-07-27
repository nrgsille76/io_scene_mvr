# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Import is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import time
import json
import uuid
import pymvr
import random
import zipfile
import mathutils
from pathlib import Path
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from io_scene_3ds.import_3ds import load_3ds
from .import_gdtf import fixture_build, load_gdtf

auxData = {}
objectData = {}


class FixtureGroup:

    __slots__ = "name", "uuid"

    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid


def create_unique_fixture_name(name, fixtures):
    while True:
        if name in fixtures:
            rand = random.randint(1000, 9999)
            name = f"{name}-{rand}"
        else:
            return name


def extract_mvr_textures(mvr_scene, folder_path):
    for name in mvr_scene._package.namelist():
        if name.endswith('.png') or name.endswith('.jpg'):
            mvr_scene._package.extract(name, folder_path)


def extract_mvr_object(mvr_scene, extracted, folder_path, file):
    if f"{file}" in mvr_scene._package.namelist():
        if file not in extracted.keys():
            mvr_scene._package.extract(file, folder_path)
            extracted[file] = 0
        else:
            extracted[file] += 1


def create_mvr_props(mvr_obj, cls, name="", uid=False, ref=None):
    mvr_obj['MVR Class'] = cls
    if len(name):
        mvr_obj['MVR Name'] = name
    if ref:
        mvr_obj['Reference'] = ref
    if uid:
        mvr_obj['UUID'] = uid


def create_transform_property(obj):
    mtx_copy = obj.matrix_world.copy()
    translate = mtx_copy.to_translation()
    rotate = mtx_copy.transposed().to_3x3()
    trans_mtx = rotate[0][:]+rotate[1][:]+rotate[2][:]+translate[:]
    obj['Transform'] = trans_mtx


def get_matrix(obj, mtx):
    mtx_data = obj.matrix.matrix
    obj_mtx = mathutils.Matrix(mtx_data).transposed()
    check_float = any(isinstance(i, float) for i in set().union(sum(mtx_data, [])))
    global_matrix = obj_mtx @ mtx if check_float else mtx
    return global_matrix


def trans_matrix(trans_mtx):
    trans = list(trans_mtx)
    matrix = mathutils.Matrix((trans[:3]+[0], trans[3:6]+[0], trans[6:9]+[0], trans[9:]+[1])).transposed()
    return matrix


def check_existing(node, collection):
    cls_name = node.__class__.__name__
    existing = any(col.get('UUID') == node.uuid for col in collection.children)
    if existing:
        for collect in collection.children:
            if collect.get('MVR Class') == cls_name:
                for obj in collect.all_objects:
                    transform = obj.get('Transform')
                    if transform is not None:
                        obj.matrix_world = trans_matrix(transform)
    return existing


def add_mvr_fixture(context, mvr_scene, fixture, mscale, folder_path, fixture_idx,
                    layer_idx, focus_point, extracted, group_collect, fixture_group=None):

    """Add fixture to the scene"""
    fixture_file = os.path.join(folder_path, fixture.gdtf_spec)
    existing_fixture = os.path.isfile(fixture_file)

    if f"{fixture.gdtf_spec}" in mvr_scene._package.namelist():
        if fixture.gdtf_spec not in extracted.keys():
            mvr_scene._package.extract(fixture.gdtf_spec, folder_path)
            extracted[fixture.gdtf_spec] = 0
        else:
            extracted[fixture.gdtf_spec] += 1

    unique_name = f"{fixture.name} {layer_idx}-{fixture_idx}"
    if existing_fixture is not None:
        fixture_build(context, fixture_file, mscale, unique_name, focus_point, group_collect, fixture)
    else:
        unique_name = create_unique_fixture_name(unique_name, folder_path)
        load_gdtf(context, fixture_file, mscale, unique_name, focus_point, group_collect, fixture)


def get_child_list(context, mscale, mvr_scene, child_list, layer_index,
                   folder_path, extracted, layer_collection, fixture_group=None):

    viewlayer = context.view_layer
    viewport = viewlayer.layer_collection.children.get(layer_collection.name)
    if viewport is not None:
        viewlayer.active_layer_collection = viewport

    for truss_idx, truss_obj in enumerate(child_list.trusses):
        existing = check_existing(truss_obj, layer_collection)

        if fixture_group is None:
            group_name = truss_obj.name or "Truss"
            group_name =  '%s %d' % (group_name, truss_idx) if scene_idx >= 1 else group_name
            fixture_group = FixtureGroup(group_name, truss_obj.uuid)

        if not existing:
            process_mvr_object(context, mvr_scene, truss_obj, truss_idx,
                               mscale, folder_path, extracted, layer_collection)

        if hasattr(truss_obj, "child_list") and truss_obj.child_list:
            get_child_list(context, mscale, mvr_scene, truss_obj.child_list, truss_idx,
                           folder_path, extracted, layer_collection, fixture_group)

    for scene_idx, scene_obj in enumerate(child_list.scene_objects):
        existing = check_existing(scene_obj, layer_collection)

        if not existing:
            process_mvr_object(context, mvr_scene, scene_obj, scene_idx,
                               mscale, folder_path, extracted, layer_collection)

        if hasattr(scene_obj, "child_list") and scene_obj.child_list:
            get_child_list(context, mscale, mvr_scene, scene_obj.child_list,
                           scene_idx, folder_path, extracted, layer_collection)

    for fixture_idx, fixture in enumerate(child_list.fixtures):
        focus_point = mscale
        if fixture.focus is not None:
            focus_points = [fp for fp in child_list.focus_points if fp.uuid == fixture.focus]
            if len(focus_points):
                focus_point = get_matrix(focus_points[0], mscale)

        add_mvr_fixture(context, mvr_scene, fixture, mscale, folder_path, fixture_idx,
                        layer_index, focus_point, extracted, layer_collection, fixture_group)

        if hasattr(fixture, "child_list") and fixture.child_list:
            get_child_list(context, mscale, mvr_scene, fixture.child_list, fixture_idx,
                           folder_path, extracted, layer_collection, fixture_group)

    for group_idx, group in enumerate(child_list.group_objects):
        if hasattr(group, "child_list") and group.child_list:
            layergroup_idx = f"{layer_index}-{group_idx}"
            group_name = group.name or "Group"
            group_name =  '%s %d' % (group_name, group_idx) if group_idx >= 1 else group_name
            fixture_group = FixtureGroup(group_name, group.uuid)
            get_child_list(context, mscale, mvr_scene, group.child_list, layergroup_idx,
                           folder_path, extracted, layer_collection, fixture_group)

    for obj in viewlayer.active_layer_collection.collection.all_objects:
        obj.select_set(True)


def process_mvr_object(context, mvr_scene, mvr_object, mvr_idx, mscale, folder_path, extracted, group_collect):

    uid = mvr_object.uuid
    name = mvr_object.name
    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    scene_collect = context.scene.collection
    class_name = mvr_object.__class__.__name__
    layer_collect = viewlayer.layer_collection
    symdef_id = isinstance(mvr_object, pymvr.Symdef)
    active_layer = viewlayer.active_layer_collection
    print("creating %s... %s" % (class_name, name))

    def add_mvr_object(node, mtx, collect, folder=None, file=""):
        imported_objects = []
        item_name = Path(file).name
        mesh_name = Path(file).stem
        mesh_data = bpy.data.meshes
        node_type = node.__class__.__name__
        gltf = file.split('.')[-1] == 'glb'
        scale_factor = 0.001 if file.split('.')[-1] == '3ds' else 1.0
        mesh_exist = next((msh for msh in mesh_data if msh.name == mesh_name), False)
        exist = any(ob.data and ob.data.name == mesh_name for ob in collect.objects)
        world_matrix = mtx @ mathutils.Matrix.Scale(scale_factor, 4)
        print("adding %s... %s" % (node_type, mesh_name))

        if not exist:
            if mesh_exist:
                mesh_id = mesh_exist.get('MVR Name', mesh_name)
                new_object = object_data.new(mesh_id, mesh_exist)
                imported_objects.append(new_object)
            else:
                file_name = os.path.join(folder, file)
                if os.path.isfile(file_name):
                    if gltf:
                        bpy.ops.import_scene.gltf(filepath=file_name)
                    else:
                        load_3ds(file_name, context, KEYFRAME=False, APPLY_MATRIX=False)
                    imported_objects.extend(list(viewlayer.objects.selected))
            for ob in imported_objects:
                ob.rotation_mode = 'XYZ'
                obname = ob.name.split('.')[0]
                create_mvr_props(ob, class_name, obname, mesh_name, uid)
                if ob.data:
                    ob.data.name = mesh_name
                    create_mvr_props(ob.data, node_type, obname, uid, item_name) 
                if len(ob.users_collection) and ob.name in ob.users_collection[0].objects:
                    ob.users_collection[0].objects.unlink(ob)
                elif ob.name in layer_collect.collection.objects:
                    active_layer.collection.objects.unlink(ob)
                if ob.data:
                    ob.matrix_world = world_matrix @ ob.matrix_world.copy() if gltf else world_matrix
                else:
                    ob.empty_display_size = 0.001
                create_transform_property(ob)
                if ob.name not in collect.objects:
                    collect.objects.link(ob)
            objectData.setdefault(uid, collect)
            imported_objects.clear()
            viewlayer.update()
        return collect

    file = ""
    symbols = []
    geometrys = []
    active_collect = None
    context_matrix = mscale
    collection = group_collect

    if isinstance(mvr_object, pymvr.Symbol):
        symbols.append(mvr_object)
    elif isinstance(mvr_object, pymvr.Geometry3D):
        geometrys.append(mvr_object)
    elif not symdef_id and mvr_object.geometries:
        symbols += mvr_object.geometries.symbol
        geometrys += mvr_object.geometries.geometry3d
    else:
        symbols += mvr_object.symbol
        geometrys += mvr_object.geometry3d

    if symdef_id:
        create_mvr_props(group_collect, class_name, name, uid)
        active_collect = next((col for col in data_collect if col.get('Reference') == uid), False)
        if not active_collect:
            active_collect = data_collect.get(uid)
            if active_collect is None:
                active_collect = data_collect.new(uid)
        if active_collect.get('MVR Class') is None:
            create_mvr_props(active_collect, class_name, uid)
        active_collect.hide_render = True
    elif (len(geometrys) + len(symbols)) > 1:
        if mvr_object.name is not None and len(mvr_object.name):
            obj_name = '%s - %s %d' % (class_name, mvr_object.name, mvr_idx)
        else:
            obj_name = '%s %d' % (class_name, mvr_idx) if mvr_idx >= 1 else class_name
        print("creating extra collection", obj_name)
        active_collect = bpy.data.collections.new(obj_name)
        create_mvr_props(active_collect, class_name, name, uid)
        group_collect.children.link(active_collect)
        collection = active_collect

    if active_collect is None:
        active_collect = next((col for col in data_collect if col.get('UUID') == uid), False)
        if not active_collect and not len(symbols):
            reference = collection.get('UUID')
            active_collect = data_collect.new(name)
            create_mvr_props(active_collect, class_name, name, uid, reference)

    for geometry in geometrys:
        file = geometry.file_name
        obj_mtx = get_matrix(geometry, mscale)
        extract_mvr_object(mvr_scene, extracted, folder_path, file)
        object_collect = add_mvr_object(geometry, obj_mtx, active_collect, folder_path, file)
        if object_collect and object_collect.name not in collection.children and collection != object_collect:
            collection.children.link(object_collect)
               
    for idx, symbol in enumerate(symbols):
        symbol_type = symbol.__class__.__name__
        symbol_mtx = get_matrix(symbol, context_matrix)
        if not symdef_id:
            symbol_mtx = get_matrix(mvr_object, symbol_mtx)
        symbol_collect = data_collect.get(symbol.symdef)
        if symbol_collect:
            if not len(name):
                name = '%s %d' % (class_name, idx) if idx >= 1 else class_name
            symbol_object = object_data.new(name, None)
            collection.objects.link(symbol_object)
            symbol_object.matrix_world = symbol_mtx
            create_transform_property(symbol_object)
            symbol_object.empty_display_size = 0.001
            symbol_object.empty_display_type = 'ARROWS'
            symbol_object.instance_type = 'COLLECTION'
            symbol_object.instance_collection = symbol_collect
            create_mvr_props(symbol_object, symbol_type, name, uid, symbol.uuid)
            create_mvr_props(symbol_collect, symbol_type, name, symbol.uuid, symbol.symdef)


def transform_objects(layers, mscale):

    def transform_matrix(mvr):
        obj_collect = objectData.get(mvr.uuid)
        if obj_collect is not None:
            global_mtx = get_matrix(mvr, mscale)
            for obj in obj_collect.objects:
                obj.matrix_world = global_mtx @ obj.matrix_world.copy()
                create_transform_property(obj)

    def collect_objects(childlist):
        for truss in childlist.trusses:
            transform_matrix(truss)
        for sceneobject in childlist.scene_objects:
            transform_matrix(sceneobject)
        for fixture in childlist.fixtures:
            transform_matrix(fixture)
        for group in childlist.group_objects:
            if hasattr(group, "child_list") and group.child_list:
                collect_objects(group.child_list)

    for layer in layers:
        if hasattr(layer, "child_list") and layer.child_list:
            collect_objects(layer.child_list)

                   
def load_mvr(context, filename, mscale=mathutils.Matrix(), obtypes=None, search=False, target=False):

    extracted = {}
    imported_layers = []
    start_time = time.time()
    viewlayer = context.view_layer
    data_collect = bpy.data.collections
    scene_collect = context.scene.collection
    view_collect = viewlayer.layer_collection
    layer_collect = view_collect.collection
    active_layer = viewlayer.active_layer_collection
    mvr_scene = pymvr.GeneralSceneDescription(filename)
    current_path = os.path.dirname(os.path.realpath(__file__))
    folder_path = os.path.join(current_path, "extracted_files", Path(filename).stem)
    aux_dir = scene_collect.children.get('AUXData')
    extract_mvr_textures(mvr_scene, folder_path)
    mvr_layer = mvr_scene.layers
    auxdata = mvr_scene.aux_data
    classes = auxdata.classes
    symdefs = auxdata.symdefs

    for aux_idx, symdef in enumerate(symdefs):
        if aux_dir and symdef.name in aux_dir.children:
            aux_collection = aux_dir.children.get(symdef.name)
        elif symdef.name in data_collect:
            aux_collection = data_collect.get(symdef.name)
        else:
            aux_collection = data_collect.new(symdef.name)

        auxData.setdefault(symdef.uuid, aux_collection)
        process_mvr_object(context, mvr_scene, symdef, aux_idx,
                           mscale, folder_path, extracted, aux_collection)

        if hasattr(symdef, "child_list") and symdef.child_list:
            get_child_list(context, mscale, mvr_scene, symdef.child_list,
                           aux_idx, folder_path, extracted, aux_collection)

    for layer_idx, layer in enumerate(mvr_scene.layers):
        layer_class = layer.__class__.__name__
        layer_collection = next((col for col in data_collect if col.get('UUID') == layer.uuid), False)
        if not layer_collection:
            layer_collection = data_collect.new(layer.name)
            create_mvr_props(layer_collection, layer_class, layer.name, layer.uuid)
            layer_collect.children.link(layer_collection)

        group_name = layer.name or "Layer"
        fixture_group = FixtureGroup(group_name, layer.uuid)
        get_child_list(context, mscale, mvr_scene, layer.child_list, layer_idx,
                           folder_path, extracted, layer_collection, fixture_group)

        if len(layer_collection.all_objects) == 0 and layer_collection.name in layer_collect.children:
            layer_collect.children.unlink(layer_collection)

    transform_objects(mvr_scene.layers, mscale)

    if auxData.items():
        aux_type = auxdata.__class__.__name__
        if 'AUXData' in data_collect:
            aux_directory = data_collect.get('AUXData')
        else:
            aux_directory = data_collect.new('AUXData')
            create_mvr_props(aux_directory, aux_type)
            layer_collect.children.link(aux_directory)
        for uid, auxcollect in auxData.items():
            if auxcollect.name not in aux_directory.children:
                aux_directory.children.link(auxcollect)
            sym_collect = data_collect.get(uid)
            if sym_collect:
                sym_name = sym_collect.get('MVR Name')
                if sym_collect.name in layer_collect.children:
                    layer_collect.children.unlink(sym_collect)
                elif sym_collect.name not in auxcollect.children:
                    auxcollect.children.link(sym_collect)
                    if sym_name in (None, 'None'):
                        sym_name = 'None Layer'
                sym_collect.name = sym_name

    for laycollect in layer_collect.children:
        if laycollect.get('MVR Class') is not None:
            imported_layers.append(laycollect)
            for cidx, collect in enumerate(laycollect.children):
                for col in collect.children:
                    col_name = col.get('MVR Name')
                    check_name = col.name[-3:].isdigit() and col.name[-4] == '.'
                    if check_name and col_name in data_collect:
                        clean_name = col.name.split('.')[0]
                        col.name = '%s %d' % (clean_name, cidx)

    for idx, collect in enumerate(imported_layers):
        for obid, obj in enumerate(collect.all_objects):
            obj_name = obj.name.split('.')[0]
            if obj.is_instancer:
                transform = obj.get('Transform')
                if transform:
                    obj.matrix_world = trans_matrix(transform)
                insta_name = '%s %d' % (obj_name, idx) if idx >= 1 else obj_name
                obj.name = '%s_%d' % (insta_name.split('_')[0], obid)
            elif obj.name[-3:].isdigit() and obj.name[-4] == '.':
                obj.name = '%s %d' % (obj_name, obid)

    for view in view_collect.children:
        if view.name == 'AUXData':
            for childs in view.children:
                for collect in childs.children:
                    collect.hide_viewport = True

    viewlayer.update()
    imported_layers.clear()
    #[fl.unlink() for fl in Path(folder_path).iterdir() if fl.is_file()] 
    print("MVR scene loaded in %.4f sec." % (time.time() - start_time))


def load(operator, context, files=None, directory="", filepath="", scale_objects=1.0, use_collection=False,
         use_image_search=True, object_filter=None, use_target=False, global_matrix=None):

    auxData.clear()
    objectData.clear()

    context.window.cursor_set('WAIT')
    mscale = mathutils.Matrix.Scale(scale_objects, 4)
    if global_matrix is not None:
        mscale = global_matrix @ mscale

    if not object_filter:
        object_filter = {'MATERIAL', 'UV', 'EMPTY'}

    default_layer = context.view_layer.active_layer_collection.collection
    for fl in files:
        if use_collection:
            collection = bpy.data.collections.new(Path(fl.name).stem)
            context.scene.collection.children.link(collection)
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collection.name]
        load_mvr(context, os.path.join(directory, fl.name), mscale, obtypes=object_filter, search=use_image_search, target=use_target)

    auxData.clear()
    objectData.clear()

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
