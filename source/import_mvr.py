# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Import is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import time
import mathutils
import py_mvr as pymvr
from pathlib import Path
from io_scene_3ds.import_3ds import load_3ds
from .import_gdtf import fixture_build, load_gdtf


auxData = {}
objectData = {}
objectMVR = {"SceneObject", "Truss"}
nodeMVR = objectMVR.add("GroupObject")


class FixtureGroup:
    """Class is representing a group of fixtures."""

    __slots__ = "name", "uuid"

    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid


def not_zero(num):
    zero = True
    if isinstance(num, int):
        zero = num >= 1

    return zero


def get_filepath(spec, assets):
    """Search for file and create filepath."""
    filepath = None
    if spec:
        file_line = spec.replace(' ','_')
        file_space = spec.replace('_',' ')
        for root, dirs, files in os.walk(assets):
            if spec in files:
                filepath = os.path.join(root, spec)
            elif file_line in files:
                filepath = os.path.join(root, file_line)
            elif file_space in files:
                filepath = os.path.join(root, file_space)
            else:
                for file in files:
                    if file.split('.')[0] == spec:
                        filepath = os.path.join(root, file)
                        break
    return filepath


def extract_mvr_textures(mvr_scene, folder_path):
    """Extract textures from zip file."""
    for name in mvr_scene._package.namelist():
        if name.endswith('.png') or name.endswith('.jpg'):
            mvr_scene._package.extract(name, folder_path)


def extract_mvr_object(mvr_scene, extracted, folder_path, file):
    """Extract meshes from zip file."""
    if f"{file}" in mvr_scene._package.namelist():
        if file not in extracted.keys():
            mvr_scene._package.extract(file, folder_path)
            extracted[file] = 0
        else:
            extracted[file] += 1


def check_for_digits(name):
    """Check for duplicated names."""
    check3Digits = name[-3:].isdigit() and name[-4] == '.'
    check4Digits = name[-4:].isdigit() and name[-5] == '.'
    check_digits = check3Digits or check4Digits

    return check_digits


def create_mvr_props(obj, mvr_cls, name="", uid=False, cls=None, ref=None, obc=None):
    """Create MVR object properties."""
    obj['MVR Class'] = mvr_cls
    if name and len(name):
        obj['MVR Name'] = name
    if cls:
        obj['Classing'] = cls
    if obc:
        obj['Object Class'] = obc
    if ref:
        obj['Reference'] = ref
    if uid:
        obj['UUID'] = uid


def create_transform_property(obj, collection=None, matrix=False):
    """Create a 4x3 matrix property."""
    prop = "Transform"
    if matrix:
        mtx = obj.matrix.matrix
        mtx_copy = mtx[0][:3] + mtx[1][:3] + mtx[2][:3] + mtx[3][:3]
        mtx_prop = [float(val) for val in mtx_copy]
    else:
        mtx_copy = obj.matrix_world.copy()
        mtx_pos = mtx_copy.to_translation()
        mtx_rot = mtx_copy.transposed().to_3x3()
        mtx_prop = mtx_rot[0][:] + mtx_rot[1][:] + mtx_rot[2][:] + mtx_pos[:]
        obj[prop] = mtx_prop
        obj.id_properties_ensure()
        mtx_property = obj.id_properties_ui(prop)
        mtx_property.update(default=mtx_prop)
    if collection is not None:
        collection[prop] = mtx_prop
        collection.id_properties_ensure()
        mtx_property = collection.id_properties_ui(prop)
        mtx_property.update(default=mtx_prop)


def get_matrix(obj, mtx):
    """Get matrix from MVR object."""
    mtx_data = obj.matrix.matrix
    obj_mtx = mathutils.Matrix(mtx_data).transposed()
    check_float = any(isinstance(i, float) for i in set().union(sum(mtx_data, [])))
    global_matrix = obj_mtx @ mtx if check_float else mtx
    return global_matrix


def trans_matrix(trans_mtx):
    """Transform matrix from 4x3 to 4x4."""
    mtx = list(trans_mtx)
    matrix = mathutils.Matrix((mtx[:3]+[0], mtx[3:6]+[0], mtx[6:9]+[0], mtx[9:]+[1])).transposed()
    return matrix


def move_instance(obj):
    """Move instance if transform."""
    transform = obj.get('Transform')
    if transform:
        obj.matrix_world = trans_matrix(transform)


def merge_material(obj):
    """Merge doubled materials."""
    if obj and obj.type == 'MESH':
        mtl_index = []
        materials = []
        cls = obj.data.get("MVR Class")
        mtl_data = bpy.data.materials
        mtl_slots = obj.material_slots
        for midx, material in enumerate(mtl_slots):
            if check_for_digits(material.name):
                mtl_name = material.name.split('.')[0]
                if mtl_name in mtl_data:
                    mtl_index.append(midx)
                    materials.append(mtl_name)
        for idx, mat in enumerate(materials):
            mtl_idx = mtl_index[idx]
            mtl = mtl_data.get(mat)
            if mtl and mtl.get("MVR Class") == cls:
                mtl_slots[mtl_idx].material = mtl
        abandoned = [mat for mat in mtl_data if not mat.users]
        for mdata in abandoned:
            mtl_data.remove(mdata)


def check_existing(node, collection):
    """Check for already existing objects."""
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


def create_index_tag(idx, grp=0, msh=False):
    """Create a ID tag."""
    if not msh and not_zero(grp):
        index_tag = f"{grp}-{idx}"
    elif msh and not_zero(grp):
        index_tag = f"{grp}_{idx}"
    elif not_zero(idx) and grp == 0:
        index_tag = str(idx)
    elif not_zero(grp) and idx == 0:
        index_tag = str(grp)
    else:
        index_tag = ""

    return index_tag


def get_mvr_name(node, index=0, layer=None):
    """Get a proper MVR name."""
    name = node.name
    cls_name = node.__class__.__name__
    is_layer = layer is not None and layer >= 1
    idx_value = int(index[-1]) if isinstance(index, str) else int(index)
    if is_layer and index is not None:
        if idx_value >= 1 and cls_name == "Object":
            index = f"{layer}_{index}"
        elif idx_value >= 1:
            index = f"{layer}-{index}"
        else:
            index = layer
    layer_id = f"L{index}"
    if is_layer:
        layer_id = f"L{layer}-{index}" if idx_value >= 1 else f"L{layer}"
    id_name = name.split('.')[0] if name else cls_name
    if cls_name == "Layer":
        id_name = '%s %s' % (layer_id, id_name)
    elif is_layer:
        id_name = f"{id_name} {layer}-{index}"
    else:
        id_name = f"{id_name} {index}" if idx_value >= 1 else id_name

    return id_name, cls_name


def get_clean_name(item, idx, lyr=None):
    """Get a clean indexed object name."""
    if item is None:
        return
    mvr_cls = item.get('MVR Class')
    mvr_idx = item.get('MVR Index')
    item_cls = item.__class__.__name__
    item_name = item.name.split('.')[0]
    has_number = item_name[-1].isdigit()
    layer_name = f"{item_name} {lyr}" if not has_number and lyr is not None and lyr >= 1 else item_name
    if check_for_digits(item.name):
        if lyr is not None and item_cls == "Collection":
            item.name = f"{layer_name}-{idx}" if idx >= 1 else layer_name
        elif lyr is not None and item_cls == "Object":
            item.name = f"{layer_name}_{idx}" if idx >= 1 else layer_name
        else:
            item.name = f"{layer_name} {idx}"


def add_mvr_fixture(context, mvr_scene, fixture, mscale, folder_path, fixture_idx,
                    layer_idx, extracted, group_collect, apply, TARGETS,
                    focus_points, fixture_path, fixture_group=None):

    """Add fixture to the scene."""
    fixture_pos = get_matrix(fixture, mscale)
    if fixture.gdtf_spec:
        fixture_file = os.path.join(folder_path, fixture.gdtf_spec)
    else:
        fixture_file = os.path.join(folder_path, "Custom@Fixture.gdtf")
    if fixture.fixture_id is not None and len(fixture.fixture_id):
        fixture_id = int(fixture.fixture_id)
    else:
        fixture_id = int(f"{layer_idx}{fixture_idx}")

    if f"{fixture.gdtf_spec}" in mvr_scene._package.namelist():
        if fixture.gdtf_spec not in extracted.keys():
            mvr_scene._package.extract(fixture.gdtf_spec, folder_path)
            extracted[fixture.gdtf_spec] = 0
        else:
            extracted[fixture.gdtf_spec] += 1
    elif fixture_path:
        fixture_file = get_filepath(fixture.gdtf_spec, fixture_path)
    existing_fixture = os.path.isfile(fixture_file)

    """Get Focuspoints."""
    focus_point = mscale
    if len(focus_points):
        focus_point = get_matrix(focus_points[0], mscale)

    if not existing_fixture:
        print(f"Info: {fixture.gdtf_spec} not available, using a generic PAR instead.")
        fixture.gdtf_spec = "NRGSille_Lighting@Simple_LED_PAR@rev2.gdtf"
        fixture_file = os.path.join(Path(folder_path).parent.parent, "gdtf", fixture.gdtf_spec)

    fixture_build(context, fixture_file, mscale, fixture.name, fixture_pos, focus_point,
                  fixture_id, fixture.color, group_collect, fixture, TARGETS)

    if len(focus_points) and focus_points[0].geometries:
        print("importing FocusPoint... %s" % fixture.name)
        target_collect = next((col for col in bpy.data.collections if
                               col.get("Target ID") == fixture.focus), None)
        if target_collect:
            group_collect = target_collect
        process_mvr_object(context, mvr_scene, focus_points[0], fixture_idx,
                           mscale, apply, folder_path, extracted, group_collect)


def get_child_list(context, mscale, mvr_scene, layer, layer_idx, folder_path, extracted,
                   apply, layer_collect, FIXTURES, TARGETS, fixturepath, fixture_group=None):
    """Get all MVR obects from the child lists."""

    child_list = layer.child_list
    viewlayer = context.view_layer
    data_collect = bpy.data.collections
    viewport = viewlayer.layer_collection.children.get(layer_collect.name)
    if viewport is not None:
        viewlayer.active_layer_collection = viewport

    for truss_idx, truss_obj in enumerate(child_list.trusses):
        existing = check_existing(truss_obj, layer_collect)

        if fixture_group is None:
            group_name = truss_obj.name or "Truss"
            group_name =  '%s %d' % (group_name, truss_idx) if truss_idx >= 1 else group_name
            fixture_group = FixtureGroup(group_name, truss_obj.uuid)

        if not existing:
            process_mvr_object(context, mvr_scene, truss_obj, truss_idx, mscale,
                               apply, folder_path, extracted, layer_collect)

        if hasattr(truss_obj, "child_list") and truss_obj.child_list:
            get_child_list(context, mscale, mvr_scene, truss_obj, truss_idx,
                           folder_path, extracted, apply, layer_collect,
                           FIXTURES, TARGETS, fixturepath, fixture_group)

    for scene_idx, scene_obj in enumerate(child_list.scene_objects):
        existing = check_existing(scene_obj, layer_collect)

        if not existing:
            process_mvr_object(context, mvr_scene, scene_obj, scene_idx, mscale,
                               apply, folder_path, extracted, layer_collect)

        if hasattr(scene_obj, "child_list") and scene_obj.child_list:
            get_child_list(context, mscale, mvr_scene, scene_obj, scene_idx, folder_path,
                           extracted, apply, layer_collect, FIXTURES, TARGETS, fixturepath)

    if FIXTURES:
        if fixture_group is None:
            lyr_name = layer.name or "Layer"
            fixture_group = FixtureGroup(lyr_name, layer.uuid)
        for fixture_idx, fixture in enumerate(child_list.fixtures):
            focus_points = []
            if fixture.focus is not None:
                focus_points.extend([fp for fp in child_list.focus_points if fp.uuid == fixture.focus])

            add_mvr_fixture(context, mvr_scene, fixture, mscale, folder_path,
                            fixture_idx, layer_idx, extracted, layer_collect,
                            apply, TARGETS, focus_points, fixturepath, fixture_group)

            if hasattr(fixture, "child_list") and fixture.child_list:
                get_child_list(context, mscale, mvr_scene, fixture, fixture_idx,
                               folder_path, extracted, apply, layer_collect,
                               FIXTURES, TARGETS, fixturepath, fixture_group)

    for group_idx, group in enumerate(child_list.group_objects):
        if hasattr(group, "child_list") and group.child_list:
            group_name, group_class = get_mvr_name(group)
            if layer_collect.get("MVR Class") == "Layer":
                layer_name = group.name or "Group"
            print("importing %s... %s" % (group_class, group_name))
            group_collection = data_collect.new(group_name)
            group_collection["MVR Index"] = group_idx
            layer_collect.children.link(group_collection)
            create_transform_property(group, group_collection, True)
            classing = group.classing if hasattr(group, "classing") else None
            create_mvr_props(group_collection, group_class, group_name,
                             group.uuid, classing, layer_collect.name)
            get_child_list(context, mscale, mvr_scene, group, group_idx, folder_path, extracted,
                           apply, group_collection, FIXTURES, TARGETS, fixturepath, fixture_group)

    for obj in viewlayer.active_layer_collection.collection.all_objects:
        obj.select_set(True)


def process_mvr_object(context, mvr_scene, mvr_object, mvr_idx, mscale, apply, folder_path, extracted, group_collect):
    """Processing MVR xml node objects."""

    uid = mvr_object.uuid
    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    scene_collect = context.scene.collection
    layer_collect = viewlayer.layer_collection
    name, class_name = get_mvr_name(mvr_object)
    active_layer = viewlayer.active_layer_collection
    symdef_id = isinstance(mvr_object, pymvr.Symdef)
    focus_id = isinstance(mvr_object, pymvr.FocusPoint)
    classing = mvr_object.classing if hasattr(mvr_object, "classing") else None
    print("creating %s... %s" % (class_name, name))

    def add_mvr_object(node, mtx, collect, folder=None, file=""):
        imported = []
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
                imported.append(new_object)
            else:
                file_name = os.path.join(folder, file)
                if os.path.isfile(file_name):
                    if gltf:
                        bpy.ops.import_scene.gltf(filepath=file_name)
                    else:
                        load_3ds(file_name, context, KEYFRAME=False, APPLY_MATRIX=apply)
                    imported.extend(list(viewlayer.objects.selected))
            imported_objects = list(filter(None, imported))
            for obj in imported_objects:
                obj.rotation_mode = 'XYZ'
                obname = obj.name.split('.')[0]
                create_mvr_props(obj, class_name, obname, uid, classing, mesh_name, node_type)
                if obj.parent is None:
                    if gltf or obj.type != 'MESH':
                        obj.matrix_local = world_matrix @ obj.matrix_world.copy()
                    else:
                        obj.matrix_local = world_matrix
                if obj.data is None:
                    obj.empty_display_size = 0.001
                else:
                    obj.data.name = mesh_name
                    create_mvr_props(obj.data, class_name, obname, uid, classing, item_name, node_type)
                    if obj.data.id_type == 'MESH':
                        for material in obj.data.materials:
                            create_mvr_props(material, class_name, obname, uid, classing, item_name)
                if len(obj.users_collection) and obj.name in obj.users_collection[0].objects:
                    obj.users_collection[0].objects.unlink(obj)
                elif obj.name in layer_collect.collection.objects:
                    active_layer.collection.objects.unlink(obj)
                create_transform_property(obj)
                if obj.name not in collect.objects:
                    collect.objects.link(obj)
            objectData.setdefault(uid, collect)
            viewlayer.update()
            imported.clear()
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
    elif class_name not in objectMVR:
        symbols += mvr_object.symbol
        geometrys += mvr_object.geometry3d

    if focus_id:
        active_collect = group_collect
    elif symdef_id:
        create_mvr_props(group_collect, class_name, name, uid)
        active_collect = next((col for col in data_collect if col.get('Reference') == uid), False)
        if not active_collect:
            active_collect = data_collect.get(uid)
            if active_collect is None:
                active_collect = data_collect.new(uid)
        if active_collect.get('MVR Class') is None:
            create_mvr_props(active_collect, class_name, uid)
        active_collect.hide_render = True
    elif not focus_id and (len(geometrys) + len(symbols)) > 1:
        obj_name, cls_name = get_mvr_name(mvr_object)
        print("creating extra collection", obj_name)
        active_collect = data_collect.new(obj_name)
        active_collect["MVR Index"] = mvr_idx
        create_mvr_props(active_collect, cls_name, name, uid, classing)
        group_collect.children.link(active_collect)
        collection = active_collect

    if active_collect is None:
        active_collect = next((col for col in data_collect if col.get('UUID') == uid), False)
        if not active_collect and not len(symbols):
            reference = collection.get('UUID')
            active_collect = data_collect.new(name)
            active_collect["MVR Index"] = mvr_idx
            create_mvr_props(active_collect, class_name, name, uid, classing, reference)

    for geometry in geometrys:
        file = geometry.file_name
        extract_mvr_object(mvr_scene, extracted, folder_path, file)
        obj_mtx = get_matrix(mvr_object, mscale) if focus_id else get_matrix(geometry, mscale)
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
            symbol_object = object_data.new(name, None)
            symbol_object["MVR Index"] = idx
            collection.objects.link(symbol_object)
            symbol_object.matrix_world = symbol_mtx
            symbol_object.empty_display_size = 0.001
            symbol_object.empty_display_type = 'ARROWS'
            symbol_object.instance_type = 'COLLECTION'
            symbol_object.instance_collection = symbol_collect
            create_transform_property(symbol_object, symbol_collect)
            create_mvr_props(symbol_object, class_name, name, uid, symbol.uuid, classing, symbol_type)
            create_mvr_props(symbol_collect, symbol_type, name, symbol.uuid, classing, symbol.symdef, "Symdef")

    if focus_id:
        target = next((ob for ob in group_collect.objects if
                       ob.get("Geometry Type") == "Target" and
                       ob.get("UUID") == mvr_object.uuid), None)
        if target:
            target_mtx = target.matrix_world.copy()
            for ob in group_collect.objects:
                if ob.parent is None and ob.get("MVR Class") == "FocusPoint" and ob.get("UUID") == mvr_object.uuid:
                    ob.parent = target
                    ob.matrix_parent_inverse = target.matrix_world.inverted()


def finalize_objects(layers, mscale):
    """Transform objects matrix."""

    def transform_matrix(mvr):
        obj_collect = objectData.get(mvr.uuid)
        if obj_collect is not None:
            global_mtx = get_matrix(mvr, mscale)
            for obj in obj_collect.objects:
                if obj.parent is None:
                    obj.matrix_world = global_mtx @ obj.matrix_local.copy()
                    create_transform_property(obj, obj_collect)
                else:
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


def create_tree_branch(layer, count):
    """Create MVR collection tree."""
    level = False
    if layer.get('MVR Index'):
        count = layer.get('MVR Index')

    def provide_geometries(objs, cid, prt=0):
        """Treat collection objects."""
        tag = create_index_tag(cid, prt, True)
        for obx, obj in enumerate(objs.objects):
            merge_material(obj)
            if obj and obj.is_instancer:
                move_instance(obj)
            ob_name = obj.name.split('.')[0]
            obj.name = '%s %s' % (ob_name, tag)
            if check_for_digits(obj.name):
                obj.name = '%s_%d %s' % (ob_name, obx, tag)
        
    def index_scene_object(collect, idx, cidx, org=None):
        """Index scene object collections."""
        tag = create_index_tag(idx, cidx)
        col_name = collect.name.split('.')[0]
        collect.name = f"{col_name} {tag}"
        if check_for_digits(collect.name):
            if org is None:
                collect.name = '%s %d %s' % (col_name, idx, tag)
            else:
                alt_tag = get_index_tag(collect, cidx, org)
                collect.name = '%s %s' % (col_name, alt_tag)
                if check_for_digits(collect.name):
                    collect.name = '%s %d %s' % (col_name, cidx, tag)
        provide_geometries(collect, idx, cidx)

    def index_group_object(group, gidx, lyr, level=False):
        """Index group collections."""
        group_name = group.name.split('.')[0]
        group.name = f"{group_name} {lyr}-{gidx}"
        provide_geometries(group, gidx, lyr)
        for idc, col in enumerate(group.children):
            if col.get("Fixture ID") is None:
                if col.get("MVR Class") == "SceneObject":
                    if level:
                        index_scene_object(col, idc, gidx, lyr)
                    else:
                        index_scene_object(col, idc, gidx)
                elif col.get("MVR Class") == "GroupObject":
                    index_group_object(col, idc, gidx, True)


    provide_geometries(layer, count)
    for cdx, collect in enumerate(layer.children):
        if collect.get("Fixture ID") is None:
            if collect.get("MVR Class") == "SceneObject":
                index_scene_object(collect, cdx, count)
            elif collect.get("MVR Class") == "GroupObject":
                index_group_object(collect, cdx, count)


def load_mvr(context, filename, fixturepath, mscale=mathutils.Matrix(), apply=False, FIXTURES=True, TARGETS=True):
    """Create MVR scene and import layers."""

    symdefs = []
    extracted = {}
    importLayer = None
    imported_layers = []
    start_time = time.time()
    viewlayer = context.view_layer
    layers_name = Path(filename).stem
    data_collect = bpy.data.collections
    scene_collect = context.scene.collection
    view_collect = viewlayer.layer_collection
    layer_collect = view_collect.collection
    active_layer = viewlayer.active_layer_collection
    aux_dir = scene_collect.children.get('AUXData')
    mvr_scene = pymvr.GeneralSceneDescription(filename)
    current_path = os.path.dirname(os.path.realpath(__file__))
    folder_path = os.path.join(current_path, "assets", "mvr", layers_name)
    mvr_layers = mvr_scene.layers if hasattr(mvr_scene, "layers") else []
    extract_mvr_textures(mvr_scene, folder_path)
    print("creating Scene... %s" % layers_name)

    if hasattr(mvr_scene, "aux_data"):
        auxdata = mvr_scene.aux_data
        print("importing AUXData...")
        classes = auxdata.classes if hasattr(auxdata, "classes") else []
        symdefs = auxdata.symdefs if hasattr(auxdata, "symdefs") else []

    for ob in viewlayer.objects.selected:
        ob.select_set(False)

    for aux_idx, symdef in enumerate(symdefs):
        if aux_dir and symdef.name in aux_dir.children:
            aux_collection = aux_dir.children.get(symdef.name)
        elif symdef.name in data_collect:
            aux_collection = data_collect.get(symdef.name)
        else:
            aux_collection = data_collect.new(symdef.name)

        auxData.setdefault(symdef.uuid, aux_collection)
        process_mvr_object(context, mvr_scene, symdef, aux_idx, mscale,
                           apply, folder_path, extracted, aux_collection)

        if hasattr(symdef, "child_list") and symdef.child_list:
            get_child_list(context, mscale, mvr_scene, symdef.child_list, aux_idx, folder_path,
                           extracted, apply, aux_collection, FIXTURES, TARGETS, fixturepath)

    print("importing Layers... %s" % scene_collect.name)
    for layer_idx, layer in enumerate(mvr_layers):
        layer_collection = next((col for col in data_collect if col.get('UUID') == layer.uuid), False)
        if not layer_collection:
            layer_name, layer_class = get_mvr_name(layer, layer_idx)
            layer_collection = data_collect.new(layer_name)
            layer_collection['MVR Index'] = layer_idx
            create_transform_property(layer, layer_collection, True)
            create_mvr_props(layer_collection, layer_class, layer.name, layer.uuid)
            print("importing %s... %s" % (layer_class, layer_name))
            layer_collect.children.link(layer_collection)
            imported_layers.append(layer_collection)

        get_child_list(context, mscale, mvr_scene, layer, layer_idx, folder_path,
                       extracted, apply, layer_collection, FIXTURES, TARGETS, fixturepath)

        if len(layer_collection.all_objects) == 0 and layer_collection.name in layer_collect.children:
            layer_collect.children.unlink(layer_collection)

    finalize_objects(mvr_layers, mscale)

    if auxData.items():
        aux_type = auxdata.__class__.__name__
        if 'AUXData' in data_collect:
            aux_directory = data_collect.get('AUXData')
        else:
            print("creating AUXData...")
            aux_directory = data_collect.new('AUXData')
            create_mvr_props(aux_directory, aux_type)
            layer_collect.children.link(aux_directory)
        for sid, (uid, auxcollect) in enumerate(auxData.items()):
            if auxcollect.name not in aux_directory.children:
                aux_directory.children.link(auxcollect)
            sym_collect = data_collect.get(uid)
            if sym_collect:
                if sym_collect.name in layer_collect.children:
                    layer_collect.children.unlink(sym_collect)
                elif sym_collect.name not in auxcollect.children:
                    auxcollect.children.link(sym_collect)
                get_clean_name(sym_collect, sid)
                sym_objects = list(filter(None, sym_collect.all_objects))
                for idx, obj in enumerate(sym_objects):
                    if check_for_digits(obj.name):
                        get_clean_name(obj, idx, sid)
                        merge_material(obj)

    for index, layer in enumerate(imported_layers):
        create_tree_branch(layer, index)

    if mvr_layers:
        for view in view_collect.children:
            if view.name == 'AUXData':
                for childs in view.children:
                    for collect in childs.children:
                        collect.hide_viewport = True

    viewlayer.update()
    imported_layers.clear()
    #[fl.unlink() for fl in Path(folder_path).iterdir() if fl.is_file()] 
    print("MVR scene loaded in %.4f sec.\n" % (time.time() - start_time))


def load(operator, context, files=[], directory="", filepath="", scale_objects=1.0, use_collection=False,
         use_apply_transform=False, use_fixtures=True, use_targets=True, fixture_path="", global_matrix=None):
    """Load the MVR file."""

    auxData.clear()
    objectData.clear()

    context.window.cursor_set('WAIT')
    mscale = mathutils.Matrix.Scale(scale_objects, 4)
    if global_matrix is not None:
        mscale = global_matrix @ mscale

    if not len(files):
        files = [Path(filepath)]
        directory = Path(filepath).parent

    default_layer = context.view_layer.active_layer_collection.collection
    for fl in files:
        if use_collection:
            collection = bpy.data.collections.new(Path(fl.name).stem)
            context.scene.collection.children.link(collection)
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collection.name]
        load_mvr(context, os.path.join(directory, fl.name), fixture_path, mscale,
                 use_apply_transform, FIXTURES=use_fixtures, TARGETS=use_targets)

    auxData.clear()
    objectData.clear()

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
