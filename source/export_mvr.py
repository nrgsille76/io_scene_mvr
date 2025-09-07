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


classData = None
mixType = {'MIX', 'MIX_RGB'}
objectStudio = {'LIGHT', 'CAMERA'}
objectGeometry = {'MESH', 'EMPTY'}
objectMVR = {"SceneObject", "Truss", "Support", "Projector", "VideoScreen"}
nodeMVR = {"GroupObject"}.union(objectMVR)


def get_gdtf_name(name):
    """Create GDTF Spec (Company@Fixture.gdtf)."""
    if name is None:
        gdtf_name = "LightCompany@CustomFixture.gdtf"
    elif "@" not in name:
        gdtf_name = "@".join(name.split())
    else:
        split_name = name.split("@")
        if len(split_name) >= 2:
            gdtf_name = "@".join((split_name[0], split_name[1]))
        else:
            gdtf_name = split_name[0]
    if not gdtf_name.split(".")[-1] == "gdtf":
        gdtf_name = ".".join((gdtf_name, "gdtf"))

    return gdtf_name


def get_filepath(spec, assets, gdtfname=False):
    """Search for file and create filepath."""
    filepath = None
    if spec:
        file_line = spec.replace(" ","_")
        file_space = spec.replace("_"," ")
        for root, dirs, files in os.walk(assets):
            if spec in files:
                filepath = os.path.join(root, spec)
            elif gdtfname:
                fix_name = get_gdtf_name(spec)
                for file in files:
                    fix_type = get_gdtf_name(file)
                    fix_line = fix_type.replace(" ","_")
                    fix_space = fix_type.replace("_"," ")
                    if (fix_type == fix_name) or (fix_line == spec) or (fix_space == spec):
                        filepath = os.path.join(root, file)
                        break
            elif file_line in files:
                filepath = os.path.join(root, file_line)
            elif file_space in files:
                filepath = os.path.join(root, file_space)

    return filepath


def remove_layer_tag(item):
    """Remove a layer tag."""
    item_name = item.name
    if len(item_name) >=3 and " " in item_name:
        check_space = item_name[2] == " " or item_name[2].isdigit()
        check_name = item.name[0] == "L" and item.name[1].isdigit()
        if check_name and check_space:
            split_name = item.name.split()
            if len(split_name) >= 2:
                item_name = " ".join(split_name[1:2])
            elif split_len == 2:
                item_name = split_name[1]

    return item_name


def cleanup_xml(node):
    """Remove None attributes from XML node."""
    node.attrib = {key: node.attrib[key] for key in node.attrib if node.attrib[key] is not None}
    for subnode in node:
        cleanup_xml(subnode)


def convert_rgb(rgb):
    """Convert from RGB to xyY (CIE 1931) colorspace."""
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


def create_layer(layername, node, node_cls, uid=None, parents=[]):
    if node_cls != "Layer":
        if uid:
            layer = pymvr.Layer(name=layername, uuid=uid)
        else:
            layer = pymvr.Layer(name=layername)
        layer_cls = layer.__class__.__name__
        layer_node = layer.to_xml(parent=node)
    else:
        if uid:
            group = pymvr.GroupObject(name=layername, uuid=uid)
        else:
            group = pymvr.GroupObject(name=layername)
        layer_cls = group.__class__.__name__
        layer_node = group.to_xml()
        parents.append(layer_node)
    layer_list = pymvr.ChildList().to_xml(parent=layer_node)

    return layer_node, layer_cls, layer_list


def get_material_images(material, path):
    """Collect material textures."""
    images = []

    def get_image(image):
        if image:
            img_name = Path(image.filepath).name
            file_path = os.path.join(path, img_name)
            if image.has_data and not os.path.isfile(file_path):
                image.save(filepath=file_path)
                images.append((file_path, img_name))

    if material and material.node_tree and not (material.get("Geometry Type") == "Gobo"):
        links = material.node_tree.links
        mtex = [lk.from_node for lk in links if lk.from_node.type == 'TEX_IMAGE' and lk.to_node.type in mixType]
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
    """Convert transmatrix from 4x3 to 4x4."""
    mtx = list(trans_mtx)
    matrix = mathutils.Matrix((mtx[:3]+[0], mtx[3:6]+[0], mtx[6:9]+[0], mtx[9:]+[1])).transposed()

    return matrix


def get_transmatrix(matrix, obj=None):
    """Create transposed 4x3 matrix."""
    mtx_cls = matrix.__class__.__name__
    if obj:
        mtx_copy = obj.matrix_world.copy()
        matrix = mtx_copy @ matrix
    if isinstance(matrix, tuple) or mtx_cls == "IDPropertyArray":
        matrix = trans_matrix(matrix)
    rotate = matrix.to_quaternion()
    translate = matrix.to_translation()
    scale = mathutils.Matrix().to_scale()
    mtx = mathutils.Matrix.LocRotScale(translate, rotate, scale).transposed().to_3x3()
    trans_mtx = list((mtx[0][:], mtx[1][:], mtx[2][:], translate[:]))

    return trans_mtx


def export_3ds(context, path, objects, SELECT, APPLY_MATRIX, CONVERSE, scale=1000.0, collection="", studio=None):
    """Export 3DStudio files."""
    save_3ds(context, path, collection, objects, scale, CONVERSE, SELECT, APPLY_MATRIX, studio, True)


def get_fixture(context, fixture, specs, file_list, folders, scale, SELECT, TARGETS, CONVERSE, APPLY_MATRIX):
    """Collect fixtures and focuspoints."""
    patch_numbers = []
    focus_point = None
    uid = fixture.get("UUID")
    fixture_name = fixture.get("Fixture Name")
    props = ["Patch Break", "Patch Universe", "Patch Address"]
    base = next((ob for ob in fixture.objects if ob.get("Use Root")), None)
    target = next((ob for ob in fixture.objects if ob.get("Geometry Type") == "Target"), None)
    fix_id = fixture.get("Fixture ID")
    fix_mode = base.get("Fixture Mode")
    transmtx = Matrix(get_transmatrix(CONVERSE, base))

    if target and TARGETS:
        focus_objects = []
        geometries = pymvr.Geometries()
        target_uid = target.get("UUID")
        target_name = target.get("Fixture Name")
        focus_name = target_name + " FocusPoint"
        focus_mtx = Matrix(get_transmatrix(CONVERSE, target))
        print("exporting FocusPoint... %s" % focus_name)
        if target.children and any((ob.type == 'MESH' for ob in target.children_recursive)):
            target_mesh = '.'.join((' '.join((target_name, "Target")), "3ds"))
            for obj in target.children_recursive:
                if obj.parent == target:
                    target_mtx = obj.matrix_parent_inverse.copy() @ target.matrix_local.copy()
                    focus_mtx = Matrix(get_transmatrix(target_mtx, obj))
                if obj.type == 'MESH':
                    file_list.extend(get_material_images(obj.active_material, folders))
                if obj.get("Geometry Class") != "Target":
                    focus_objects.append(obj)
        focus_point = pymvr.FocusPoint(uuid=target_uid, name=focus_name, matrix=focus_mtx).to_xml()
        if len(focus_objects):
            print("exporting Geometry3D... %s" % target_mesh)
            mvr_object = pymvr.Geometry3D(file_name=target_mesh)
            geometries.geometry3d.append(mvr_object)
            file_path = os.path.join(folders, target_mesh)
            export_3ds(context, file_path, focus_objects, SELECT, APPLY_MATRIX, CONVERSE, scale)
            file_list.append((file_path, target_mesh))
            geometries.to_xml(parent=focus_point)
        geometries.geometry3d.clear()
        geometries.symbol.clear()
        fix_object = pymvr.Fixture(name=fixture_name, uuid=uid, gdtf_spec=specs, gdtf_mode=fix_mode, matrix=transmtx,
                                   fixture_id=str(fix_id), fixture_id_numeric=fix_id, focus=target_uid)
    else:
        fix_object = pymvr.Fixture(name=fixture_name, uuid=uid, gdtf_spec=specs, gdtf_mode=fix_mode,
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

    return file_list, fix_object, focus_point      


def export_mvr(context, items, filename, fixturepath, folder_path, asset_path, scalefactor,
               SELECT, IMAGES, FIXTURES, TARGETS, CONVERSE, APPLY_MATRIX, VERSION):
    """Export MVR xml tree."""

    scene_collection = context.scene.collection
    blend_file = Path(bpy.data.filepath).stem
    layers_name = Path(filename).stem
    scene_name = context.scene.name
    layer_list = None
    file_list = []

    print("\ncreating Scene... %s" % blend_file)
    layers_element = pymvr.LayersElement()
    layers_cls = layers_element.__class__.__name__
    scale_vec = mathutils.Vector.Fill(3, scalefactor)
    mvr = pymvr.GeneralSceneDescriptionWriter()
    user = pymvr.UserData().to_xml(parent=mvr.xml_root)
    scene = pymvr.SceneElement().to_xml(parent=mvr.xml_root)
    print("collecting Elements... %s" % layers_name)
    pymvr.Data(ver=VERSION).to_xml(parent=user)
    layers = layers_element.to_xml(parent=scene)
    auxdata = pymvr.AUXData()


    def export_fixture(profile, parent_name, child_list, file_list):
        if child_list is None:
            layer, cls, child_list = create_layer(parent_name, layers, layers_cls)
            print("exporting %s... %s" % (cls, parent_name))
        print("exporting Fixture... %s" % profile.name)
        gdtf_name = profile.get("GDTF Spec")
        gdtf_spec = get_gdtf_name(gdtf_name)
        profile_path = get_filepath(gdtf_spec, asset_path, True)
        if fixturepath and profile_path is None:
            profile_path = get_filepath(gdtf_spec, fixturepath, True)
        file_list, fix_object, focus_point = get_fixture(context, profile, gdtf_name,
                                                         file_list, folder_path, scalefactor,
                                                         SELECT, TARGETS, CONVERSE, APPLY_MATRIX)
        if profile_path:
            file_list.append((profile_path, Path(profile_path).name))
        child_list.append(fix_object.to_xml())
        if focus_point:
            child_list.append(focus_point)


    def create_studio_object(studiolayer, child_list, file_list):
        print("creating SceneObject... 3DStudio %s" % studiolayer)
        studio_name = " ".join((studiolayer, "3DStudio"))
        studio_file = ".".join((studio_name, "3ds"))
        transmtx = Matrix(get_transmatrix(CONVERSE))
        stuff = pymvr.Geometry3D(file_name=studio_file)
        print("exporting Geometry3D... %s" % studio_file)
        file_path = os.path.join(folder_path, studio_file)
        scene_object = pymvr.SceneObject(name=studio_name, matrix=transmtx).to_xml()
        export_3ds(context, file_path, [], SELECT, APPLY_MATRIX,
                   CONVERSE, scalefactor, studiolayer, objectStudio)
        file_list.append((file_path, studio_file))
        stuff_list = pymvr.Geometries()
        stuff_list.geometry3d.append(stuff)
        stuff_list.to_xml(parent=scene_object)
        child_list.append(scene_object)
        stuff_list.geometry3d.clear()
        stuff_list.symbol.clear()

        return child_list, file_list


    def export_symbol(sym):
        sym_uid = sym.get("UUID")
        sym_ref = sym.get("Reference")
        transform = sym.get("Transform")
        transmtx = Matrix(get_transmatrix(transform))
        symbol_name = sym.get("MVR Name") if sym.get("MVR Name") else sym.name
        print("exporting Symbol... %s" % symbol_name)
        instance = (sym.instance_collection.get("Reference") if
                    sym.instance_collection else sym.get("Reference"))
        symbol = pymvr.Symbol(uuid=sym_ref, symdef=instance)

        return symbol, transmtx


    def export_geometry(scene_obj, obj_name, file_list):
        class_name = scene_obj.__class__.__name__
        print("exporting Geometry3D... %s" % obj_name)
        file_path = os.path.join(folder_path, obj_name)
        file_list.append((file_path, obj_name))
        transmtx = Matrix(get_transmatrix(CONVERSE))
        geometry = pymvr.Geometry3D(file_name=obj_name)
        clsing = obj_class = None
        if class_name == "Collection":
            obj_mtx = scene_obj.get("Transform")
            obj_class = scene_obj.get("MVR Class")
            average = CONVERSE.to_translation()
            consize = CONVERSE.to_scale()
            for ob in scene_obj.objects:
                if IMAGES and not (SELECT and not ob.select_get()):
                    file_list.extend(get_material_images(ob.active_material, folder_path))
                if obj_mtx is None:
                    mtx = ob.get("Transform")
                    if mtx:
                        average += mathutils.Vector(tuple(mtx[9:]))
                        consize += trans_matrix(mtx).to_scale()
                    else:
                        average += ob.matrix_world.copy().to_translation()
                        consize += ob.matrix_world.copy().to_scale()
            if obj_mtx:
                scale = trans_matrix(obj_mtx).to_scale()
                transmtx = Matrix(get_transmatrix(obj_mtx))
            elif not APPLY_MATRIX:
                amount = mathutils.Vector.Fill(3, len(scene_obj.objects))
                scale = mathutils.Vector(tuple(consize[i] / amount[i] for i in range(3)))
                vector = tuple(average[i] / amount[i] for i in range(3))
                translate = mathutils.Matrix.Translation(vector)
                transmtx = Matrix(get_transmatrix(translate))
            convertscale = sum(scale * scale_vec) / 3
            export_3ds(context, file_path, scene_obj.all_objects, SELECT,
                       APPLY_MATRIX, CONVERSE, convertscale, scene_obj.name)
        elif class_name == "Object":
            object_list = [scene_obj]
            if IMAGES:
                file_list.extend(get_material_images(scene_obj.active_material, folder_path))
            for child in scene_obj.children_recursive:
                object_list.append(child)
                if IMAGES:
                    file_list.extend(get_material_images(child.active_material, folder_path))
            mtx = scene_obj.get("Transform")
            if mtx:
                transmtx = Matrix(get_transmatrix(mtx))
            elif not APPLY_MATRIX:
                transmtx = Matrix(get_transmatrix(CONVERSE, scene_obj))
            convertscale = sum(scene_obj.matrix_world.to_scale() * scale_vec) / 3
            export_3ds(context, file_path, object_list, SELECT,
                       APPLY_MATRIX, CONVERSE, convertscale)

        return geometry, transmtx


    def create_scene_object(scene_layer, child_list, file_list, single=False):
        col_uid = scene_layer.get("UUID")
        col_name = remove_layer_tag(scene_layer)
        if scene_layer.get("MVR Name"):
            col_name = scene_layer.get("MVR Name")
        mesh_list = pymvr.Geometries()
        col_cls = scene_layer.get("MVR Class")
        if single:
            for obj in scene_layer.objects:
                unselected = SELECT and not obj.select_get()
                if not unselected and obj.type not in objectStudio and obj.parent is None:
                    vcls = obj.get("Classing")
                    obj_typ = obj.get("MVR Type")
                    obj_cls = obj.get("MVR Class")
                    classes = set((obj_typ, obj_cls))
                    xml_cls = getattr(pymvr, obj_cls, "SceneObject")
                    obj_name = obj.get("MVR Name") if obj.get("MVR Name") else remove_layer_tag(obj)
                    print("creating SceneObject... %s" % obj_name)
                    if obj.data is None and "Symbol" in classes:
                        meshes = mesh_list.symbol
                        mesh_name = obj_name
                        mvr_object, mvr_matrix = export_symbol(obj)
                    elif obj.type in objectStudio:
                        studio_list.append(obj)
                    else:
                        meshes = mesh_list.geometry3d
                        mesh_name = ".".join((obj.data.name if obj.data else obj_name, "3ds"))
                        mvr_object, mvr_matrix = export_geometry(obj, mesh_name, file_list)
                    scene_object = xml_cls(name=obj_name, matrix=mvr_matrix, classing=vcls).to_xml()
                    meshes.append(mvr_object)
                    mesh_list.to_xml(parent=scene_object)
                    child_list.append(scene_object)
                    meshes.clear()
        elif col_cls is not None:
            viewcls = scene_layer.get("Classing")
            col_name = remove_layer_tag(scene_layer)
            xml_cls = getattr(pymvr, col_cls, "SceneObject")
            for obj in scene_layer.objects:
                if not (SELECT and not obj.select_get()) and obj.parent is None:
                    obj_typ = obj.get("MVR Type")
                    obj_cls = obj.get("MVR Class")
                    print("creating %s... %s" % (col_cls, obj.name))
                    classes = set((obj_typ, obj_cls))
                    if obj_typ == "Geometry3D":
                        meshes = mesh_list.geometry3d
                        mesh_name = ".".join((obj.data.name if obj.data else obj.name, "3ds"))
                        mvr_object, mvr_matrix = export_geometry(obj, mesh_name, file_list)
                    elif obj.data is None and "Symbol" in classes:
                        meshes = mesh_list.symbol
                        mvr_object, mvr_matrix = export_symbol(obj)
                    meshes.append(mvr_object)
            scene_object = xml_cls(name=col_name, uuid=col_uid, matrix=mvr_matrix, classing=viewcls).to_xml()
            mesh_list.to_xml(parent=scene_object)
            child_list.append(scene_object)
            meshes.clear()
        else:
            print("creating SceneObject... %s" % scene_layer.name)
            mesh_name = ".".join((scene_layer.name, "3ds"))
            mvr_object, mvr_matrix = export_geometry(scene_layer, mesh_name, file_list)
            scene_object = pymvr.SceneObject(name=scene_layer.name, matrix=mvr_matrix).to_xml()
            mesh_list.geometry3d.append(mvr_object)
            mesh_list.to_xml(parent=scene_object)
            child_list.append(scene_object)
            mesh_list.geometry3d.clear()
            mesh_list.symbol.clear()

        return child_list, file_list


    def export_collection(item, mvr_node, mvr_cls, mvr_list, file_list, single=True):
        item_name = item.get("MVR Name") if item.get("MVR Name") else item.name
        item_cls = item.get("MVR Class")
        item_typ = item.get("MVR Type")
        item_uid = item.get("UUID")
        if item.objects:
            if item_cls in objectMVR or item_typ == "Symbol":
                mvr_list, file_list = create_scene_object(item, mvr_list, file_list)
            else:
                mvr_list, file_list = create_scene_object(item, mvr_list, file_list, single)
                if any((ob.type in objectStudio for ob in item.objects)):
                    mvr_list, file_list = create_studio_object(item_name, mvr_list, file_list)
        for cld in item.children:
            cld_typ = cld.get("MVR Type")
            cld_cls = cld.get("MVR Class")
            cld_name = cld.get("MVR Name") if cld.get("MVR Name") else cld.name
            if (cld_cls == "AUXData") or (cld_name == "AUXData"):
                continue
            cld_uid = cld.get("UUID")
            is_fixture = cld.get("Company")
            if FIXTURES and cld_uid and is_fixture:
                export_fixture(cld, cld_name, mvr_list, file_list)
            elif not is_fixture:
                if cld.children or mvr_list is None or any((ob.is_instancer for ob in cld.objects)):
                    if cld_cls not in objectMVR and mvr_cls == "Layers" or cld_cls == "Layer":
                        mvr_node, mvr_cls, mvr_list = create_layer(item_name, layers, layers_cls, cld_uid)
                    elif cld_cls not in objectMVR and mvr_cls == "Layer" or cld_cls == "GroupObject":
                        mvr_node, mvr_cls, mvr_list = create_layer(item_name, mvr_node, mvr_cls, cld_uid, mvr_list)
                    print("exporting %s... %s" % (mvr_cls, item_name))
                if cld.objects and not cld.children:
                    export_collection(cld, mvr_node, mvr_cls, mvr_list, file_list, True)
                else:
                    export_collection(cld, mvr_node, mvr_cls, mvr_list, file_list, False)


    def collect_layers(collect, node, nd_cls, layer_list, file_list):
        layer = node
        layer_cls = nd_cls
        collect_uid = collect.get("UUID")
        is_profile = collect.get("Company")
        collect_cls = collect.get("MVR Class")
        collect_name = collect.get("MVR Name") if collect.get("MVR Name") else collect.name
        if collect.objects:
            layer_list, file_list = create_scene_object(collect, layer_list, file_list)
        for col in collect.children:
            col_uid = col.get("UUID")
            col_cls = col.get("MVR Class")
            is_gdtf = col.get("Company")
            col_name = col.get("MVR Name") if col.get("MVR Name") else col.name
            if (col_cls == "AUXData") or (col_name == "AUXData"):
                continue
            if FIXTURES and col_uid and is_gdtf:
                export_fixture(col, col_name, layer_list, file_list)
            elif not is_gdtf:
                if len(collect.children) == 1 and not col.objects:
                    collect_layers(col, node, nd_cls, layer_list, file_list)
                layer, layer_cls, layer_list = create_layer(col_name, layers, layers_cls, col_uid)
                print("exporting %s... %s" % (layer_cls, col_name))
                export_collection(col, layer, layer_cls, layer_list, file_list)


    items_uid = items.get("UUID")
    is_profile = items.get("Company")
    items_class = items.get("MVR Class")
    aux_collection = bpy.data.collections.get("AUXData")
    print("creating %s... %s" % (layers_cls, scene_name))
    no_objects = len(items.children) == 1 and not items.objects
    items_name = items.get("MVR Name") if items.get("MVR Name") else items.name
    is_layers = items.name in scene_collection.children and len(scene_collection.children) == 1
    if aux_collection:
        classData = aux_collection.get("View Classes")
    print("getting Collections... %s" % scene_name)

    if items_uid:
        if FIXTURES and is_profile:
            export_fixture(items, items_name, layer_list, file_list)
        elif items.children or items.objects:
            print("exporting Layer... %s" % items_name)
            export_collection(items, layers, layers_cls, layer_list, file_list)
    elif is_layers or no_objects or items == scene_collection:
        print("exporting Layers... %s" % items_name)
        collect_layers(items, layers, layers_cls, layer_list, file_list)
    elif items.objects or items.children:
        layer, layer_cls, layer_list = create_layer(items_name, layers, layers_cls)
        print("exporting Layer... %s" % items_name)
        export_collection(items, layers, layers_cls, layer_list, file_list)

    if aux_collection:
        print("exporting AUXData...")
        if classData is not None:
            for cuid, clsname in classData.items():
                viewclass = pymvr.Class(uuid=cuid, name=clsname).to_xml()
                auxdata.classes.append(viewclass)
        scale_vec = mathutils.Vector.Fill(3, scalefactor)
        for child in aux_collection.children:
            symdef_uid = child.get("UUID")
            print("creating Symdef... %s" % child.name)
            symdef = pymvr.Symdef(uuid=symdef_uid, name=child.name).to_xml()
            symlist = pymvr.ChildList().to_xml(parent=symdef)
            for geo in child.children:
                if geo.objects:
                    consize = file_path = None
                    conscale = CONVERSE.to_scale()
                    geo_name = geo.name
                    for ob in geo.objects:
                        if ob.data:
                            trans = ob.data.get("Transform")
                            geo_name = ob.data.get("Reference")
                            if geo_name is None:
                                geo_name = ob.data.name
                            if trans:
                                consize = mathutils.Vector((trans[0], trans[4], trans[8]))
                            elif consize is None:
                                consize = ob.matrix_world.copy().to_scale() 
                            geo_path = get_filepath(geo_name, asset_path)
                            if file_path is None and geo_path is not None:
                                file_path = geo_path
                            if consize is not None:
                                conscale = consize
                            file_list.extend(get_material_images(ob.active_material, folder_path))
                    convertscale = sum(conscale * scale_vec) / 3
                    print("exporting Geometry3D... %s" % geo_name)
                    if file_path is None:
                        mesh_name = ".".join((geo_name, "3ds"))
                        file_path = os.path.join(folder_path, mesh_name)
                        export_3ds(context, file_path, geo.all_objects, SELECT,
                                   APPLY_MATRIX, CONVERSE, convertscale, geo_name)
                    mvr_object = pymvr.Geometry3D(file_name=geo_name).to_xml()
                    file_list.append((file_path, geo_name))
                    symlist.append(mvr_object)
                else:
                    print("exporting Symbol... %s" % geo.name)
            auxdata.symdefs.append(symdef)

    auxdata.to_xml(parent=scene)
    cleanup_xml(scene)
    mvr.files_list = list(set(file_list))
    mvr.write_mvr(filename)
    file_size = Path(filename).stat().st_size
    auxdata.classes.clear()
    auxdata.symdefs.clear()

    return scene, file_list


def save_mvr(context, items, filename, fixturepath="", scale_factor=1.0,
             APPLY_MATRIX=False, SELECT=False, IMAGES=True, FIXTURES=True,
             TARGETS=True, CONVERSE=mathutils.Matrix(), VERSION=""):
    """Create the .mvr file."""

    start_time = time.time()
    scalefactor = scale_factor * 1000
    current_path = os.path.dirname(os.path.realpath(__file__))
    asset_path = os.path.join(current_path, "assets", "mvr")
    folder_path = os.path.join(asset_path, Path(filename).stem)
    Path(folder_path).mkdir(parents=True, exist_ok=True)

    try:
        scene, file_list = export_mvr(context, items, filename, fixturepath, folder_path,
                                      asset_path, scalefactor, SELECT, IMAGES, FIXTURES,
                                      TARGETS, CONVERSE, APPLY_MATRIX, VERSION)
    except Exception as exc:
        print(exc)

    if os.path.isdir(folder_path):
        [fl.unlink() for fl in Path(folder_path).iterdir() if fl.is_file()]
        Path(folder_path).rmdir()

    print("MVR scene exported in %.4f sec.\n" % (time.time() - start_time))


def save(operator, context, filepath="", collection="", scale_factor=1.0, use_selection=False,
         use_apply_transform=False, use_images=True, use_collection=False, use_fixtures=True,
         use_targets=True, fixture_path="", global_matrix=None, version=""):
    """Save the MVR file."""

    if global_matrix is None:
        global_matrix = mathutils.Matrix()

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

    save_mvr(context, items, filepath, fixture_path, scale_factor, APPLY_MATRIX=use_apply_transform, SELECT=use_selection,
             IMAGES=use_images, FIXTURES=use_fixtures, TARGETS=use_targets, CONVERSE=global_matrix, VERSION=version)

    return {'FINISHED'}
