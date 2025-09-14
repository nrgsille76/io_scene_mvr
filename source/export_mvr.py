# SPDX-FileCopyrightText: 2025 Sebastian Schrand
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Export is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import time
import pymvr
import traceback
import mathutils
import bpy_extras
import uuid as pyuid
from pathlib import Path
from bpy_extras import node_shader_utils
from io_scene_3ds.export_3ds import save_3ds


mixType = {'MIX', 'MIX_RGB'}
objectStudio = {'LIGHT', 'CAMERA'}
objectGeometry = {'MESH', 'EMPTY'}
layerMVR = {"Layer", "GroupObject"}
objectMVR = {"SceneObject", "Truss", "Support", "Projector", "VideoScreen"}
nodeMVR = {"GroupObject"}.union(objectMVR)


def isFixture(col):
    """Check if it is a fixture collection."""
    is_profile = col.get("Company")
    is_fixture = bool(is_profile)
    if is_profile is None and any(
        (ob.get("geometry_type") for ob in col.objects)
    ):
        is_fixture = True

    return is_fixture


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


def drop_suffix(name):
    """Drop suffix string."""
    if name is None:
        return ""
    split_name = name.split()
    splen = len(split_name)
    final_name = split_name[0]
    if splen > 2:
        if splen > 3 and split_name[-1].isdigit() and split_name[-2].isdigit():
            final_name = " ".join(split_name[:-2])
        else:
            final_name = " ".join(split_name[:-1])

    return final_name


def remove_layer_tag(name):
    """Remove a layer tag."""
    item_name = name
    if len(name) >=3 and " " in name:
        check_space = name[2] == " " or name[2].isdigit()
        check_name = name[0] == "L" and name[1].isdigit()
        if check_name and check_space:
            split_name = name.split()
            splen = len(split_name)
            if splen >= 2:
                if split_name[-1].isdigit():
                    if splen >= 3 and split_name[-2].isdigit():
                        item_name = " ".join(split_name[1:-2])
                    else:
                        item_name = " ".join(split_name[1:-1])
                else:
                    item_name = " ".join(split_name[1:])
            elif split_len == 2:
                item_name = split_name[1]

    return item_name


def get_mvr_name(item):
    """Get the MVR object name."""
    item_name = item.get("MVR Name")
    if item_name is not None:
        mvr_name = remove_layer_tag(item_name)
    else:
        mvr_name = remove_layer_tag(item.name)

    return mvr_name


def export_3ds(context, path, objects, SELECT, APPLY_MATRIX, CONVERSE, scale=1000.0, collection="", studio=None):
    """Export Autodesk 3DStudio (.3ds) files."""
    save_3ds(context, path, collection, objects, scale, CONVERSE, SELECT, APPLY_MATRIX, studio, True)


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


def get_material_images(material, path):
    """Collect material textures."""
    images = []

    def get_image(image):
        if image:
            img_name = Path(image.filepath).name
            file_path = os.path.join(path, img_name)
            if not os.path.isfile(file_path):
                image.save(filepath=file_path)
                images.append((file_path, img_name))

    if (material and material.node_tree and not
        (material.get("Geometry Type") == "Gobo")
    ):
        links = material.node_tree.links
        mtex = [lk.from_node for lk in links
                if lk.from_node.type == 'TEX_IMAGE'
                and lk.to_node.type in mixType]

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


def create_layer(layername, node, node_cls, uid=None, parents=[]):
    """Create a xml layer or group."""
    if node_cls is None or node_cls == "Layers":
        layer = pymvr.Layer(name=layername, uuid=uid)
        layer_node = layer
        node.append(layer)
    else:
        group = pymvr.GroupObject(name=layername, uuid=uid)
        layer_node = group
        parents.group_objects.append(group)
    layer_list = pymvr.ChildList()
    layer_node.child_list = layer_list
    layer_cls = layer_node.__class__.__name__

    return layer_node, layer_cls, layer_list


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


def get_fixture(context, fixture, specs, file_list, folders, scale, SELECT, TARGETS, CONVERSE, APPLY_MATRIX):
    """Collect fixtures and focuspoints."""
    patch_numbers = []
    focus_point = None
    uid = fixture.get("UUID")
    fixture_name = fixture.get("Fixture Name")
    props = ["Patch Break", "Patch Universe", "Patch Address"]
    base = next((ob for ob in fixture.objects if ob.get("Use Root")), None)
    target = next((ob for ob in fixture.objects if ob.get("Geometry Type") == "Target"), None)
    trs_mtx = pymvr.Matrix(get_transmatrix(CONVERSE, base))
    fix_mode = base.get("Fixture Mode")
    fix_id = fixture.get("Fixture ID")

    if target and TARGETS:
        focus_objects = []
        geometries = pymvr.Geometries()
        target_uid = target.get("UUID")
        factor = mathutils.Vector.Fill(3)
        target_name = target.get("Fixture Name")
        focus_name = target_name + " FocusPoint"
        scale_vec = mathutils.Vector.Fill(3, scale)
        focus_mtx = pymvr.Matrix(get_transmatrix(CONVERSE, target))
        print("exporting FocusPoint... %s" % focus_name)
        if target.children and any((ob.type == 'MESH' for ob in target.children_recursive)):
            target_mesh = ".".join((" ".join((target_name, "Target")), "3ds"))
            for obj in target.children_recursive:
                if obj.parent == target:
                    target_mtx = obj.matrix_parent_inverse.copy() @ target.matrix_local.copy()
                    focus_mtx = pymvr.Matrix(get_transmatrix(target_mtx, obj))
                if obj.type == 'MESH':
                    file_list.extend(get_material_images(obj.active_material, folders))
                if obj.get("Geometry Class") != "Target":
                    factor += obj.matrix_world.copy().to_scale()
                    focus_objects.append(obj)
        focus_point = pymvr.FocusPoint(uuid=target_uid, name=focus_name, matrix=focus_mtx)
        if len(focus_objects):
            print("adding Geometry3D... %s" % target_mesh)
            quantity = mathutils.Vector.Fill(3, len(focus_objects))
            size = mathutils.Vector(tuple(factor[i] / quantity[i] for i in range(3)))
            geometry = pymvr.Geometry3D(file_name=target_mesh)
            factorsize = sum(size * scale_vec) / 3
            geometries.geometry3d.append(geometry)
            file_path = os.path.join(folders, target_mesh)
            export_3ds(context, file_path, focus_objects, SELECT, APPLY_MATRIX, CONVERSE, factorsize)
            file_list.append((file_path, target_mesh))
            focus_point.geometries = geometries
        fix_object = pymvr.Fixture(name=fixture_name, uuid=uid, gdtf_spec=specs, gdtf_mode=fix_mode, matrix=trs_mtx,
                                   fixture_id=str(fix_id), fixture_id_numeric=fix_id, focus=target_uid)
    else:
        fix_object = pymvr.Fixture(name=fixture_name, uuid=uid, gdtf_spec=specs, gdtf_mode=fix_mode,
                                   matrix=trs_mtx, fixture_id=str(fix_id), fixture_id_numeric=fix_id)

    for prop in props:
        patch_numbers.append(fixture.get(prop) if fixture.get(prop) is not None else 0)

    patch = pymvr.Address(dmx_break=patch_numbers[0], universe=patch_numbers[1], address=patch_numbers[2])
    fix_object.addresses = pymvr.Addresses(address=[patch])
    patch_numbers.clear()

    if base and base.get("RGB Beam") is not None:
        color_xy = convert_rgb(base.get("RGB Beam"))
    elif base and base.get("RGB Glow") is not None:
        color_xy = convert_rgb(base.get("RGB Glow"))
    else:
        color_xy = convert_rgb((1.0, 1.0, 1.0))
    fix_object.color = pymvr.Color(x=color_xy[0], y=color_xy[1], Y=color_xy[2])

    return file_list, fix_object, focus_point      


def export_mvr(context, items, filename, fixturepath, folder_path, asset_path, scalefactor,
               SELECT, IMAGES, FIXTURES, TARGETS, CONVERSE, APPLY_MATRIX, VERSION):
    """Export MVR xml tree."""
    data_collections = bpy.data.collections
    scene_collection = context.scene.collection
    blend_file = Path(bpy.data.filepath).stem
    layers_name = Path(filename).stem
    scene_name = context.scene.name
    classData = None
    file_list = []
    sym_defs = {}

    print("\ncreating Scene... %s" % blend_file)
    mvr = pymvr.GeneralSceneDescriptionWriter()
    scene = pymvr.Scene()
    layers = pymvr.Layers()
    layers_cls = layers.__class__.__name__
    scale_vec = mathutils.Vector.Fill(3, scalefactor)
    scene.layers = layers
    auxdata = pymvr.AUXData()
    user_data = pymvr.UserData()
    user_data.data = [pymvr.Data(provider="NRGSille", ver=VERSION)]
    print("collecting Elements... %s" % layers_name)


    def export_fixture(profile, childlist, filelist):
        print("exporting Fixture... %s" % profile.name)
        gdtf_name = profile.get("GDTF Spec")
        if gdtf_name is None:
            gdtf_name = drop_suffix(profile.name)
        gdtf_spec = get_gdtf_name(gdtf_name)
        profile_path = get_filepath(gdtf_spec, asset_path, True)
        if fixturepath and profile_path is None:
            profile_path = get_filepath(gdtf_spec, fixturepath, True)
        filelist, fix_object, focus_point = get_fixture(context, profile, gdtf_name,
                                                        filelist, folder_path, scalefactor,
                                                        SELECT, TARGETS, CONVERSE, APPLY_MATRIX)
        if profile_path:
            filelist.append((profile_path, Path(profile_path).name))
        childlist.fixtures.append(fix_object)
        if focus_point:
            childlist.focus_points.append(focus_point)

        return childlist, filelist


    def create_studio_object(studiolayer, child_list, filelist, studiolist=[]):
        if "3DStudio" in studiolayer:
            studiolayer = drop_suffix(studiolayer)
        studio_name = " ".join((studiolayer, "3DStudio"))
        studio_file = ".".join((studio_name, "3ds"))
        transmtx = pymvr.Matrix(get_transmatrix(CONVERSE))
        stuff = pymvr.Geometry3D(file_name=studio_file)
        print("adding Geometry3D... %s" % studio_file)
        file_path = os.path.join(folder_path, studio_file)
        scene_object = pymvr.SceneObject(name=studio_name, matrix=transmtx)
        export_3ds(context, file_path, studiolist, SELECT, APPLY_MATRIX,
                   CONVERSE, scalefactor, studiolayer, objectStudio)
        filelist.append((file_path, studio_file))
        stuff_list = pymvr.Geometries()
        stuff_list.geometry3d.append(stuff)
        scene_object.geometries = stuff_list
        child_list.scene_objects.append(scene_object)

        return child_list, filelist


    def create_symdef(collect, symdef_uid, filelist):
        sym_list = pymvr.SymdefChildList()
        geometry_name = collect.name
        consize = scalefactor
        path_list = filelist

        def collect_objects(geometry):
            geo_name = geometry.name
            meshsize = meshpath = None
            conscale = CONVERSE.to_scale()
            for obj in geometry.objects:
                if obj.parent is None:
                    trs_mtx = obj.data.get("Transform") if ob.data else obj.get("Transform")
                    geo_name = obj.data.get("Reference") if ob.data else obj.get("Reference")
                    if geo_name is None:
                        geo_name = obj.data.name
                    if trs_mtx:
                        meshsize = mathutils.Vector((trs_mtx[0], trs_mtx[4], trs_mtx[8]))
                    elif meshsize is None:
                        meshsize = obj.matrix_world.copy().to_scale() 
                    geo_path = get_filepath(geo_name, asset_path)
                    if meshpath is None and geo_path is not None:
                        meshpath = geo_path
                    if meshsize is not None:
                        conscale = meshsize
                    filelist.extend(get_material_images(obj.active_material, folder_path))

            return geo_name, conscale, meshpath

        def export_symdef(geo, name, size, path, pathlist):
            convertscale = sum(size * scale_vec) / 3
            mesh_name = name if name.endswith(".3ds") else f"{name}.3ds"
            print("adding Geometry3D... %s" % mesh_name)
            if path is None:
                path = os.path.join(folder_path, mesh_name)
                export_3ds(context, path, geo.all_objects, SELECT,
                           APPLY_MATRIX, CONVERSE, convertscale, geo.name)
            geometry = pymvr.Geometry3D(file_name=mesh_name)
            sym_list.geometry3d.append(geometry)
            pathlist.append((path, mesh_name))

            return pathlist

        if collect.children:
            for geo in collect.children:
                if geo.objects:
                    geometry_name, consize, file_path = collect_objects(geo)
                    path_list = export_symdef(geo, geometry_name, consize, file_path, filelist)
        elif collect.objects:
            geometry_name, consize, file_path = collect_objects(collect)
            path_list = export_symdef(collect, geometry_name, consize, file_path, filelist)
        sym_def = pymvr.Symdef(uuid=symdef_uid, name=geometry_name)
        sym_def.child_list = sym_list

        return sym_def, path_list


    def export_symbol(sym):
        insta = sym.instance_collection
        sym_ref = sym.get("Reference")
        sym_uid = insta.get("Reference")
        transform = sym.get("Transform")
        symbol_name = get_mvr_name(sym)
        if sym_uid is None:
            sym_uid = str(pyuid.uuid4())
        if sym_ref is None:
            sym_ref = sym_defs.get(insta.name)
        if transform is None:
            transmtx = pymvr.Matrix(get_transmatrix(CONVERSE, sym))
        else:
            transmtx = pymvr.Matrix(get_transmatrix(transform))
        print("adding Symbol... %s" % symbol_name)
        symbol = pymvr.Symbol(uuid=sym_uid, symdef=sym_ref)

        return symbol, transmtx


    def export_geometry(scene_obj, obj_name, filelist):
        class_name = scene_obj.__class__.__name__
        print("adding Geometry3D... %s" % obj_name)
        file_path = os.path.join(folder_path, obj_name)
        filelist.append((file_path, obj_name))
        transmtx = pymvr.Matrix(get_transmatrix(CONVERSE))
        geometry = pymvr.Geometry3D(file_name=obj_name)
        clsing = obj_class = None
        if class_name == "Collection":
            obj_mtx = scene_obj.get("Transform")
            obj_class = scene_obj.get("MVR Class")
            average = CONVERSE.to_translation()
            consize = mathutils.Vector.Fill(3)
            for ob in scene_obj.objects:
                if IMAGES and not (SELECT and not ob.select_get()):
                    filelist.extend(get_material_images(ob.active_material, folder_path))
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
                transmtx = pymvr.Matrix(get_transmatrix(obj_mtx))
            elif not APPLY_MATRIX:
                amount = mathutils.Vector.Fill(3, len(scene_obj.objects))
                scale = mathutils.Vector(tuple(consize[i] / amount[i] for i in range(3)))
                vector = tuple(average[i] / amount[i] for i in range(3))
                translate = mathutils.Matrix.Translation(vector)
                transmtx = pymvr.Matrix(get_transmatrix(translate))
            convertscale = sum(scale * scale_vec) / 3
            export_3ds(context, file_path, scene_obj.all_objects, SELECT,
                       APPLY_MATRIX, CONVERSE, convertscale, scene_obj.name)
        elif class_name == "Object":
            object_list = [scene_obj]
            if IMAGES:
                filelist.extend(get_material_images(scene_obj.active_material, folder_path))
            for child in scene_obj.children_recursive:
                object_list.append(child)
                if IMAGES:
                    filelist.extend(get_material_images(child.active_material, folder_path))
            mtx = scene_obj.get("Transform")
            if mtx:
                transmtx = pymvr.Matrix(get_transmatrix(mtx))
            elif not APPLY_MATRIX:
                transmtx = pymvr.Matrix(get_transmatrix(CONVERSE, scene_obj))
            convertscale = sum(scene_obj.matrix_world.to_scale() * scale_vec) / 3
            export_3ds(context, file_path, object_list, SELECT,
                       APPLY_MATRIX, CONVERSE, convertscale)

        return geometry, transmtx, filelist


    def create_scene_object(collect, grouplist, filelist, single=False):
        grp_uid = collect.get("UUID")
        vcls = collect.get("Classing")
        grp_name = get_mvr_name(collect)
        grp_cls = collect.get("MVR Class")

        def create_geometry(meshcol, meshlist, files, xmlcls):
            geo_cls = xmlcls.__name__
            print("creating %s... %s" % (geo_cls, grp_name))
            if all((ob.type in objectStudio for ob in meshcol.objects)):
                meshlist, files = create_studio_object(grp_name, meshlist, files)
            else:
                meshes = pymvr.Geometries()
                mesh_mtx = meshcol.get("Transform")
                mtx = pymvr.Matrix(get_transmatrix(CONVERSE))
                if mesh_mtx is not None:
                    mtx = pymvr.Matrix(get_transmatrix(mesh_mtx))
                for mesh in meshcol.objects:
                    unselected = SELECT and not geo.select_get()
                    if not unselected and mesh.type not in objectStudio and mesh.parent is None:
                        if mesh.type in objectGeometry and not mesh.is_instancer:
                            mesh_name = get_mvr_name(mesh)
                            filename = ".".join((mesh.data.name if mesh.data else mesh_name, "3ds"))
                            geometry, mtx, filelist = export_geometry(mesh, filename, files)
                            meshes.geometry3d.append(geometry)
                scene_object = xmlcls(name=grp_name, uuid=grp_uid, matrix=mtx, classing=vcls)
                scene_object.geometries = meshes
                meshlist.scene_objects.append(scene_object)

        def create_symbol(symcol, instalist, files, xmlcls):
            sym_cls = xmlcls.__name__
            for insta in symcol.objects:
                unselected = SELECT and not obj.select_get()
                if not unselected and insta.type not in objectStudio and insta.parent is None:
                    instances = pymvr.Geometries()
                    insta_name = get_mvr_name(insta)
                    print("creating %s... %s" % (sym_cls, insta_name))
                    if insta.is_instancer and insta.data is None:
                        symbol, mtx = export_symbol(insta)
                        instances.symbol.append(symbol)
                    else:
                        filename = ".".join((insta.data.name if insta.data else insta_name, "3ds"))
                        geometry, mtx, filelist = export_geometry(insta, filename, files)
                        instances.geometry3d.append(geometry)
                    scene_object = xmlcls(name=insta_name, uuid=grp_uid, matrix=mtx, classing=vcls)
                    scene_object.geometries = instances
                    instalist.scene_objects.append(scene_object)

        if bool(collect.objects):
            if grp_cls is not None:
                obj_cls = "SceneObject"
                xml_cls = pymvr.SceneObject
                scene_mtx = collect.get("Transform")
                mvr_matrix = pymvr.Matrix(get_transmatrix(CONVERSE))
                obj_name = next((ob.get("MVR Name") for ob in collect.objects), grp_name)
                col_name = grp_name if grp_cls in objectMVR else obj_name
                if scene_mtx is not None:
                    mvr_matrix = pymvr.Matrix(get_transmatrix(scene_mtx))
                    obj_cls = next((ob.get("MVR Class") for ob in collect.objects
                                    if ob.get("MVR Class")), "SceneObject")
                    xml_cls = getattr(pymvr, obj_cls, "SceneObject")
                if bool(collect.children) or any((ob.is_instancer for ob in collect.objects)):
                    create_symbol(collect, grouplist, filelist, xml_cls)
                else:
                    create_geometry(collect, grouplist, filelist, xml_cls)
            elif single:
                if any((ob.type in objectStudio for ob in collect.objects)):
                    print("creating 3DStudio... %s" % grp_name)
                    grouplist, filelist = create_studio_object(grp_name, grouplist, filelist)
                for obj in collect.objects:
                    unselected = SELECT and not obj.select_get()
                    if not unselected and obj.type not in objectStudio and obj.parent is None:
                        lay_cls = "SceneObject"
                        xml_cls = pymvr.SceneObject
                        obj_name = get_mvr_name(obj)
                        obj_cls = obj.get("MVR Class")
                        if obj_cls in objectMVR:
                            xml_cls = getattr(pymvr, obj_cls, lay_cls)
                            lay_cls = obj_cls
                        geometries = pymvr.Geometries()
                        print("creating %s... %s" % (lay_cls, obj_name))
                        if obj.is_instancer and obj.instance_collection and obj.data is None:
                            symbol, mvr_matrix = export_symbol(obj)
                            geometries.symbol.append(symbol)
                        else:
                            mesh_name = ".".join((obj.data.name if obj.data else obj_name, "3ds"))
                            geometry, mvr_matrix, filelist = export_geometry(obj, mesh_name, filelist)
                            geometries.geometry3d.append(geometry)
                        scene_object = xml_cls(name=obj_name, matrix=mvr_matrix)
                        scene_object.geometries = geometries
                        grouplist.scene_objects.append(scene_object)
            else:
                print("creating SceneObject... %s" % collect.name)
                geometries = pymvr.Geometries()
                mesh_name = ".".join((collect.name, "3ds"))
                mvr_object, mvr_matrix, filelist = export_geometry(collect, mesh_name, filelist)
                scene_object = pymvr.SceneObject(name=collect.name, matrix=mvr_matrix)
                geometries.geometry3d.append(mvr_object)
                scene_object.geometries = geometries
                grouplist.scene_objects.append(scene_object)

        return grouplist, filelist


    def export_collection(item, layer, lay_cls, laylist, filelist, single=False):
        if bool(item.objects):
            if item.get("MVR Class"):
                laylist, filelist = create_scene_object(item, laylist, filelist)
            else:
                laylist, filelist = create_scene_object(item, laylist, filelist, single)
        for child in item.children:
            cld_uid = child.get("UUID")
            childname = get_mvr_name(child)
            cldtype = child.get("MVR Type")
            cld_cls = child.get("MVR Class")
            if "AUXData" in (cld_cls, childname) or child.name in sym_defs.keys():
                continue
            if FIXTURES and cld_uid and isFixture(child):
                laylist, filelist = export_fixture(child, laylist, filelist)
            elif not isFixture(child):
                if lay_cls in layerMVR and bool(child.children) or any((ob.is_instancer for ob in child.objects)):
                    group, grp_cls, grplist = create_layer(childname, layer, lay_cls, cld_uid, laylist)
                    print("exporting %s... %s" % (grp_cls, childname))
                    export_collection(child, group, grp_cls, grplist, filelist)
                elif child.objects and not child.children:
                    export_collection(child, layer, lay_cls, laylist, filelist, True)
                else:
                    export_collection(child, layer, lay_cls, laylist, filelist)


    def collect_layers(laycols, node, node_cls, filelist):
        laycols_name = get_mvr_name(laycols)
        for laycol in laycols.children:
            laycol_name = get_mvr_name(laycol)
            laycol_cls = laycol.get("MVR Class")
            if "AUXData" in (laycol_cls, laycol_name) or laycol.name in sym_defs.keys():
                continue
            laycol_uid = laycol.get("UUID")
            if len(laycols.children) == 1 and not laycol.objects:
                print("exporting Layers... %s" % laycol_name)
                collect_layers(laycol, node, node_cls, filelist)
            else:
                layer, layer_cls, layerlist = create_layer(laycol_name, node, node_cls, laycol_uid)
                print("exporting %s... %s" % (layer_cls, laycol_name))
                export_collection(laycol, layer, layer_cls, layerlist, filelist, True)


    items_uid = items.get("UUID")
    items_name = get_mvr_name(items)
    items_class = items.get("MVR Class")
    aux_collection = bpy.data.collections.get("AUXData")
    print("creating %s... %s" % (layers_cls, scene_name))
    no_objects = len(items.children) == 1 and not items.objects
    is_layers = items.name in scene_collection.children and len(scene_collection.children) == 1
    if aux_collection:
        classData = aux_collection.get("View Classes")
    print("getting Collections... %s" % scene_name)
    for obj in items.all_objects:
        if obj.is_instancer and not obj.get("UUID"):
            instance_name = obj.instance_collection.name
            if instance_name not in sym_defs.keys():
                sym_defs.setdefault(instance_name, str(pyuid.uuid4()))

    if items_uid:
        layer, layer_cls, layer_list = create_layer(items_name, layers, layers_cls, items_uid)
        if FIXTURES and isFixture(items):
            layer_list, file_list = export_fixture(items, layer_list, file_list)
        elif items.children or items.objects:
            export_collection(items, layer, layer_cls, layer_list, file_list)
    elif is_layers or no_objects or items == scene_collection:
        print("exporting Layers... %s" % items_name)
        collect_layers(items, layers, layers_cls, file_list)
    elif items.objects or items.children and items != aux_collection:
        layer, layer_cls, layer_list = create_layer(items_name, layers, layers_cls)
        print("exporting %s... %s" % (layer_cls, items_name))
        export_collection(items, layers, layers_cls, layer_list, file_list)

    if aux_collection or sym_defs.items():
        print("exporting AUXData...")
        if classData is not None:
            for cuid, clsname in classData.items():
                viewclass = pymvr.Class(uuid=cuid, name=clsname)
                auxdata.classes.append(viewclass)
        if aux_collection is not None:
            for child in aux_collection.children:
                symdef_uid = child.get("UUID")
                print("creating Symdef... %s" % child.name)
                symdef, file_list = create_symdef(child, symdef_uid, file_list)
                auxdata.symdefs.append(symdef)
        for colname, reference in sym_defs.items():
            sym_collect = data_collections.get(colname)
            if sym_collect:
                print("creating Symdef... %s" % colname)
                symdef, file_list = create_symdef(sym_collect, reference, file_list)
                auxdata.symdefs.append(symdef)

    scene.aux_data = auxdata
    user_data.to_xml(parent=mvr.xml_root)
    scene.to_xml(parent=mvr.xml_root)
    mvr.files_list = list(set(file_list))
    mvr.write_mvr(filename)
    file_size = Path(filename).stat().st_size
    auxdata.classes.clear()
    auxdata.symdefs.clear()
    sym_defs.clear()

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
        traceback.print_exception(exc)


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

    viewlayer = context.view_layer
    items = viewlayer.layer_collection.collection

    if use_collection:
        items = viewlayer.active_layer_collection.collection
    elif collection:
        item_collection = bpy.data.collections.get(collection)
        if item_collection:
            items = item_collection

    save_mvr(context, items, filepath, fixture_path, scale_factor, APPLY_MATRIX=use_apply_transform, SELECT=use_selection,
             IMAGES=use_images, FIXTURES=use_fixtures, TARGETS=use_targets, CONVERSE=global_matrix, VERSION=version)

    return {'FINISHED'}
