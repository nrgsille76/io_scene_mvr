# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Import is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import time
import pymvr
import mathutils
from pathlib import Path
from io_scene_3ds.import_3ds import load_3ds
from .import_gdtf import fixture_build


auxData = {}
classData = {}
objectData = {}
objectMVR = {"SceneObject", "Truss", "Support", "Projector", "VideoScreen"}
nodeMVR = {"GroupObject"}.union(objectMVR)


class FixtureGroup:
    """Class is representing a group of fixtures."""

    __slots__ = "name", "uuid"

    def __init__(self, name, uuid):
        self.name = name
        self.uuid = uuid


def get_nums(num):
    """Get the numbers from index string."""
    return list(map(int, num.replace("-", "_").split("_")))


def isZero(num):
    """Check if index is zero."""
    is_zero = num == 0
    if num is None:
        return True
    elif isinstance(num, bool):
        return num
    elif isinstance(num, str):
        nums = get_nums(num)
        is_zero = abs(sum(nums)) < 1
    elif isinstance(num, int):
        is_zero = abs(num) < 1

    return is_zero


def notZero(num):
    """Check if index has value."""
    not_zero = num != 0
    if num is None:
        return False
    elif isinstance(num, bool):
        return num
    elif isinstance(num, str):
        nums = get_nums(num)
        not_zero = (sum(nums) // len(nums)) > 0
    elif isinstance(num, int):
        not_zero = num > 0

    return not_zero


def drop_suffix(name, space=False):
    """Drop suffix string."""
    if name is None:
        return ""
    if space:
        split_name = name.split("_")
    else:
        split_name = name.split(".")
    final_name = split_name[0]
    if len(split_name) > 2:
        final_name = ".".join(split_name[:-1])

    return final_name


def get_filepath(spec, assets):
    """Search for file and create filepath."""
    filepath = None
    if spec:
        file_line = spec.replace(" ","_")
        file_space = spec.replace("_"," ")
        for root, dirs, files in os.walk(assets):
            if spec in files:
                filepath = os.path.join(root, spec)
            elif file_line in files:
                filepath = os.path.join(root, file_line)
            elif file_space in files:
                filepath = os.path.join(root, file_space)
            else:
                for file in files:
                    if drop_suffix(file) == spec:
                        filepath = os.path.join(root, file)
                        break
    return filepath


def extract_mvr_textures(mvr_scene, folder_path):
    """Extract textures from zip file."""
    for name in mvr_scene._package.namelist():
        if name.endswith(".png") or name.endswith(".jpg"):
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
    check3Digits = len(name) >= 4 and name[-3:].isdigit() and name[-4] == "."
    check4Digits = len(name) >= 5 and name[-4:].isdigit() and name[-5] == "."
    check_digits = check3Digits or check4Digits

    return check_digits


def create_index_tag(idx, grp=None, amt=False):
    """Create an ID tag."""
    if idx is None:
        idx = str(0)
    index_tag = subex_tag = " "
    if notZero(grp) and isZero(idx) and amt == 1:
        index_tag = subex_tag = f"{grp}"
    elif notZero(grp) and notZero(idx) or amt > 1:
        index_tag = f"{grp}-{idx}"
        subex_tag = f"{grp}_{idx}"
    elif notZero(idx):
        index_tag = subex_tag = f"{idx}"

    return index_tag, subex_tag


def create_layer_tag(item, index):
    """Create a layer tag."""
    item_name = drop_suffix(item.name)
    check_len = len(item_name) >=2
    check_name = check_len and item_name[0] == "L" and item_name[1].isdigit()
    if not check_name:
        item.name = "L%d %s" % (index, item_name)


def create_mvr_props(obj, mvr_cls, name="", uid=False, cls=None, ref=None, obc=None):
    """Create MVR object properties."""
    cls_name = classData.get(cls) if cls else None
    obj["MVR Class"] = mvr_cls
    if cls_name and obc != "Symdef":
        obj["Category"] = cls_name
        obj["Classing"] = cls
    if name and len(name):
        obj["MVR Name"] = name
    if obc:
        obj["MVR Type"] = obc
    if ref:
        obj["Reference"] = ref
    if uid:
        obj["UUID"] = uid


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
    check_float = any(isinstance(i, float) for i in
                      set().union(sum(mtx_data, [])))
    global_matrix = obj_mtx @ mtx if check_float else mtx

    return global_matrix


def trans_matrix(trans_mtx):
    """Transform matrix from 4x3 to 4x4."""
    mtx = list(trans_mtx)
    matrix = mathutils.Matrix((mtx[:3]+[0], mtx[3:6]+[0],
                               mtx[6:9]+[0], mtx[9:]+[1])).transposed()

    return matrix


def move_instance(obj):
    """Move instance if transform."""
    transform = obj.get("Transform")
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
                mtl_name = drop_suffix(material.name)
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
    existing = any(col.get("UUID") == node.uuid for col in collection.children)
    if existing:
        for collect in collection.children:
            if collect.get("MVR Class") == cls_name:
                for obj in collect.all_objects:
                    transform = obj.get("Transform")
                    if transform is not None:
                        obj.matrix_world = trans_matrix(transform)
    return existing


def get_clean_name(item, idx=0, grp=None):
    """Get a clean indexed object name."""
    if item is None:
        return
    layerTag = isinstance(grp, str)
    itsaNumber = isinstance(grp, int)
    itsaString = isinstance(item, str)
    id_name = item if itsaString else item.name
    item_cls = mvr_cls = item.__class__.__name__
    item_name = layer_name = drop_suffix(id_name)
    hasNumber = len(item_name) and item_name[-1].isdigit()
    strNumber = layerTag and "-" not in grp and "_" not in grp
    mvr_cls = item_cls if itsaString else item.get("MVR Class")
    grp_idx = f"{grp}_{idx}" if item_cls == "Object" else f"{grp}-{idx}"
    if notZero(idx) and notZero(grp) and (strNumber or itsaNumber):
        layer_name = f"{item_name} {grp_idx}"
    elif grp is None and notZero(idx):
        layer_name = f"{item_name} {idx}"
    elif notZero(grp) and not hasNumber:
        layer_name = f"{item_name} {grp}"
    if itsaString:
        return layer_name
    elif check_for_digits(item.name) or item_name == mvr_cls:
        item.name = layer_name
    if check_for_digits(item.name) and (strNumber or itsaNumber):
        if item_cls == "Collection":
            item.name = f"{item_name} {grp}-{idx}"
        elif item_cls == "Object":
            item.name = f"{item_name} {grp}_{idx}"
    if grp is None and check_for_digits(item.name):
        item.name = f"{item_name} {idx}"
    elif layerTag and check_for_digits(item.name):
        item.name = f"{item_name} {idx} {grp}"
    if check_for_digits(item.name):
        if itsaNumber:
            idsum = sum((idx, grp))
            item.name = f"{item_name} {idsum}"
        elif isZero(grp) and item_cls == "Collection":
            item.name = f"{item_name} 0-{idx}"
        elif isZero(grp) and item_cls == "Object":
            item.name = f"{item_name} 0_{idx}"


def get_mvr_name(node, index=0, layer=None):
    """Get a proper MVR name."""
    name = node.name
    layer_id = f"{index}"
    cls_name = node.__class__.__name__
    mvr_name = name if name else cls_name
    if notZero(layer) and notZero(index):
        layer_id = f"{layer}-{index}"
    elif notZero(layer) and isZero(index):
        layer_id = f"{layer}"
    if isZero(layer) and isZero(index):
        idx_name = mvr_name
    elif cls_name == "Layer":
        idx_name = f"L{layer_id} {mvr_name}"
    else:
        idx_name = f"{mvr_name} {layer_id}"

    return mvr_name, idx_name, cls_name


def add_mvr_fixture(context, mvr_scene, fixture, mscale, folderpath, fixture_idx,
                    layer_idx, extracted, group_collect, apply, TARGETS,
                    focus_points, fixture_path, fixture_group=None):

    """Add fixture to the scene."""
    fixture_pos = get_matrix(fixture, mscale)
    if fixture.gdtf_spec:
        fixture_file = os.path.join(folderpath, fixture.gdtf_spec)
    else:
        fixture_file = os.path.join(folderpath, "Custom@Fixture.gdtf")
    if fixture.fixture_id is not None and len(fixture.fixture_id):
        fixture_id = int(fixture.fixture_id)
    else:
        fixture_id = int(f"{layer_idx}{fixture_idx}")

    if f"{fixture.gdtf_spec}" in mvr_scene._package.namelist():
        if fixture.gdtf_spec not in extracted.keys():
            mvr_scene._package.extract(fixture.gdtf_spec, folderpath)
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
        print(f"Info: {fixture.gdtf_spec} not available, using generic PAR instead.")
        fixture.gdtf_spec = "NRGSille_Lighting@Simple_LED_PAR@rev2.gdtf"
        fixture_file = os.path.join(Path(folderpath).parent.parent, "gdtf", fixture.gdtf_spec)

    fixture_build(context, fixture_file, mscale, fixture.name, fixture_pos, focus_point,
                  fixture_id, fixture.color, group_collect, fixture, TARGETS)

    if len(focus_points) and focus_points[0].geometries:
        print("importing FocusPoint... %s" % fixture.name)
        target_collect = next((col for col in bpy.data.collections if
                               col.get("Target ID") == fixture.focus), None)
        if target_collect:
            group_collect = target_collect
        process_mvr_object(context, mvr_scene, focus_points[0], fixture_idx,
                           mscale, apply, folderpath, extracted, group_collect)


def get_child_list(context, mscale, mvr_scene, layer, layer_idx, folderpath, extracted,
                   layer_collect, apply, FIXTURES, TARGETS, fixpath, fixture_group=None):
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
            group_name =  get_clean_name(group_name, truss_idx)
            fixture_group = FixtureGroup(group_name, truss_obj.uuid)

        if not existing:
            process_mvr_object(context, mvr_scene, truss_obj, truss_idx, mscale,
                               apply, folderpath, extracted, layer_collect)

        if hasattr(truss_obj, "child_list") and truss_obj.child_list:
            get_child_list(context, mscale, mvr_scene, truss_obj, truss_idx,
                           folderpath, extracted, layer_collect, apply,
                           FIXTURES, TARGETS, fixpath, fixture_group)

    for support_idx, support_obj in enumerate(child_list.supports):
        existing = check_existing(support_obj, layer_collect)

        if fixture_group is None:
            group_name = support_obj.name or "Support"
            group_name =  get_clean_name(group_name, support_idx)
            fixture_group = FixtureGroup(group_name, support_obj.uuid)

        if not existing:
            process_mvr_object(context, mvr_scene, support_obj, support_idx,
                               mscale, apply, folderpath, extracted, layer_collect)

        if hasattr(support_obj, "child_list") and support_obj.child_list:
            get_child_list(context, mscale, mvr_scene, support_obj, support_idx,
                           folderpath, extracted, layer_collect, apply,
                           FIXTURES, TARGETS, fixpath, fixture_group)

    for project_idx, project_obj in enumerate(child_list.projectors):
        existing = check_existing(project_obj, layer_collect)

        if fixture_group is None:
            group_name = project_obj.name or "Projector"
            group_name =  get_clean_name(group_name, project_idx)
            fixture_group = FixtureGroup(group_name, project_obj.uuid)

        if not existing:
            process_mvr_object(context, mvr_scene, project_obj, project_idx,
                               mscale, apply, folderpath, extracted, layer_collect)

        if hasattr(project_obj, "child_list") and project_obj.child_list:
            get_child_list(context, mscale, mvr_scene, project_obj, project_idx,
                           folderpath, extracted, layer_collect, apply,
                           FIXTURES, TARGETS, fixpath, fixture_group)

    for screen_idx, screen_obj in enumerate(child_list.video_screens):
        existing = check_existing(screen_obj, layer_collect)

        if fixture_group is None:
            group_name = screen_obj.name or "Screen"
            group_name =  get_clean_name(group_name, screen_idx)
            fixture_group = FixtureGroup(group_name, screen_obj.uuid)

        if not existing:
            process_mvr_object(context, mvr_scene, screen_obj, screen_idx,
                               mscale, apply, folderpath, extracted, layer_collect)

        if hasattr(screen_obj, "child_list") and screen_obj.child_list:
            get_child_list(context, mscale, mvr_scene, screen_obj, screen_idx,
                           folderpath, extracted, layer_collect, apply,
                           FIXTURES, TARGETS, fixpath, fixture_group)
            
    for scene_idx, scene_obj in enumerate(child_list.scene_objects):
        existing = check_existing(scene_obj, layer_collect)

        if not existing:
            process_mvr_object(context, mvr_scene, scene_obj, scene_idx, mscale,
                               apply, folderpath, extracted, layer_collect)

        if hasattr(scene_obj, "child_list") and scene_obj.child_list:
            get_child_list(context, mscale, mvr_scene, scene_obj, scene_idx, folderpath,
                           extracted, layer_collect, apply, FIXTURES, TARGETS, fixpath)

    if FIXTURES:
        if fixture_group is None:
            lyr_name = layer.name or "Layer"
            fixture_group = FixtureGroup(lyr_name, layer.uuid)
        for fixture_idx, fixture in enumerate(child_list.fixtures):
            focus_points = []
            if fixture.focus is not None:
                focus_points.extend([fp for fp in child_list.focus_points if
                                     fp.uuid == fixture.focus])

            add_mvr_fixture(context, mvr_scene, fixture, mscale, folderpath,
                            fixture_idx, layer_idx, extracted, layer_collect,
                            apply, TARGETS, focus_points, fixpath, fixture_group)

            if hasattr(fixture, "child_list") and fixture.child_list:
                get_child_list(context, mscale, mvr_scene, fixture, fixture_idx,
                               folderpath, extracted, layer_collect, apply,
                               FIXTURES, TARGETS, fixpath, fixture_group)

    for group_idx, group in enumerate(child_list.group_objects):
        if hasattr(group, "child_list") and group.child_list:
            group_name, index_name, group_class = get_mvr_name(group, group_idx, layer_idx)
            if layer_collect.get("MVR Class") == "Layer" and group.name is None:
                group.name = "L%d Group" % layer_idx if notZero(layer_idx) else "Group"
                group_name, index_name, group_class = get_mvr_name(group, group_idx)   
            print("importing %s... %s" % (group_class, index_name))
            group_collection = data_collect.new(group_name)
            group_collection["MVR Index"] = layer_idx
            layer_collect.children.link(group_collection)
            create_transform_property(group, group_collection, True)
            classing = group.classing if hasattr(group, "classing") else None
            create_mvr_props(group_collection, group_class, group_name,
                             group.uuid, classing, layer_collect.name)
            get_child_list(context, mscale, mvr_scene, group, group_idx, folderpath, extracted,
                           group_collection, apply, FIXTURES, TARGETS, fixpath, fixture_group)

    for obj in viewlayer.active_layer_collection.collection.all_objects:
        obj.select_set(True)


def process_mvr_object(context, mvr_scene, mvr_object, mvr_idx, mscale,
                       apply, folderpath, extracted, group_collect):
    """Processing MVR xml node objects."""

    uid = mvr_object.uuid
    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    scene_collect = context.scene.collection
    layer_collect = viewlayer.layer_collection
    active_layer = viewlayer.active_layer_collection
    itsaSymdef = isinstance(mvr_object, pymvr.Symdef)
    itsaFocus = isinstance(mvr_object, pymvr.FocusPoint)
    name, idx_name, class_name = get_mvr_name(mvr_object, mvr_idx)
    classing = mvr_object.classing if hasattr(mvr_object, "classing") else None
    print("creating %s... %s" % (class_name, idx_name))

    def add_mvr_object(node, mtx, collect, folder=None, file=""):
        imported = []
        item_name = Path(file).name
        mesh_name = Path(file).stem
        mesh_data = bpy.data.meshes
        node_type = node.__class__.__name__
        gltf = file.split(".")[-1] == "glb"
        scale_factor = 0.001 if file.split(".")[-1] == "3ds" else 1.0
        mesh_exist = next((msh for msh in mesh_data if msh.name == mesh_name), False)
        exist = any(ob.data and ob.data.name == mesh_name for ob in collect.objects)
        world_matrix = mtx @ mathutils.Matrix.Scale(scale_factor, 4)
        print("adding %s... %s" % (node_type, mesh_name))

        if not exist:
            if mesh_exist:
                mesh_id = mesh_exist.get("MVR Name", mesh_name)
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
                obname = drop_suffix(obj.name)
                create_mvr_props(obj, class_name, obname, uid,
                                 classing, mesh_name, node_type)
                if obj.parent is None:
                    if gltf or obj.type != 'MESH':
                        obj.matrix_world = world_matrix @ obj.matrix_world.copy()
                    else:
                        obj.matrix_world = world_matrix
                if obj.data is None:
                    obj.empty_display_size = 0.001
                else:
                    obj.data.name = mesh_name
                    create_mvr_props(obj.data, class_name, obname, uid,
                                     classing, item_name, node_type)
                    if obj.data.id_type == 'MESH':
                        for material in obj.data.materials:
                            create_mvr_props(material, class_name, obname,
                                             uid, classing, item_name)
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
    elif not itsaSymdef and mvr_object.geometries:
        symbols += mvr_object.geometries.symbol
        geometrys += mvr_object.geometries.geometry3d
    elif class_name not in objectMVR:
        symbols += mvr_object.symbol
        geometrys += mvr_object.geometry3d

    if itsaFocus:
        active_collect = group_collect
    elif itsaSymdef:
        create_mvr_props(group_collect, class_name, name, uid)
        active_collect = next((col for col in data_collect if
                               col.get("Reference") == uid), False)
        if not active_collect:
            active_collect = data_collect.get(uid)
            if active_collect is None:
                active_collect = data_collect.new(uid)
        if active_collect.get("MVR Class") is None:
            create_mvr_props(active_collect, class_name, name, uid)
        active_collect.hide_render = True
    elif not itsaFocus and (len(geometrys) + len(symbols)) > 1:
        print("creating extra collection", idx_name)
        active_collect = data_collect.new(name)
        create_mvr_props(active_collect, class_name, idx_name, uid, classing)
        group_collect.children.link(active_collect)
        collection = active_collect

    if active_collect is None:
        active_collect = next((col for col in data_collect if
                               col.get("UUID") == uid), False)
        if not active_collect and not len(symbols):
            reference = collection.get("UUID")
            active_collect = data_collect.new(name)
            create_mvr_props(active_collect, class_name, idx_name, uid, classing, reference)

    for geometry in geometrys:
        file = geometry.file_name
        extract_mvr_object(mvr_scene, extracted, folderpath, file)
        obj_mtx = get_matrix(mvr_object, mscale) if itsaFocus else get_matrix(geometry, mscale)
        object_collect = add_mvr_object(geometry, obj_mtx, active_collect, folderpath, file)
        if (
            object_collect and collection != object_collect
            and object_collect.name not in collection.children
        ):
            collection.children.link(object_collect)
               
    for idx, symbol in enumerate(symbols):
        symbol_type = symbol.__class__.__name__
        symbol_mtx = get_matrix(symbol, context_matrix)
        if not itsaSymdef:
            symbol_mtx = get_matrix(mvr_object, symbol_mtx)
        symbol_collect = data_collect.get(symbol.symdef)

        if symbol_collect:
            symbol_name = symbol_collect.get("MVR Name")
            symbol_object = object_data.new(name, None)
            collection.objects.link(symbol_object)
            symbol_object.matrix_world = symbol_mtx
            symbol_object.empty_display_size = 0.001
            symbol_object.empty_display_type = 'ARROWS'
            symbol_object.instance_type = 'COLLECTION'
            symbol_object.instance_collection = symbol_collect
            create_transform_property(symbol_object, symbol_collect)
            create_mvr_props(symbol_object, class_name, name, uid,
                             classing, symbol.uuid, symbol_type)
            create_mvr_props(symbol_collect, symbol_type, symbol_name,
                             symbol.uuid, classing, symbol.symdef, "Symdef")

    if itsaFocus:
        focus_target = next((ob for ob in group_collect.objects if
                             ob.get("Geometry Type") == "Target" and
                             ob.get("UUID") == mvr_object.uuid), None)
        if focus_target:
            focus_idx = group_collect.get("Fixture ID")
            target_mtx = focus_target.matrix_world.copy()
            for ob in group_collect.objects:
                if (
                    ob.parent is None and
                    ob.get("MVR Class") == "FocusPoint" and
                    ob.get("UUID") == mvr_object.uuid
                ):
                    ob.parent = focus_target
                    ob.matrix_parent_inverse = focus_target.matrix_world.inverted()
                if focus_idx and check_for_digits(ob.name):
                    ob.name = "ID%d %s" % (focus_idx, drop_suffix(ob.name))


def finalize_objects(layers, mscale):
    """Transform objects matrix."""

    def transform_matrix(mvr):
        obj_collect = objectData.get(mvr.uuid)
        if obj_collect is not None:
            global_mtx = get_matrix(mvr, mscale)
            for obj in obj_collect.objects:
                if obj.parent is None:
                    obj.matrix_world = global_mtx @ obj.matrix_world.copy()
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


def create_tree_branch(layers, count):
    """Create MVR collection tree."""
    layers_cls = layers.get("MVR Class")
    if layers.get("MVR Index"):
        count = layers.get("MVR Index")

    def provide_geometries(geometries, tag, lyr=False, prt=None):
        """Treat collection objects."""
        ob_count = len(geometries.objects)
        for obx, obj in enumerate(geometries.objects):
            merge_material(obj)
            if obj and obj.is_instancer:
                move_instance(obj)
            if check_for_digits(obj.name) and not lyr and notZero(count):
                create_layer_tag(obj, count)
            if prt and ob_count == 1:
                get_clean_name(obj, prt, tag)
            else:
                get_clean_name(obj, obx, tag)

            if check_for_digits(obj.name):
                create_layer_tag(obj, count)
                get_clean_name(obj, obx, tag)

    def index_scene_object(col, idx, cdx, gcls, tag=None, level=False):
        """Index scene object collections."""
        col_name = drop_suffix(col.name)
        oblyr = False if gcls == "Layer" else True
        if check_for_digits(col.name) and notZero(count):
            create_layer_tag(col, count)
            col_name = col.name
        if tag is not None:
            get_clean_name(col, idx, tag[0])
            provide_geometries(col, tag[1], oblyr, idx)
        elif not oblyr and cdx != count:
            get_clean_name(col, idx, cdx)
            provide_geometries(col, idx, oblyr, cdx)
        else:
            get_clean_name(col, idx)
            provide_geometries(col, idx, oblyr)
        if check_for_digits(col.name):
            col.name = col_name
            if tag is not None:
                get_clean_name(col, cdx, tag[0])
            else:
                get_clean_name(col, cdx)

    def index_group_object(group, gidx, lidx, level=False):
        """Index group collections."""
        objs = len(group.objects)
        clds = len(group.children)
        grpcls = group.get("MVR Class")
        grptag = create_index_tag(gidx, lidx, objs)
        provide_geometries(group, grptag[1], True)
        for idc, col in enumerate(group.children):
            obs = len(col.objects)
            colcls = col.get("MVR Class")
            if colcls in objectMVR:
                if level:
                    obtag = create_index_tag(gidx, lidx, clds)
                else:
                    obtag = create_index_tag(idc, gidx, obs)
                index_scene_object(col, idc, gidx, grpcls, obtag, level)
            elif colcls == "GroupObject":
                get_clean_name(col, idc, gidx)
                index_group_object(col, idc, gidx, True)

    provide_geometries(layers, count, True)
    for lidx, layer in enumerate(layers.children):
        if layer.get("Fixture ID") is None:
            lyrcls = layer.get("MVR Class")
            if lyrcls in objectMVR:
                if check_for_digits(layer.name) and notZero(count):
                    object_name = drop_suffix(layer.name)
                    if object_name != layer.name:
                        create_layer_tag(layer, count)
                index_scene_object(layer, lidx, count, layers_cls)
            elif lyrcls == "GroupObject":
                get_clean_name(layer, lidx)
                index_group_object(layer, lidx, count)


def load_mvr(context, filename, fixpath, mscale=mathutils.Matrix(),
             APPLY_MATRIX=False, FIXTURES=True, TARGETS=True):
    """Create MVR scene and import layers."""

    symdefs = []
    extracted = {}
    auxdata = None
    mvr_layers = []
    imported_layers = []
    start_time = time.time()
    viewlayer = context.view_layer
    layers_name = Path(filename).stem
    data_collect = bpy.data.collections
    scene_collect = context.scene.collection
    view_collect = viewlayer.layer_collection
    layer_collect = view_collect.collection
    active_layer = viewlayer.active_layer_collection
    aux_dir = scene_collect.children.get("AUXData")
    mvr_scene = pymvr.GeneralSceneDescription(filename)
    current_path = os.path.dirname(os.path.realpath(__file__))
    folderpath = os.path.join(current_path, "assets", "mvr", layers_name)
    mvr_layers = mvr_scene.layers if hasattr(mvr_scene, "layers") else []
    extract_mvr_textures(mvr_scene, folderpath)
    print("\ncreating Scene... %s" % layers_name)

    """Deselect all objects."""
    for ob in viewlayer.objects.selected:
        ob.select_set(False)

    if hasattr(mvr_scene, "scene") and mvr_scene.scene:
        auxdata = mvr_scene.scene.aux_data
        mvr_layers = mvr_scene.scene.layers

    classes = auxdata.classes if auxdata is not None else []
    symdefs = auxdata.symdefs if auxdata is not None else []

    if auxdata is not None:
        print("importing AUXData...")
        for cls in classes:
            classData[cls.uuid] = cls.name

        for aux_idx, symdef in enumerate(symdefs):
            if aux_dir and symdef.name in aux_dir.children:
                aux_collection = aux_dir.children.get(symdef.name)
            elif symdef.name in data_collect:
                aux_collection = data_collect.get(symdef.name)
            else:
                aux_collection = data_collect.new(symdef.name)

            auxData.setdefault(symdef.uuid, aux_collection)
            process_mvr_object(context, mvr_scene, symdef, aux_idx, mscale,
                               APPLY_MATRIX, folderpath, extracted, aux_collection)

            if hasattr(symdef, "child_list") and symdef.child_list:
                get_child_list(context, mscale, mvr_scene, symdef.child_list, aux_idx, folderpath,
                               extracted, aux_collection, APPLY_MATRIX, FIXTURES, TARGETS, fixpath)

    print("importing Layers... %s" % scene_collect.name)
    for layer_idx, layer in enumerate(mvr_layers):
        layer_collection = next((col for col in data_collect if
                                 col.get("UUID") == layer.uuid), False)
        if not layer_collection:
            layer_name, mvr_layer, layer_class = get_mvr_name(layer, layer_idx)
            layer_collection = data_collect.new(mvr_layer)
            layer_collection["MVR Index"] = layer_idx
            create_transform_property(layer, layer_collection, True)
            create_mvr_props(layer_collection, layer_class, layer_name, layer.uuid)
            print("importing %s... %s" % (layer_class, mvr_layer))
            layer_collect.children.link(layer_collection)
            imported_layers.append(layer_collection)

        get_child_list(context, mscale, mvr_scene, layer, layer_idx, folderpath,
                       extracted, layer_collection, APPLY_MATRIX, FIXTURES, TARGETS, fixpath)

        if len(layer_collection.all_objects) == 0 and layer_collection.name in layer_collect.children:
            layer_collect.children.unlink(layer_collection)

    finalize_objects(mvr_layers, mscale)

    if auxData.items():
        aux_type = auxdata.__class__.__name__
        if "AUXData" in data_collect:
            aux_directory = data_collect.get("AUXData")
        else:
            print("creating AUXData...")
            aux_directory = data_collect.new("AUXData")
            create_mvr_props(aux_directory, aux_type)
            layer_collect.children.link(aux_directory)
        if classData.items() and "View Classes" not in aux_directory.keys():
            aux_directory["View Classes"] = classData
        for sid, (uid, auxcollect) in enumerate(auxData.items()):
            if auxcollect.name not in aux_directory.children:
                aux_directory.children.link(auxcollect)
            sym_collect = data_collect.get(uid)
            if sym_collect:
                if sym_collect.name in layer_collect.children:
                    layer_collect.children.unlink(sym_collect)
                elif sym_collect.name not in auxcollect.children:
                    auxcollect.children.link(sym_collect)
                sym_collect.name = sym_collect.get("MVR Name")
                if check_for_digits(sym_collect.name):
                    get_clean_name(sym_collect, sid)
                sym_objects = list(filter(None, sym_collect.all_objects))
                for idx, obj in enumerate(sym_objects):
                    merge_material(obj)
                    if check_for_digits(obj.name):
                        get_clean_name(obj, idx, sid)

    for index, layer in enumerate(imported_layers):
        create_tree_branch(layer, index)

    if mvr_layers:
        for view in view_collect.children:
            if view.name == "AUXData":
                for childs in view.children:
                    for collect in childs.children:
                        collect.hide_viewport = True

    viewlayer.update()
    objectData.clear()
    classData.clear()
    auxData.clear()
    imported_layers.clear()
    #[fl.unlink() for fl in Path(folderpath).iterdir() if fl.is_file()] 
    print("MVR scene loaded in %.4f sec.\n" % (time.time() - start_time))


def load(operator, context, files=[], directory="", filepath="", scale_objects=1.0, use_collection=False,
         use_apply_transform=False, use_fixtures=True, use_targets=True, fixture_path="", global_matrix=None):
    """Load the MVR file."""

    auxData.clear()
    objectData.clear()

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
                 APPLY_MATRIX=use_apply_transform, FIXTURES=use_fixtures, TARGETS=use_targets)

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    return {'FINISHED'}
