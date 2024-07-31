# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#                         2020 Hugo Aboud
#                         2020 Vanous
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Import is based on using information from BlenderDMX source-code
# (https://github.com/open-stage/blender-dmx)


import os
import bpy
import copy
import math
import pygdtf
import random
import mathutils
import uuid as pyuid
from types import SimpleNamespace
from io_scene_3ds.import_3ds import load_3ds
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from pathlib import Path

targetData = {}
channelData = {}


class FixtureMode(object):

    def __init__(self, profile):
        self._name = next((md.name for md in profile.dmx_modes if
                           md.name.split(' ')[0] == 'Standard'), 'Standard')

    @property
    def name(self):
        return self._name

    def __str__(self):
        return f"{self.name}"


def get_folder_path():
    folder_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(folder_path, "fixture_profiles")


def get_profile_list(directory):
    profiles = []
    for file in os.listdir(directory):
        if "@" not in file:
            file = os.path.join(directory, file)
            fixture_type = pygdtf.FixtureType(file)
            info = [f"{fixture_type.manufacturer}", f"{fixture_type.long_name}", ""]
        else:
            info = file.split("@")
    return tuple(profiles)


def cleanup_name(geometry):
    name = geometry.name.replace(" ", "_")
    root_name = ""
    if hasattr(geometry, "reference_root"):
        root_name = f"{geometry.reference_root.replace(' ', '_')}_"
    return f"{root_name}{name}"


def create_fixture_name(name):
    if '@' not in name:
        return name
    split_name = name.split('@')
    if len(split_name) >= 1:
        manufacturer = split_name[0]
        fixture_name = split_name[1]
        clean_name = manufacturer + ' ' + fixture_name
    else:
        clean_name = split_name[0]
    return clean_name


def create_transform_property(obj):
    mtx_copy = obj.matrix_basis.copy()
    translate = mtx_copy.to_translation()
    rotate = mtx_copy.to_3x3().inverted()
    rota_translate = rotate[0][:]+rotate[1][:]+rotate[2][:]+translate[:]
    obj['Transform'] = rota_translate


def rotation_translate(rota_mtx):
    mtx = list(rota_mtx)
    rota_invert = mathutils.Matrix((mtx[:3]+[0], mtx[3:6]+[0], mtx[6:9]+[0])).inverted()
    matrix = mathutils.Matrix.Translation((mtx[9], mtx[10], mtx[11])) @ rota_invert.to_4x4()
    return matrix


def collect_dmx_channels(gdtf_profile, mode):
    """Returns list of arrays, each array is one DMX Break,
    with DMX channels, defaults, geometries"""

    dmx_mode = None
    dmx_channels = []
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(gdtf_profile, mode)

    if dmx_mode:
        root_geometry = pygdtf.utils.get_geometry_by_name(gdtf_profile, dmx_mode.geometry)
    else:
        root_geometry = None
    device_channels = pygdtf.utils.get_channels_for_geometry(gdtf_profile, root_geometry, dmx_mode.dmx_channels, [])

    for channel, geometry in device_channels:
        feature = str(channel.logical_channels[0].attribute)
        if channel.offset is None:
            continue
        channel_break = channel.dmx_break
        if isinstance(geometry, pygdtf.GeometryReference) and channel.dmx_break == 'Overwrite':
            if len(geometry.breaks):
                channel_break = geometry.breaks[0].dmx_break
            else:
                channel_break = 1
        if len(dmx_channels) < channel_break:
            dmx_channels = dmx_channels + [[]] * (channel_break - len(dmx_channels))
        break_channels = dmx_channels[channel_break - 1]
        break_addition = 0
        if hasattr(geometry, "breaks"):
            dmx_offset = pygdtf.utils.get_address_by_break(geometry.breaks, channel_break)
            if dmx_offset is not None:
                break_addition = dmx_offset.address - 1
        offset_coarse = channel.offset[0] + break_addition
        offset_fine = 0
        if len(channel.offset) > 1:
            offset_fine = channel.offset[1] + break_addition
        max_offset = max([offset_coarse, offset_fine])
        if len(break_channels) < max_offset:
            break_channels = break_channels + [{
                'DMX': '',
                'ID': '',
                'Geometry': '',
                'Break': '',
                }] * (max_offset - len(break_channels))
        break_channels[offset_coarse - 1] = {
            'DMX': offset_coarse,
            'ID': feature,
            'Geometry': geometry.name,
            'Break': channel_break,
            'Functions': channel.logical_channels[0].channel_functions,
        }
        if offset_fine > 0:
            break_channels[offset_fine - 1] = {
                'DMX': offset_fine,
                'ID': '+' + feature,
                'Geometry': geometry.name,
                'Break': channel_break,
                'Functions': channel.logical_channels[0].channel_functions,
            }
        dmx_channels[channel_break - 1] = break_channels
        if feature in {'Pan', 'Tilt'}:
            channelData[geometry.name] = feature

    for index, break_list in enumerate(dmx_channels):
        dmx_channels[index] = [channel for channel in break_list if channel.get('ID', "") != ""]

    return dmx_channels


def convert_color(color_cie):
    """As blender needs RGBA, which we later strip anyways, we just add 100 for Alpha"""
    x = color_cie.x
    y = color_cie.y
    Y = color_cie.Y
    if not x or not y or not Y:
        return (0, 0, 0, 0)

    # convert to XYZ
    X = x * (Y / y)
    Z = (1 - x - y) * (Y / y)
    var_X = X / 100
    var_Y = Y / 100
    var_Z = Z / 100

    # XYZ to RGB
    var_R = var_X * 3.2406 + var_Y * -1.5372 + var_Z * -0.4986
    var_G = var_X * -0.9689 + var_Y * 1.8758 + var_Z * 0.0415
    var_B = var_X * 0.0557 + var_Y * -0.204 + var_Z * 1.057

    if var_R > 0.0031308:
        var_R = 1.055 * math.pow(var_R, 1 / 2.4) - 0.055
    else:
        var_R = 12.92 * var_R
    if var_G > 0.0031308:
        var_G = 1.055 * math.pow(var_G, 1 / 2.4) - 0.055
    else:
        var_G = 12.92 * var_G
    if var_B > 0.0031308:
        var_B = 1.055 * math.pow(var_B, 1 / 2.4) - 0.055
    else:
        var_B = 12.92 * var_B
    return (int(var_R * 100), int(var_G * 100), int(var_B * 100), 0)


def load_blender_primitive(model):
    primitive = str(model.primitive_type)
    if primitive == 'Cube':
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == 'Pigtail':
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == 'Plane':
        bpy.ops.mesh.primitive_plane_add(size=1.0)
    elif primitive == 'Cylinder':
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1.0)
    elif primitive == 'Sphere':
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=16, radius=0.5)
    obj = bpy.context.view_layer.objects.selected[0]
    obj.users_collection[0].objects.unlink(obj)
    obj.data.transform(mathutils.Matrix.Diagonal((model.length, model.width, model.height)).to_4x4())
    return obj


def load_gdtf_primitive(model):
    primitive = str(model.primitive_type)
    primitive_path = os.path.join(get_folder_path(), "primitives")
    path = os.path.join(primitive_path, f"{primitive}.glb")
    bpy.ops.import_scene.gltf(filepath=path)
    obj = bpy.context.view_layer.objects.selected[0]
    obj.users_collection[0].objects.unlink(obj)
    obj.data.transform(mathutils.Matrix.Diagonal((model.length / obj.dimensions.x,
                                                  model.width / obj.dimensions.y,
                                                  model.height / obj.dimensions.z)).to_4x4())
    return obj


def extract_gobos(profile, name):
    """now unused as we need sequences for keyframe animating"""
    gobos = []
    folder_path = os.path.join(get_folder_path(), create_fixture_name(name))
    for gobo_name in profile._package.namelist():
        if gobo_name.startswith("wheels"):
            short_name = gobo_name.replace("wheels/", "", 1)
            if short_name in bpy.data.images:
                gobo = bpy.data.images.get(short_name)
            else:
                profile._package.extract(gobo_name, folder_path)
                image_path = os.path.join(folder_path, gobo_name)
                gobo = bpy.data.images.load(image_path)
            gobos.append(gobo)
    return gobos


def get_wheel_slot_colors(profile):
    colors = []
    for wheel in profile.wheels:
        for slot in wheel.wheel_slots:
            try:
                color = convert_color(slot.color)
            except:
                color = None
            if color is not None and color not in colors:
                colors.append(color)
    return colors


def extract_gobos_as_sequence(profile, name):
    gdtf_path = os.path.join(get_folder_path(), name)
    images_path = os.path.join(gdtf_path, "wheels")
    sequence_path = os.path.join(gdtf_path, "sequence")
    for image_name in profile._package.namelist():
        if image_name.startswith("wheels"):
            profile._package.extract(image_name, gdtf_path)
    if not os.path.isdir(sequence_path):
        os.makedirs(sequence_path)
    first = ""
    count = 0
    for idx, image in enumerate(Path(images_path).rglob("*"), start=1):
        destination = Path(sequence_path, f"image_{idx:04}{image.suffix}")
        if idx == 1:
            first = str(destination.resolve())
        if idx == 256:
            break
        destination.write_bytes(image.read_bytes())
        count = idx
    if first:
        sequence = bpy.data.images.load(first)
    else:
        return None
    sequence["Count"] = count
    return sequence


def load_2d(profile, name):
    folder_path = os.path.join(get_folder_path(), name, "symbols")
    filename = f"{profile.thumbnail}.svg"
    obj = None
    if filename in profile._package.namelist():
        profile._package.extract(filename, folder_path)
    else:
        folder_path = os.path.join(get_folder_path(), "primitives")
        filename = "thumbnail.svg"

    bpy.ops.wm.gpencil_import_svg(filepath="", directory=folder_path, files=[{"name": filename}], scale=1)
    if len(bpy.context.view_layer.objects.selected):
        obj = bpy.context.view_layer.objects.selected[0]
    if obj is not None:
        obj.name = '2D Symbol'
        obj.users_collection[0].objects.unlink(obj)
        obj.rotation_euler[0] = math.radians(-90)
    return obj


def join_parts_apply_transforms(objects):
    join = 0
    single = None
    for ob in objects:
        mb = ob.matrix_basis
        if ob.type == 'MESH' and ob.data.vertices.items():
            ob.select_set(True)
            join += 1
            bpy.context.view_layer.objects.active = ob
            single = ob
            if hasattr(ob.data, 'Transform'):  # glb files
                ob.data.transform(mb)
        ob.matrix_basis.identity()
    if join > 0:
        bpy.ops.object.join()
        objects = list(bpy.context.view_layer.objects.selected)
    for obj in objects:
        obj.users_collection[0].objects.unlink(obj)
    if join == 1:
        objects = [single]
    for ob in objects:
        if ob.type == 'MESH':
            obj = ob
            break

    return obj


def load_model(profile, name, model):
    folder_path = os.path.join(get_folder_path(), name)
    obj_dimension = mathutils.Vector((model.length, model.width, model.height))

    if model.file.extension.lower() == "3ds":
        inside_zip_path = f"models/3ds/{model.file.name}.{model.file.extension}"
        profile._package.extract(inside_zip_path, folder_path)
        file_name = os.path.join(folder_path, inside_zip_path)
        load_3ds(file_name, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)
        for ob in bpy.context.selected_objects:
            if ob.dimensions.to_tuple(3) > tuple(v*10 for v in obj_dimension.to_tuple(3)):
                ob.data.transform(mathutils.Matrix.Scale(0.001, 4))
    else:
        inside_zip_path = f"models/gltf/{model.file.name}.{model.file.extension}"
        profile._package.extract(inside_zip_path, folder_path)
        file_name = os.path.join(folder_path, inside_zip_path)
        bpy.ops.import_scene.gltf(filepath=file_name)
    objects = list(bpy.context.selected_objects)

    # if the model is made up of multiple parts we must join them
    obj = join_parts_apply_transforms(objects)
    obj.rotation_mode = 'XYZ'
    scale_vector = obj.scale * obj_dimension
    dimensions = obj.dimensions or mathutils.Vector((1, 1, 1))
    obj.scale = mathutils.Vector([scale_vector[val] / dimensions[val] for val in range(3)])
    if obj.data:
        obj.data.name = model.file.name
    return obj


def build_collection(profile, name, fixture_id, uid, mode, BEAMS, TARGETS, CONES):
    """Create model collection."""

    objectDict = {}
    has_gobos = False
    fixturetype_id = profile.fixture_type_id
    collection = bpy.data.collections.new(name)
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(profile, mode)

    if dmx_mode is None:
        dmx_mode = profile.dmx_modes[0]
        mode = dmx_mode.name

    def create_gdtf_props(item, name):
        split_name = name.split()
        if len(split_name) > 1:
            fixture_name = split_name[1]
            item['Company'] = split_name[0]
        else:
            fixture_name = name
        item['Fixture Name'] = fixture_name

    collection['Fixture ID'] = fixture_id
    create_gdtf_props(collection, name)
    collection['UUID'] = uid
    root_geometry = pygdtf.utils.get_geometry_by_name(profile, dmx_mode.geometry)
    dmx_channels = collect_dmx_channels(profile, mode)
    virtual_channels = pygdtf.utils.get_virtual_channels(profile, mode)
    dmx_channels_flattened = [channel for break_channels in dmx_channels for channel in break_channels]

    for ch in dmx_channels_flattened:
        if 'Gobo' in ch['ID']:
            has_gobos = True

    def load_geometries(geometry):
        """Load 3d models, primitives and shapes"""
        print(f"loading geometry {geometry.name}")

        data_meshes = bpy.data.meshes
        data_objects = bpy.data.objects
        geometry_name = cleanup_name(geometry)
        geometry_class = geometry.__class__.__name__
        geometry_type = get_geometry_type_as_string(geometry)
        if geometry_class == 'GeometryBeam':
            if str(geometry.beam_type.value) in ['None' 'Glow']:
                geometry_name = 'Glow'
        for ob in bpy.context.selected_objects:
            ob.select_set(False)
        if isinstance(geometry, pygdtf.GeometryReference):
            reference = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
            geometry.model = reference.model

            if hasattr(reference, "geometries"):
                for sub_geometry in reference.geometries:
                    setattr(sub_geometry, "reference_root", str(geometry.name))
                    load_geometries(sub_geometry)

        if geometry.model is None:
            model = pygdtf.Model(name=f"{geometry}", length=0.0001, width=0.0001, height=0.0001, primitive_type='Cube')
            geometry.model = ""
        else:
            model = copy.deepcopy(pygdtf.utils.get_model_by_name(profile, geometry.model))

        if isinstance(geometry, pygdtf.GeometryReference):
            model.name = f"{geometry}"

        obj = None
        mesh_name = ""
        if model.file:
            mesh_name = model.file.name
        primitive = str(model.primitive_type)
        if primitive[-3:] == '1_1':
            primitive = primitive[:-3]
            model.primitive_type = pygdtf.PrimitiveType(primitive)

        # Prefer File first, as some GDTFs have both File and PrimitiveType
        if primitive == 'Undefined' or model.file and mesh_name != "" and primitive != 'Pigtail':
            obj = data_objects.get(geometry_name)
            if obj is None or obj.get('Model Name') != mesh_name or obj.get('Fixture ID') != fixture_id:
                geo = data_meshes.get(mesh_name)
                if geo and geo.get('Model Name') == mesh_name and geo.get('UUID') == fixturetype_id:
                    obj = data_objects.new(cleanup_name(geometry), geo)
                else:
                    try:
                        obj = load_model(profile, name, model)
                    except Exception as exc:
                        print("Error importing 3D model: %s" % exc)
                        model.primitive_type = 'Cube'
                        obj = load_blender_primitive(model)
        else:
            primesh = data_meshes.get(primitive)
            if primesh and primesh.get('UUID') == fixturetype_id:
                obj = data_objects.new(primitive, primesh)
            elif primitive in ['Base', 'Conventional', 'Head', 'Yoke']:
                obj = load_gdtf_primitive(model)
                obj.data.name = primitive
            else:
                obj = load_blender_primitive(model)
                obj.data.name = primitive

        # If object was created
        if obj is not None:
            if obj.data:
                obj_name = obj.name.split('.')[0]
                if obj.get('UUID') is None:
                    obj.data['Geometry Class'] = geometry_class
                    obj.data['Geometry Type'] = geometry_type
                    obj.data['Original Name'] = obj_name
                    obj.data['Model Name'] = mesh_name
                    obj.data['UUID'] = fixturetype_id
                if obj.data.materials:
                    for mtl in obj.data.materials:
                        mtl_name = mtl.name.split('.')[0]
                        mtl.name = mtl_name
                        if obj.get('UUID') is None:
                            create_gdtf_props(mtl, name)
                            mtl['Original Name'] = mtl_name
                            mtl['Model Name'] = mesh_name
                            mtl['UUID'] = fixturetype_id
            obj.name = geometry_name
            obj['Fixture ID'] = fixture_id
            create_gdtf_props(obj, name)
            obj['Fixture Mode'] = mode
            obj['Geometry Class'] = geometry_class
            obj['Geometry Type'] = geometry_type
            obj['Model Name'] = mesh_name
            obj['Original Name'] = geometry.name.split('.')[0]
            
            if geometry_name == cleanup_name(root_geometry):
                obj['Root Geometry'] = True
                obj.hide_select = False
            else:
                obj.hide_select = True
            if isinstance(geometry, pygdtf.GeometryReference):
                obj['Reference'] = str(geometry.geometry)
            if str(model.primitive_type) == 'Pigtail':
                obj['Geometry Type'] = 'Pigtail'
            objectDict[cleanup_name(geometry)] = obj
            mb = obj.matrix_basis.copy()
            if hasattr(obj.data, 'Transform'):
                obj.data.transform(mb) 
            for cld in obj.children:
                cld.matrix_local = mb @ cld.matrix_local
            obj.matrix_basis.identity()

        if hasattr(geometry, "geometries"):
            for sub_geometry in geometry.geometries:
                load_geometries(sub_geometry)

    def get_geometry_type_as_string(geometry):
        if isinstance(geometry, pygdtf.GeometryMediaServerCamera):
            return 'Camera'
        if isinstance(geometry, pygdtf.GeometryBeam):
            return 'Beam'
        if isinstance(geometry, pygdtf.GeometryLaser):
            return 'Laser'
        if isinstance(geometry, pygdtf.GeometryAxis):
            return 'Axis'
        if isinstance(geometry, pygdtf.GeometryReference):
            geometry = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
            return get_geometry_type_as_string(geometry)
        return 'Normal'

    def create_camera(geometry):
        if not cleanup_name(geometry) in objectDict:
            return
        obj_child = objectDict[cleanup_name(geometry)]
        camera_data = bpy.data.cameras.get(name=f"{obj_child.name}")
        if camera_data is None:
            camera_data = bpy.data.cameras.new(name=f"{obj_child.name}")
        camera_object = bpy.data.objects.new('MediaCamera', camera_data)
        camera_object.hide_select = True
        camera_object.parent = obj_child
        camera_object.matrix_parent_inverse = obj_child.matrix_world.inverted()
        camera_object.rotation_euler[0] += math.radians(90)
        collection.objects.link(camera_object)

    def create_beam(geometry):
        default_factor = 1000
        data_lights = bpy.data.lights
        if cleanup_name(geometry) not in objectDict:
            return
        obj_child = objectDict[cleanup_name(geometry)]
        if not BEAMS:
            return
        if any(geometry.beam_type.value == x for x in ['None', 'Glow']):
            return

        obj_child.visible_shadow = False
        light_name = name.split()[-1]
        light_data = data_lights.get(f"{light_name} {obj_child.name}")
        if light_data is None or light_data.get('Fixture Name') != light_name:
            light_data = data_lights.new(f"{light_name} {obj_child.name}", 'SPOT')
            create_gdtf_props(light_data, name)
            light_data['Flux'] = geometry.luminous_flux
            light_data.energy = light_data['Flux']
            light_data.diffuse_factor = max((default_factor / light_data.energy), 1.0)
            light_data.specular_factor = max(((default_factor * 2) / light_data.energy), 1.0)
            light_data.use_custom_distance = True
            light_data.cutoff_distance = 23
            light_data.spot_blend = calculate_spot_blend(geometry)
            light_data.spot_size = math.radians(geometry.beam_angle)
            light_data.shadow_soft_size = geometry.beam_radius * 0.1
            light_data['Radius'] = geometry.beam_radius
            light_data['Gobo'] = True
            light_data['UUID'] = fixturetype_id
            light_data.shadow_buffer_clip_start = 0.0001
            if CONES:
                light_data.show_cone = True
        light_object = bpy.data.objects.new('Spot', light_data)
        light_object.hide_select = True
        light_object.parent = obj_child
        create_gdtf_props(light_object, name)
        light_object['Geometry Class'] = geometry.__class__.__name__
        obj_child.matrix_parent_inverse = light_object.matrix_world.inverted()
        create_transform_property(light_object)
        collection.objects.link(light_object)

        gobo_radius = 2.2 * 0.01 * math.tan(math.radians(geometry.beam_angle / 2))
        goboGeometry = SimpleNamespace(name=f"Gobo {geometry}", length=gobo_radius, width=gobo_radius,
                                       height=0, primitive_type='Plane', beam_radius=geometry.beam_radius)
        if has_gobos:
            create_gobo(geometry, goboGeometry)
            if not light_data.use_nodes:
                light_data.use_nodes = True
                nodes = light_data.node_tree.nodes
                links = light_data.node_tree.links
                emit = nodes.get('Emission')
                emit.label = 'Fixture'
                emit.location = (80, 300)
                lightpath = nodes.new(type='ShaderNodeLightPath')
                lightfalloff = nodes.new(type='ShaderNodeLightFalloff')
                lightpath.location = (-1140, 180)
                lightfalloff.location = (-720, 60)
                emit.inputs[0].default_value[:3] = light_data.color
                links.new(emit.outputs[0], nodes['Light Output'].inputs[0])
                links.new(lightpath.outputs[7], lightfalloff.inputs[1])
                links.new(lightpath.outputs[8], lightfalloff.inputs[0])
                links.new(lightfalloff.outputs[0], emit.inputs[1])

    def create_laser(geometry):
        if cleanup_name(geometry) not in objectDict:
            return
        obj_child = objectDict[cleanup_name(geometry)]
        if 'Laser' not in obj_child.name.lower():
            obj_child.name = f"Laser {obj_child.name}"
        obj_child.visible_shadow = False
        obj_child.rotation_mode = 'XYZ'
        obj_child['Diameter'] = geometry.beam_diameter

    def create_gobo(geometry, goboGeometry):
        geometry_class = geometry.__class__.__name__
        msh = bpy.data.meshes.get(goboGeometry.name)
        if msh and msh.get('Geometry Type') == 'Gobo' and msh.get('UUID') == fixturetype_id:
            obj = bpy.data.objects.new(goboGeometry.name, msh)
        else:
            obj = load_blender_primitive(goboGeometry)
        obj['Geometry Class'] = obj.data['Geometry Class'] = geometry_class     
        obj['Geometry Type'] = obj.data['Geometry Type'] = 'Gobo'
        obj['Radius'] = obj.data['Radius'] = goboGeometry.beam_radius
        obj.dimensions = (goboGeometry.length, goboGeometry.width, 0)
        obj.name = obj.data.name = goboGeometry.name
        objectDict[cleanup_name(goboGeometry)] = obj
        obj.location[2] += -0.01
        constraint_child_to_parent(geometry, goboGeometry)

    def calculate_spot_blend(geometry):
        """Return spot_blend value based on beam_type."""
        beam_type = geometry.beam_type.value
        if any(beam_type == x for x in ['Wash', 'Fresnel', 'PC']):
            return 1.0
        return 0.0

    def add_child_position(geometry):
        """Add a child position"""
        obj_child = objectDict[cleanup_name(geometry)]
        geometry_mtx = mathutils.Matrix(geometry.position.matrix)
        translate = geometry_mtx.to_translation()
        rotation = geometry_mtx.to_3x3().inverted()
        scale = geometry_mtx.to_scale()
        obj_child.matrix_local = mathutils.Matrix.LocRotScale(translate, rotation, scale)
        create_transform_property(obj_child)

    def constraint_child_to_parent(parent_geometry, child_geometry):
        if not cleanup_name(parent_geometry) in objectDict:
            return
        obj_parent = objectDict[cleanup_name(parent_geometry)]
        if not cleanup_name(child_geometry) in objectDict:
            return
        obj_child = objectDict[cleanup_name(child_geometry)]
        obj_child.parent = obj_parent
        obj_child.matrix_parent_inverse = obj_parent.matrix_world.inverted()

    def update_geometry(geometry):
        """Recursively update objects position, rotation and scale
        and define parent/child constraints."""

        if not isinstance(geometry, pygdtf.GeometryReference):
            add_child_position(geometry)
        if isinstance(geometry, pygdtf.GeometryBeam):
            create_beam(geometry)
        if isinstance(geometry, pygdtf.GeometryLaser):
            create_laser(geometry)
        elif isinstance(geometry, (pygdtf.GeometryMediaServerCamera)):
            create_camera(geometry)
        elif isinstance(geometry, pygdtf.GeometryReference):
            reference = copy.deepcopy(pygdtf.utils.get_geometry_by_name(profile, geometry.geometry))
            reference.name = cleanup_name(geometry)
            add_child_position(reference)
            reference.position = geometry.position
            add_child_position(reference)
            if isinstance(reference, pygdtf.GeometryBeam):
                create_beam(reference)
            if isinstance(reference, pygdtf.GeometryLaser):
                create_laser(reference)
            elif isinstance(reference, (pygdtf.GeometryMediaServerCamera)):
                create_camera(reference)
            if hasattr(reference, "geometries"):
                if len(reference.geometries) > 0:
                    for child_geometry in reference.geometries:
                        setattr(child_geometry, "reference_root", str(reference.name))
                        constraint_child_to_parent(reference, child_geometry)
                        update_geometry(child_geometry)
            return

        if hasattr(geometry, "geometries"):
            if len(geometry.geometries) > 0:
                for child_geometry in geometry.geometries:
                    constraint_child_to_parent(geometry, child_geometry)
                    update_geometry(child_geometry)

    load_geometries(root_geometry)
    update_geometry(root_geometry)
        
    def get_axis_objects(attribute):
        axis_objects = []
        for obj in objectDict.values():
            feature = channelData.get(obj.get('Original Name'))
            obj['Mobile Axis'] = feature
            if feature == attribute:
                axis_objects.append(obj)
        return axis_objects

    def check_center_object(obj):
        return (abs(round(obj.location.x, 1)) == 0.0 and abs(round(obj.location.y, 1)) == 0.0)

    # This could be moved to the processing up higher,but for now, it's easier here
    moving_objects = [ob for ob in objectDict.values() if ob.get('Geometry Type') == 'Axis']
    base = next(ob for ob in objectDict.values() if ob.get('Root Geometry'))
    yokes = get_axis_objects('Pan')
    heads = get_axis_objects('Tilt')

    if TARGETS:
        target_uid = str(pyuid.uuid4())
        data_objects = bpy.data.objects
        main_target = bpy.data.objects.new('Target', None)
        main_target.empty_display_size = 0.4
        collection.objects.link(main_target)
        main_target['Fixture ID'] = fixture_id
        create_gdtf_props(main_target, name)
        main_target['Geometry Type'] = 'Target'
        main_target['UUID'] = target_uid
        targetData[target_uid] = main_target

        for idx, obj in enumerate(moving_objects):
            center_object = check_center_object(obj)
            center_parent = obj.parent and check_center_object(obj.parent)
            check_pan = obj.parent and obj.parent.get('Mobile Axis') == 'Tilt'
            check_tilt = obj.get('Mobile Axis') == 'Tilt'
            constraint = obj.constraints.new('LOCKED_TRACK')
            if check_tilt or check_pan and obj.parent.parent and obj.parent.parent.get('Mobile Axis') == 'Pan':
                constraint.track_axis = 'TRACK_NEGATIVE_Z'
            else:
                constraint.track_axis = 'TRACK_NEGATIVE_Y'
            constraint.lock_axis = 'LOCK_X' if obj.get('Mobile Axis') == 'Tilt' else 'LOCK_Z'
            if center_object and center_parent:
                constraint.target = main_target
                obj['Target'] = target_uid
            else:
                if obj.parent and len(obj.parent.children) > 1:
                    if not center_object or (center_object and not center_parent):
                        target_name = 'Target %s' % obj.name
                        obj_target = bpy.data.objects.new(target_name, None)
                        obj_target.empty_display_type = 'SINGLE_ARROW'
                        obj_target.empty_display_size = 0.2
                        obj_target.parent = main_target
                        obj_target['Fixture ID'] = fixture_id
                        create_gdtf_props(obj_target, name)
                        obj_target['Geometry Class'] = 'Target'
                        obj_target['Reference'] = obj.get('Original Name', obj.name)
                        collection.objects.link(obj_target)
                        if not center_object:
                            obj_target.location = (obj.location.x, obj.location.y, 0)
                        elif center_object and not center_parent:
                            obj_target.location = (obj.parent.location.x, obj.parent.location.y, 0)
                        create_transform_property(obj_target)
                        constraint.target = obj_target
            if not yokes and not heads:
                constraint = base.constraints.new('TRACK_TO')
                constraint.target = main_target
    
    # 2D thumbnail planning symbol
    obj = load_2d(profile, name)
    if obj is not None:
        obj['2D Symbol'] = "all"
        objectDict['2D Symbol'] = obj
        obj.show_in_front = True
        if obj.active_material.grease_pencil:
            obj.active_material.grease_pencil.show_stroke = True
        obj.data.pixel_factor = 2

        # Add constraints
        constraint_copyLocation = obj.constraints.new(type='COPY_LOCATION')
        constraint_copyRotation = obj.constraints.new(type='COPY_ROTATION')
        constraint_copyLocation.target = base
        constraint_copyRotation.target = base
        constraint_copyRotation.use_z = True
        constraint_copyRotation.use_x = False
        constraint_copyRotation.use_y = False

    # Link objects to collection
    for name, obj in objectDict.items():
        collection.objects.link(obj)
    
    objectDict.clear()
    return collection


def get_fixture_models(profile, name, fixture_id, uid, dmx_mode, BEAMS, TARGETS, CONES):
    collections = bpy.data.collections

    if profile == None:
        return None

    new_collection = collections.get(name)
    if new_collection and len(new_collection.objects) and new_collection.get('Fixture ID') == fixture_id:
        print("Getting collection from cache: %s" % name)
        return new_collection
    else:
        new_collection = build_collection(profile, name, fixture_id, uid, dmx_mode, BEAMS, TARGETS, CONES)
        return new_collection


def get_root_model(model_collection):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        if obj.get('Root Geometry', False):
            return obj


def get_tilt(model_collection, channels):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        for channel in channels:
            if 'Tilt' == channel.get('ID') and channel.get('Geometry') == obj.get('Original Name', 'None'):
                return obj


def fixture_build(context, filename, mscale, name, position, focus_point,
                  fixture_idx, collect, fixture, TARGETS=True, BEAMS=True, CONES=False):

    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    layer_collect = viewlayer.layer_collection
    gdtf_profile = pygdtf.FixtureType(filename)
    fixture_name = create_fixture_name(name)
    uid = gdtf_profile.fixture_type_id
    mode = FixtureMode(gdtf_profile)
    fixture_id = fixture_idx
    color = (1.0, 1.0, 1.0)
    has_gobos = False
    channels = []

    if fixture:
        uid = fixture.uuid
        mode = fixture.gdtf_mode
        fixture_id = int(fixture.fixture_id)
        gel_color = convert_color(fixture.color)
        color =  list(int((255/1)*i) for i in gel_color[:3])

    def index_name(device):
        device_name = device
        if fixture_id > 0:
            device_name = 'ID%d %s' % (fixture_id, device.split('.')[0])
        return device_name

    # Remove Collection if same index
    index_collection = next((col for col in data_collect if col.get('Fixture ID') == fixture_id), False)
    if index_collection:
        for obj in index_collection.objects:
            object_data.remove(obj)
        data_collect.remove(index_collection)

    # Import Fixture Model Collection
    model_collection = get_fixture_models(gdtf_profile, fixture_name, fixture_id, uid, mode, BEAMS, TARGETS, CONES)
    if model_collection:
        collection_name = fixture_name if fixture is None else name
        model_collection.name = index_name(collection_name)
        if collect and model_collection.name not in collect.children:
            collect.children.link(model_collection)

    # Build DMX channels cache
    if not any(mode == md.name for md in gdtf_profile.dmx_modes):
        mode = gdtf_profile.dmx_modes[0].name
    dmx_channels = collect_dmx_channels(gdtf_profile, mode)
    channels += [channel for break_channels in dmx_channels for channel in break_channels]

    # Build cache of virtual channels
    _virtual_channels = pygdtf.utils.get_virtual_channels(gdtf_profile, mode)
    for ch in _virtual_channels:
        if 'Gobo' in ch.get('id'):
            has_gobos = True

    # Get all gobos
    if has_gobos:
        gobo_material = bpy.data.materials.new('Gobos')
        principled_shader = PrincipledBSDFWrapper(gobo_material, is_readonly=False, use_nodes=True)
        gobo_seq = extract_gobos_as_sequence(gdtf_profile, name)
        if gobo_seq is not None:
            gobo = bpy.data.images.new('Gobo')
    if 'Gobo' not in bpy.data.images:
        has_gobos = False

    linkDict = {}
    base = get_root_model(model_collection)
    head = get_tilt(model_collection, channels)

    if model_collection:
        print("creating model collection... %s" % model_collection.name)
        for obj in model_collection.objects:
            linkDict[obj.name] = obj
            if obj.type == 'MESH' and obj.get('Geometry Type') == 'Beam':
                if not len(obj.data.materials):
                    emit_material = bpy.data.materials.new(obj.name + ' ' + obj.get('Geometry Type'))
                    obj.data.materials.append(emit_material)
                emitter = obj.active_material
                emitter.shadow_method = "NONE"
                emit_shader = PrincipledBSDFWrapper(emitter, is_readonly=False, use_nodes=True)
                emit_shader.emission_strength = 1.0
                emit_shader.emission_color = color
            elif obj.parent and obj.type == 'LIGHT':
                obj['UUID'] = uid
                obj.matrix_world = obj.matrix_world @ obj.parent.matrix_local.inverted()
                gobos = extract_gobos(gdtf_profile, name)
                if len(gobos):
                    nodes = obj.data.node_tree.nodes
                    links = obj.data.node_tree.links
                    emit = nodes.get('Emission')
                    mix = nodes.new(type='ShaderNodeMixRGB')
                    rgb = nodes.new(type='ShaderNodeRGB')
                    mix.blend_type = 'DARKEN'
                    mix.location = (-140, 340)
                    rgb.location = (-380, 100)
                    mix.inputs[2].default_value[:3] = rgb.outputs[0].default_value[:3] = obj.data.color
                    gobo_node = nodes.new(type='ShaderNodeTexImage')
                    rota_node = nodes.new(type='ShaderNodeVectorRotate')
                    cord_node = nodes.new(type='ShaderNodeTexCoord')
                    norm_node = nodes.new(type='ShaderNodeNormal')
                    gobo_image = random.choice(gobos)
                    gobo_node.image = gobo_image
                    gobo_node.label = 'Gobo: ' + gobo_image.name
                    cord_node.label = 'Gobo Coordinate'
                    rota_node.rotation_type = 'Z_AXIS'
                    rota_node.inputs[1].default_value[:2] = [0.5] * 2
                    gobo_node.location = (-480, 440)
                    rota_node.location = (-720, 440)
                    norm_node.location = (-940, 400)
                    cord_node.location = (-1140, 440)
                    lightfalloff = nodes.get('Light Falloff')
                    links.new(rota_node.outputs[0], gobo_node.inputs[0])
                    links.new(cord_node.outputs[2], rota_node.inputs[0])
                    links.new(norm_node.outputs[1], rota_node.inputs[3])
                    links.new(cord_node.outputs[6], norm_node.inputs[0])
                    links.new(lightfalloff.outputs[1], mix.inputs[0])
                    links.new(gobo_node.outputs[0], mix.inputs[1])
                    links.new(rgb.outputs[0], mix.inputs[2])
                    links.new(mix.outputs[0], emit.inputs[0])
            elif obj.get('Geometry Type') == 'Target':
                obj.name = index_name(obj.name)
            elif obj.get('Geometry Type') == 'Axis':
                obj['UUID'] = uid
            elif obj.get('Root Geometry'):
                ob_name = fixture_name if fixture is None else name
                obj['UUID'] = uid
                obj.name = index_name(ob_name)
            elif obj.get('2D Symbol', None) == "all":
                obj.name = index_name('2D Symbol')

        # Reparent children
        for obj in model_collection.objects:
            for child in obj.children:
                if child.name in linkDict:
                    linkDict[child.name].parent = obj
                child.name = index_name(child.name)
            if obj.type == 'MESH' and len(obj.data.materials):
                for mtl in obj.data.materials:
                    ob_name = obj.name.split()
                    if fixture is None:
                        obj_name = ob_name[-1]
                    elif len(ob_name) > 1:
                        obj_name = ob_name[-2]
                    else:
                        obj_name = ob_name[0]
                    split_name = mtl.name.split('.')[0]
                    obj_material = '%s_%s' % (obj_name, split_name)
                    mtl.name = index_name(obj_material)
            if obj.get('Root Geometry'):
                for parents in obj.children_recursive:
                    if len(parents.children) > 1:
                        for idx, childs in enumerate(parents.children):
                            if len(childs.children) > 1:
                                for i, child in enumerate(childs.children):
                                    child_name = child.name.split('.')[0]
                                    child.name = '%s %d' % (child_name, i + 1)
                            else:
                                for child in childs.children_recursive:
                                    child_name = child.name.split('.')[0]
                                    child.name = '%s %d' % (child_name, idx + 1)
          
        # Relink constraints
        for obj in model_collection.objects:
            target = obj.get('Target')
            if len(obj.constraints):
                for child in obj.children:
                    if len(child.constraints) and child.constraints[0].target is None:
                        if child.constraints[0].target is None:
                            child.constraints[0].target = obj.constraints[0].target
            if target is not None:
                for constraint in obj.constraints:
                    constraint.target = targetData.get(target)

        # Set position
        for obj in model_collection.objects:
            if obj.get('Root Geometry', False):
                obj.matrix_world = position @ obj.matrix_world.copy()
                create_transform_property(obj)

        # Set target's position from MVR
        if focus_point is not None:
            for obj in model_collection.objects:
                if obj.get('Geometry Type') == 'Target':
                    obj.matrix_world = focus_point
                    create_transform_property(obj)

        # Setup emitter
        for obj in model_collection.objects:
            if 'Gobo' in obj.get('Geometry Type', ""):
                gobo_material = bpy.data.materials.new(index_name(obj.name))
                obj.active_material = gobo_material
                obj.active_material.shadow_method = 'CLIP'
                obj.active_material.blend_method = 'BLEND'
                obj.material_slots[0].link = 'OBJECT' # ensure that each fixture has it's own material
                obj.material_slots[0].material = gobo_material

        # Link collection to DMX collection
        if collect is None and model_collection.name not in layer_collect.collection.children:
            layer_collect.collection.children.link(model_collection)

        # Set Pigtail visibility and Beam selection
        for obj in model_collection.objects:
            if 'Pigtail' in obj.get('Geometry Type', ""):
                obj.hide_set(False)
                obj.hide_viewport = False
                obj.hide_render = False
            if obj.get('Root Geometry', False):
                continue
            if 'Target' in obj.name:
                continue
            if obj.get('2D Symbol', None) == "all":
                obj.hide_set(True)
                obj.hide_viewport = True
                obj.hide_render = True
                continue

            obj.hide_select = False


def load_gdtf(context, filename, mscale, name, position, focus_point,
              fixture_idx, collect, fixture, TARGETS=True, BEAMS=True, CONES=False):

    targetData.clear()
    channelData.clear()

    fixture_build(context, filename, mscale, name, position, focus_point,
                  fixture_idx, collect, fixture, TARGETS, BEAMS, CONES)

    targetData.clear()
    channelData.clear()


def load_prepare(context, filename, global_matrix, collect, align_objects,
                 scale_objects, fixture_index, fixture_count, TARGETS, BEAMS, CONES):

    
    name = Path(filename).stem
    mscale = mathutils.Matrix.Scale(scale_objects, 4)

    if global_matrix is not None:
        mscale = global_matrix @ mscale

    for idx in range(fixture_index, fixture_index + fixture_count):
        count = idx - fixture_index
        distribution = count * align_objects
        align = 0.5 * (fixture_count * align_objects) - (0.5 * align_objects)
        position = mathutils.Matrix.Translation((distribution - align, 0, 1))
        focus_point = mathutils.Matrix.Translation((position.to_translation().x, 0, 0))
        load_gdtf(context, filename, mscale, name, position,
                  focus_point, idx, collect, None, TARGETS, BEAMS, CONES)


def load(operator, context, files=None, directory="", filepath="", fixture_index=0, fixture_count=1, align_objects=0.5,
         scale_objects=1.0, use_collection=False, use_target=True, use_beams=True, use_show_cone=False, global_matrix=None):

    context.window.cursor_set('WAIT')
    default_layer = context.view_layer.active_layer_collection.collection

    for fl in files:
        collect = None
        if use_collection:
            collect = bpy.data.collections.new(Path(fl.name).stem)
            context.scene.collection.children.link(collect)
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collect.name]
        load_prepare(context, os.path.join(directory, fl.name), global_matrix, collect, align_objects, scale_objects,
                     fixture_index, fixture_count, TARGETS=use_target, BEAMS=use_beams, CONES=use_show_cone)

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
