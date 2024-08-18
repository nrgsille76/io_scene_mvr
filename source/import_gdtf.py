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
import random
import pygdtf
import mathutils
import uuid as pyuid
from types import SimpleNamespace
from io_scene_3ds.import_3ds import load_3ds
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from pathlib import Path

targetData = {}
channelData = {}
rangeData = {}


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
        clean_name = manufacturer + '_' + fixture_name
    else:
        clean_name = split_name[0]
    return clean_name


def create_fixture_id(item, fixture_id):
    item['Fixture ID'] = fixture_id
    item.id_properties_ensure()
    item_property = item.id_properties_ui('Fixture ID')
    item_property.update(default=0, min=0, max=4096, soft_min=0, soft_max=4096)


def create_gdtf_props(item, name):
    if '_' in name:
        split_name = name.split('_')
    else:
        split_name = name.split()
    if len(split_name) > 1:
        item['Company'] = split_name[0]
        fixture_name = split_name[1]
    else:
        fixture_name = name
    item['Fixture Name'] = fixture_name


def create_dimmer_driver(item, target, power):
    dimmer_val = "energy" if item.type == 'SPOT' else "default_value"
    dimmer_curve = item.driver_add(dimmer_val)
    dimmer_drive = dimmer_curve.driver
    dimmer_drive.type = 'SCRIPTED'
    dimmer_drive.expression = "flux * dim * 0.01" if item.type == 'SPOT' else "dim * 0.01"
    dimmer_var = dimmer_drive.variables.new()
    dimmer_var.name = "dim"
    dimmer_target = dimmer_var.targets[0]
    dimmer_target.id = target
    dimmer_target.data_path = '["Intensity"]'
    if item.type == 'SPOT':
        energy_var = dimmer_drive.variables.new()
        energy_var.name = "flux"
        energy_target = energy_var.targets[0]
        energy_target.id = power
        energy_target.data_path = '["Flux"]'


def create_color_driver(item, target, path):
    color_val = "color" if item.type == 'SPOT' else "default_value"
    red_curve = item.driver_add(color_val, 0)
    green_curve = item.driver_add(color_val, 1)
    blue_curve = item.driver_add(color_val, 2)
    red_drive = red_curve.driver
    green_drive = green_curve.driver
    blue_drive = blue_curve.driver
    red_drive.type = green_drive.type = blue_drive.type = 'AVERAGE'
    red_var = red_drive.variables.new()
    green_var = green_drive.variables.new()
    blue_var = blue_drive.variables.new()
    red_var.name = "R"
    green_var.name = "G"
    blue_var.name = "B"
    red_target = red_var.targets[0]
    green_target = green_var.targets[0]
    blue_target = blue_var.targets[0]
    red_target.id = green_target.id = blue_target.id = target
    red_target.data_path = f'["{path}"][0]'
    green_target.data_path = f'["{path}"][1]'
    blue_target.data_path = f'["{path}"][2]'


def create_gobo_driver(node, target, item=None):
    node.inputs[1].default_value[:2] = [0.5] * 2
    rota_curve = node.inputs[3].driver_add("default_value")
    rota_drive = rota_curve.driver
    rota_drive.type = 'AVERAGE'
    rota_var = rota_drive.variables.new()
    rota_var.name = "gobo_rotate"
    rota_target = rota_var.targets[0]
    rota_target.id = target
    rota_target.data_path = '["Gobo Rotate"]'
    node.rotation_type = 'Z_AXIS'
    node.inputs[1].hide = True
    if item is not None:
        item.inputs[2].hide = True
        item.inputs[0].name = 'Gobo'
        item.inputs[1].name = 'Slot'
        gobo_curve = item.inputs[0].driver_add("default_value")
        slot_curve = item.inputs[1].driver_add("default_value")
        gobo_drive = gobo_curve.driver
        slot_drive = slot_curve.driver
        gobo_drive.type = slot_drive.type = 'SCRIPTED'
        gobo_drive.expression = "gobo % 10"
        slot_drive.expression = "gobo // 10"
        gobo_var = gobo_drive.variables.new()
        slot_var = slot_drive.variables.new()
        gobo_var.name = slot_var.name = "gobo"
        gobo_target = gobo_var.targets[0]
        slot_target = slot_var.targets[0]
        gobo_target.id = slot_target.id = target
        gobo_target.data_path = slot_target.data_path = '["Gobo Select"]'
        item.location = (-860, 120)


def create_trackball_driver(item, target, prop):
    range_property = item.id_properties_ui("Range")
    range_data = range_property.as_dict()
    min_angle = range_data.get("min")
    max_angle = range_data.get("max")
    check_target = target.get('Target')
    check_pan = item.get('Mobile Axis') == "Pan"
    path = f'["{prop}"][0]' if check_pan else f'["{prop}"][1]'
    value = "min_z" if check_pan else "min_x"
    limit = item.constraints.get('Limit Rotation')
    lock = item.constraints.get('Locked Track')
    if limit:
        limit.enabled = check_target
        axis_value = limit.max_z if check_pan else limit.max_x
        move_curve = limit.driver_add(value)
        limit_curve = limit.driver_add("influence")
        move_drive = move_curve.driver
        limit_drive = limit_curve.driver
        move_drive.type = limit_drive.type = 'SCRIPTED'
        move_drive.expression = "track * angle"
        limit_drive.expression = "1.0 if track else 0.0"
        move_var = move_drive.variables.new()
        angle_var = move_drive.variables.new()
        limit_var = limit_drive.variables.new()
        limit_var.name = move_var.name = "track"
        angle_var.name = "angle"
        move_target = move_var.targets[0]
        limit_target = limit_var.targets[0]
        angle_target = angle_var.targets[0]
        move_target.id = limit_target.id = angle_target.id = target
        move_target.data_path = path
        limit_target.data_path = '["Trackball"]'
        angle_target.use_fallback_value = True
        angle_target.fallback_value = max_angle
        axis_value = min_angle
    if lock:
        bool_curve = lock.driver_add("enabled")
        lock_curve = lock.driver_add("influence")
        bool_drive = bool_curve.driver
        lock_drive = lock_curve.driver
        bool_drive.type = 'AVERAGE'
        lock_drive.type = 'SCRIPTED'
        lock_drive.expression = "0.0 if track else 1.0"
        bool_var = bool_drive.variables.new()
        lock_var = lock_drive.variables.new()
        bool_var.name = "target"
        lock_var.name = "track"
        bool_target = bool_var.targets[0]
        lock_target = lock_var.targets[0]
        bool_target.id = lock_target.id = target
        lock_target.data_path = '["Trackball"]'
        bool_target.data_path = '["Target"]'


def create_zoom_driver(item, target):
    if item.id_type == 'LIGHT':
        zoom_curve = item.driver_add("spot_size")
        zoom_drive = zoom_curve.driver
        zoom_drive.type = 'AVERAGE'
        zoom_var = zoom_drive.variables.new()
        zoom_var.name = "focus_zoom"
        zoom_target = zoom_var.targets[0]
        zoom_target.id = target
        zoom_target.data_path = '["Focus Zoom"]'
    elif item.id_type == 'OBJECT':
        x_curve = item.driver_add("scale", 0)
        y_curve = item.driver_add("scale", 1)
        x_drive = x_curve.driver
        y_drive = y_curve.driver
        x_drive.type = y_drive.type = 'SCRIPTED'
        x_drive.expression = "zoom / max(angle, 1e-09)"
        y_drive.expression = "zoom / max(angle, 1e-09)"
        zoom_x = x_drive.variables.new()
        zoom_y = y_drive.variables.new()
        angle_x = x_drive.variables.new()
        angle_y = y_drive.variables.new()
        zoom_x.name = zoom_y.name = "zoom"
        angle_x.name = angle_y.name = "angle"
        zoom_x_target = zoom_x.targets[0]
        zoom_y_target = zoom_y.targets[0]
        angle_x_target = angle_x.targets[0]
        angle_y_target = angle_y.targets[0]
        zoom_x_target.id = zoom_y_target.id = target
        angle_x_target.id = angle_y_target.id = item
        zoom_x_target.data_path = zoom_y_target.data_path = '["Focus Zoom"]'
        angle_x_target.data_path = angle_y_target.data_path = '["Focus"]'


def create_gobo_property(item, count):
    item["Gobo Rotate"] = 0.0
    item.id_properties_ensure()
    gobo_property = item.id_properties_ui("Gobo Select")
    angle_property = item.id_properties_ui("Gobo Rotate")
    gobo_property.update(default=0.0, min=0.0, max=count, soft_min=0.0, soft_max=count, precision=1, step=0.1, subtype='LAYER')
    angle_property.update(default=0.0, min=-360.0, max=360.0, soft_min=-540.0, soft_max=540.0, precision=1, step=1.0, subtype='ANGLE') 


def create_color_property(item, color, prop):
    item[prop] = color
    item.id_properties_ensure()
    color_property = item.id_properties_ui(prop)
    color_property.update(default=color, min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, subtype='COLOR_GAMMA')


def create_ctc_property(item, ctc, prop):
    if ctc:
        tmin = 1000.0
        tmax = 10000.0
        item[prop] = ctc
        item.id_properties_ensure()
        ctc_property = item.id_properties_ui(prop)
        ctc_property.update(default=ctc, min=tmin, max=tmax, soft_min=tmin, soft_max=tmax, precision=0, step=100.0, subtype='TEMPERATURE')
        

def create_dimmer_property(item):
    item['Intensity'] = 100
    item.id_properties_ensure()
    dimmer_property = item.id_properties_ui('Intensity')
    dimmer_property.update(default=100, min=0, max=100, soft_min=0, soft_max=100, subtype='PERCENTAGE')


def create_range_property(item, angle, prop, limits=False):
    if angle:
        val = angle
        if limits:
            rmin = math.radians(min(limits))
            rmax = math.radians(max(limits))
        elif isinstance(angle, tuple):
            rmin = math.radians(min(angle))
            rmax = math.radians(max(angle))
            val = rmin, rmax
        else:
            rmin = abs(angle) / 2
            rmax = abs(angle) * 2
        item[prop] = val
        item.id_properties_ensure()
        range_property = item.id_properties_ui(prop)
        range_property.update(default=val, min=rmin, max=rmax, soft_min=rmin, soft_max=rmax, precision=1, step=1.0, subtype='ANGLE')


def create_trackball_property(item, prop, targets):
    vec = (0.0, 0.0, 1.0)
    item[prop] = vec
    item.id_properties_ensure()
    item['Trackball'] = not targets
    pt_property = item.id_properties_ui(prop)
    pt_property.update(default=vec, min=-1.0, max=1.0, soft_min=-1.0, soft_max=1.0, precision=8, step=0.00001, subtype='DIRECTION')


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
    dmx_mode = None
    dmx_channels = []
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(gdtf_profile, mode)

    if dmx_mode:
        root_geometry = pygdtf.utils.get_geometry_by_name(gdtf_profile, dmx_mode.geometry)
    else:
        root_geometry = None
    device_channels = pygdtf.utils.get_channels_for_geometry(gdtf_profile, root_geometry, dmx_mode.dmx_channels, [])

    for channel, geometry in device_channels:
        channel_range = []
        feature = str(channel.logical_channels[0].attribute)
        functions = channel.logical_channels[0].channel_functions
        if len(functions):
            channel_range += [functions[0].physical_from, functions[0].physical_to]
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
            if len(channel_range) and (channel_range[0] != channel_range[-1]):
                rangeData.setdefault(geometry.name, []).extend(channel_range)

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
    path = os.path.join(primitive_path, f"{primitive}.3ds")
    load_3ds(path, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)
    obj = bpy.context.view_layer.objects.selected[0]
    obj.users_collection[0].objects.unlink(obj)
    obj.data.transform(mathutils.Matrix.Diagonal((model.length / obj.dimensions.x,
                                                  model.width / obj.dimensions.y,
                                                  model.height / obj.dimensions.z)).to_4x4())
    return obj


def load_open_gobo(node):
    open_gobo = bpy.data.images.get("open.png", False)
    if not open_gobo:
        gobo_path = os.path.join(get_folder_path(), "primitives", "open.png")
        open_gobo = bpy.data.images.load(gobo_path)
    node.image = open_gobo


def create_udim_tiles(context, gobos):
    start_tile = 1001
    ctx_area = context.area
    image_amount = len(gobos)
    screens = bpy.data.screens
    img_screen = next(scr for scr in screens if any(ar.ui_type == 'IMAGE_EDITOR' for ar in scr.areas))
    img_area = next(era for scr in screens for era in scr.areas if era.ui_type == 'IMAGE_EDITOR')
    img_region = next((reg for reg in img_area.regions if reg.type == 'WINDOW'), False)

    if not img_region:
        img_region = img_area.regions[0]

    current = img_area.spaces.active.image
    for idx, gobo in enumerate(gobos, 1002):
        if gobo.source != 'TILED':
            gobo.source = 'TILED'
            img_area.spaces.active.image = gobo
            with context.temp_override(screen=img_screen, area=img_area, region=img_region):
                bpy.ops.image.tile_add(number=start_tile, count=image_amount)
            tile = gobo.tiles.get(idx)
            if tile is not None:
                gobo.tiles.remove(tile)
            gobo.tiles.new(idx)
            gobo_tile = gobo.tiles.get(idx)
            first = gobo.tiles.get(start_tile)
            if first is not None:
                gobo.tiles.remove(first)

    if current is not None:
        img_area.spaces.active.image = current


def extract_gobos(profile, fixturename):
    name = create_fixture_name(fixturename)
    gdtf_path = os.path.join(get_folder_path(), name)
    open_path = os.path.join(get_folder_path(), "primitives", "open.png")
    images_path = os.path.join(gdtf_path, "wheels")
    gobos_path = os.path.join(gdtf_path, "gobos")
    open_image = Path(open_path)
    open_destination = Path(gobos_path, f"{name}_gobo-{1:04}{open_image.suffix}")
    for image_name in profile._package.namelist():
        if image_name.startswith("wheels"):
            profile._package.extract(image_name, gdtf_path)
    if not os.path.isdir(gobos_path):
        os.makedirs(gobos_path)
    count = 0
    first = str(open_destination.resolve())
    open_destination.write_bytes(open_image.read_bytes())
    for idx, image in enumerate(Path(images_path).rglob('*'), 2):
        destination = Path(gobos_path, f"{name}_gobo-{idx:04}{image.suffix}")
        destination.write_bytes(image.read_bytes())
        count = idx
    sequence = bpy.data.images.load(first)
    sequence.source = 'SEQUENCE'
    sequence['Count'] = count
    return sequence


def collect_gobos(fixturename):
    gobos = []
    name = create_fixture_name(fixturename)
    folder_path = os.path.join(get_folder_path(), name)
    gobos_path = os.path.join(folder_path, "gobos")
    files = [fl for fl in os.listdir(gobos_path) if os.path.isfile(os.path.join(gobos_path, fl))]
    files.pop(0)
    for idx, file in enumerate(files):
        gobo_path = os.path.join(gobos_path, file)
        tile_name = f"{name}_slot{idx:03}"
        if tile_name in bpy.data.images:
            gobo = bpy.data.images.get(tile_name)
        else:
            gobo = bpy.data.images.load(gobo_path)
            gobo.name = tile_name
            with bpy.context.temp_override(id=gobo):
                bpy.ops.ed.lib_id_load_custom_preview(filepath=gobo_path)
        gobos.append(gobo)
    files.clear()
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


def load_2d(profile, name):
    folder_path = os.path.join(get_folder_path(), name, "symbols")
    filename = f"{profile.thumbnail}.svg"
    obj = None
    if filename in profile._package.namelist():
        profile._package.extract(filename, folder_path)
        bpy.ops.wm.gpencil_import_svg(filepath="", directory=folder_path, files=[{"name": filename}], scale=1)
    if obj is not None:
        obj.name = '2D Symbol'
        if len(obj.users_collection):
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
            if ob.data.get('Model Type') == 'glb':
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

    if model.file.extension.lower() == '3ds':
        inside_zip_path = f"models/3ds/{model.file.name}.{model.file.extension}"
        file_name = os.path.join(folder_path, inside_zip_path)
        try:
            profile._package.extract(inside_zip_path, folder_path)
            load_3ds(file_name, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)
            for ob in bpy.context.selected_objects:
                ob.data['Model Type'] = model.file.extension.lower()
        except:
            alternative = load_blender_primitive(model)
            bpy.context.view_layer.active_layer_collection.collection.objects.link(alternative)
            alternative.select_set(True)
    else:
        inside_zip_path = f"models/gltf/{model.file.name}.{model.file.extension}"
        profile._package.extract(inside_zip_path, folder_path)
        file_name = os.path.join(folder_path, inside_zip_path)
        bpy.ops.import_scene.gltf(filepath=file_name)
        for ob in bpy.context.selected_objects:
            ob.data['Model Type'] = model.file.extension.lower()
    objects = list(bpy.context.selected_objects)

    # if the model is made up of multiple parts we must join them
    obj = join_parts_apply_transforms(objects)
    obj.rotation_mode = 'XYZ'
    scale_vector = obj.scale * obj_dimension
    factor = mathutils.Vector([scale_vector[val] / max(obj.dimensions[val], 1e-09) for val in range(3)])
    if obj.data.get('Model Type') == '3ds':
        obj.data.transform(mathutils.Matrix.Diagonal(factor).to_4x4())
    else:
        obj.scale = factor
    if obj.data:
        obj.data.name = model.file.name
    return obj


def build_collection(profile, name, fixture_id, uid, mode, BEAMS, TARGETS, CONES):
    """Create model collection."""

    objectDict = {}
    has_gobos = zoom_range = False
    fixturetype_id = profile.fixture_type_id
    collection = bpy.data.collections.new(name)
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(profile, mode)

    if dmx_mode is None:
        dmx_mode = profile.dmx_modes[0]
        mode = dmx_mode.name

    collection['Fixture ID'] = fixture_id
    create_gdtf_props(collection, name)
    collection['UUID'] = uid
    root_geometry = pygdtf.utils.get_geometry_by_name(profile, dmx_mode.geometry)
    dmx_channels = collect_dmx_channels(profile, mode)
    logical_channels = [channel for break_channels in dmx_channels for channel in break_channels]
    virtual_channels = pygdtf.utils.get_virtual_channels(profile, mode)

    for channel in logical_channels:
        if 'Gobo' in channel['ID']:
            has_gobos = True
        if 'Zoom' in channel['ID']:
            zoom_function = channel.get('Functions')
            zoom_range = zoom_function[0].physical_from, zoom_function[0].physical_to


    def load_geometries(geometry):
        """Load 3d models, primitives and shapes"""
        data_meshes = bpy.data.meshes
        data_objects = bpy.data.objects
        geometry_name = cleanup_name(geometry)
        geometry_class = geometry.__class__.__name__
        geometry_type = get_geometry_type_as_string(geometry)

        for ob in data_objects:
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
        if primitive == 'Undefined' or (model.file and model.file.name != "" and primitive != 'Pigtail'):
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
                if geometry_class == 'GeometryBeam':
                    if any(geometry.beam_type.value == x for x in ['None', 'Glow']):
                        geometry_type = 'Glow'
                    elif obj.data.materials:
                        obj.data.materials[0]['Fixture ID'] = fixture_id
                if obj.get('UUID') is None:
                    obj.data['Geometry Class'] = geometry_class
                    obj.data['Geometry Type'] = geometry_type
                    obj.data['Original Name'] = obj_name
                    obj.data['Model Name'] = mesh_name
                    obj.data['UUID'] = fixturetype_id
                if obj.data.materials:
                    for mtl in obj.data.materials:
                        mtl_name = mtl.name.split('.')[0]
                        if obj.get('UUID') is None:
                            create_gdtf_props(mtl, name)
                            mtl['Original Name'] = mtl_name
                            mtl['Model Name'] = mesh_name
                            mtl['UUID'] = fixturetype_id
            obj.name = geometry_name
            create_fixture_id(obj, fixture_id)
            create_gdtf_props(obj, name)

            if geometry_name == cleanup_name(root_geometry):
                obj['Fixture Mode'] = mode
                obj['Use Root'] = True
                obj.hide_select = False
            else:
                obj['Geometry Class'] = geometry_class
                obj['Geometry Type'] = geometry_type
                obj['Model Name'] = mesh_name
                obj['Original Name'] = geometry.name
                obj.hide_select = True
            if isinstance(geometry, pygdtf.GeometryReference):
                obj['Reference'] = str(geometry.geometry)
                obj['Geometry Type'] = obj.data.get('Geometry Type')
            elif hasattr(geometry, "reference_root"):
                obj['Reference'] = getattr(geometry, "reference_root")
            if str(model.primitive_type) == 'Pigtail':
                obj['Geometry Type'] = 'Pigtail'
            objectDict[cleanup_name(geometry)] = obj
            mb = obj.matrix_basis.copy()
            if obj.data.get('Model Type') == 'glb':
                obj.data.transform(mb) 
            for cld in obj.children:
                cld.matrix_local = mb @ cld.matrix_local
            obj.matrix_basis.identity()

        if hasattr(geometry, "geometries"):
            for sub_geometry in geometry.geometries:
                if hasattr(geometry, "reference_root"):
                    root_reference = getattr(geometry, "reference_root")
                    setattr(sub_geometry, "reference_root", root_reference)
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
        obj_child = objectDict.get(cleanup_name(geometry))
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
        lightname = name.split()[-1]
        data_lights = bpy.data.lights
        ctc = float(geometry.color_temperature)
        beam_angle = math.radians(geometry.beam_angle)
        obj_child = objectDict.get(cleanup_name(geometry))
        childname = obj_child.get('Original Name', obj_child.name.split('.')[0])
        obj_child['Fixture ID'] = obj_child.data['Fixture ID'] = fixture_id
        obj_child.data.name = '%s_Beam' % name
        if len(obj_child.data.materials):
            beam_mtl = obj_child.data.materials[0]
            beam_mtl['Fixture ID'] = fixture_id
            beam_mtl.name = '%s_Beam' % name
        beamname = f"{lightname}_{childname}"
        if not BEAMS or obj_child is None:
            return
        if fixture_id >= 1:
            if obj_child.data.get('Fixture ID') != fixture_id:
                emitter = obj_child.data.copy()
                emitter['Fixture ID'] = fixture_id
                obj_child.data = emitter
            beamname = f"ID{fixture_id}_{lightname}_{childname}"
            obj_child.data.name = f"ID{fixture_id}_{name}_Beam"
            obj_child['Geometry Type'] = obj_child.data['Geometry Type'] = "Beam"
            if len(obj_child.data.materials):
                emit_material = obj_child.data.materials[0]
                emit_material['Fixture ID'] = fixture_id
                emit_material.name = beamname
        if any(geometry.beam_type.value == x for x in ['None', 'Glow']):
            glowname = f"ID{fixture_id}_{name}_Glow" if fixture_id >= 1 else '%s_Glow' % name
            obj_child['Geometry Type'] = obj_child.data['Geometry Type'] = "Glow"
            obj_child.data.name = glowname
            if len(obj_child.data.materials):
                glow_material = obj_child.data.materials[0]
                glow_material.name = glowname
            return
        obj_child.visible_shadow = False
        light_data = data_lights.get(beamname)
        if light_data is None or light_data.get('Fixture Name') != lightname:
            light_data = data_lights.new(beamname, 'SPOT')
            create_gdtf_props(light_data, name)
            light_data.energy = geometry.luminous_flux
            light_data.diffuse_factor = max((default_factor / light_data.energy), 1.0)
            light_data.specular_factor = max(((default_factor * 2) / light_data.energy), 1.0)
            light_data.use_custom_distance = True
            light_data.cutoff_distance = 23
            light_data.spot_blend = calculate_spot_blend(geometry)
            light_data.spot_size = beam_angle
            light_data.shadow_soft_size = geometry.beam_radius * 0.1
            light_data.shadow_buffer_clip_start = 0.02
            light_data['Fixture ID'] = fixture_id
            light_data['UUID'] = fixturetype_id
            if CONES:
                light_data.show_cone = True
        light_object = bpy.data.objects.new('Spot', light_data)
        light_object.hide_select = True
        light_object.parent = obj_child
        create_gdtf_props(light_object, name)
        light_object['Focus'] = light_data['Focus'] = beam_angle
        light_object['Geometry Class'] = geometry.__class__.__name__
        light_object['Flux'] = light_data['Flux'] = obj_child['Flux'] = geometry.luminous_flux
        light_object['Light CTC'] = light_data['Temperature'] = obj_child['Temperature'] = ctc
        light_object['Radius'] = light_data['Radius'] = obj_child['Radius'] = geometry.beam_radius
        if zoom_range:
            create_range_property(obj_child, zoom_range, 'Range')
            create_range_property(light_object, beam_angle, 'Focus', zoom_range)
            create_range_property(light_data, beam_angle, 'Focus', zoom_range)
            create_range_property(light_object, zoom_range, 'Range')
            create_range_property(light_data, zoom_range, 'Range')
        obj_child.matrix_parent_inverse = light_object.matrix_world.inverted()
        create_transform_property(light_object)
        collection.objects.link(light_object)

        gobo_radius = 2.2 * 0.01 * math.tan(math.radians(geometry.beam_angle / 2))
        goboGeometry = SimpleNamespace(name=f"Gobo {geometry}", length=gobo_radius, width=gobo_radius,
                                       height=0, primitive_type='Plane', beam_radius=geometry.beam_radius)
        if has_gobos:
            light_data['Gobo'] = True
            light_data.shadow_buffer_clip_start = 0.001
            create_gobo(geometry, goboGeometry)
            if not light_data.use_nodes:
                light_data.use_nodes = True
                nodes = light_data.node_tree.nodes
                links = light_data.node_tree.links
                emit = nodes.get('Emission')
                emit.label = emit.name = 'Fixture'
                light_mix = nodes.new('ShaderNodeMixRGB')
                gobos_node = nodes.new('ShaderNodeTexImage')
                lightpath = nodes.new('ShaderNodeLightPath')
                light_normal = nodes.new('ShaderNodeNormal')
                color_temp = nodes.new('ShaderNodeBlackbody')
                light_uv = nodes.new('ShaderNodeNewGeometry')
                rota_node = nodes.new('ShaderNodeVectorRotate')
                layerweight = nodes.new('ShaderNodeLayerWeight')
                lightfalloff = nodes.new('ShaderNodeLightFalloff')
                lightcontrast = nodes.new('ShaderNodeBrightContrast')
                gobos_node.label = gobos_node.name = 'Gobos'
                rota_node.label = rota_node.name = 'Gobo Rotate'
                light_uv.label = light_uv.name = 'Light Orientation'
                color_temp.label = color_temp.name = 'Color Temperature'
                lightcontrast.label = lightcontrast.name = 'Light Contrast'
                light_mix.blend_type = 'SOFT_LIGHT'
                gobos_node.extension = 'EXTEND'
                rota_node.invert = True
                emit.location = (100, 300)
                light_mix.location = (-100, 360)
                light_uv.location = (-1160, 360)
                rota_node.location = (-800, 380)
                lightpath.location = (-980, 200)
                color_temp.location = (-300, 100)
                gobos_node.location = (-600, 400)
                layerweight.location = (-300, 380)
                light_normal.location = (-980, 380)
                lightfalloff.location = (-800, 220)
                lightcontrast.location = (-300, 240)
                color_temp.inputs[0].default_value = ctc
                links.new(lightfalloff.outputs[0], lightcontrast.inputs[2])
                links.new(gobos_node.outputs[0], lightcontrast.inputs[0])
                links.new(light_normal.outputs[0], layerweight.inputs[1])
                links.new(light_normal.outputs[1], layerweight.inputs[0])
                links.new(lightcontrast.outputs[0], light_mix.inputs[1])
                links.new(lightpath.outputs[9], lightcontrast.inputs[1])
                links.new(lightpath.outputs[8], lightfalloff.inputs[0])
                links.new(lightpath.outputs[7], lightfalloff.inputs[1])
                links.new(light_uv.outputs[3], light_normal.inputs[0])
                links.new(layerweight.outputs[1], light_mix.inputs[0])
                links.new(rota_node.outputs[0], gobos_node.inputs[0])
                links.new(color_temp.outputs[0], light_mix.inputs[2])
                links.new(light_uv.outputs[5], rota_node.inputs[0])
                links.new(layerweight.outputs[0], emit.inputs[1])
                links.new(light_mix.outputs[0], emit.inputs[0])
                for out in lightpath.outputs:
                    if not out.is_linked:
                        out.hide = True


    def create_laser(geometry):
        if cleanup_name(geometry) not in objectDict:
            return
        obj_child = objectDict[cleanup_name(geometry)]
        if 'Laser' not in obj_child.name.lower():
            obj_child.name = f"Laser {obj_child.name}"
        obj_child['Diameter'] = geometry.beam_diameter
        obj_child.visible_shadow = False
        obj_child.rotation_mode = 'XYZ'


    def create_gobo(geometry, goboGeometry):
        geometry_class = geometry.__class__.__name__
        goboname = f"ID{fixture_id}_{name}_Gobo" if fixture_id >= 1 else f"{name}_Gobo"
        msh = bpy.data.meshes.get(goboname)
        if msh and msh.get('Geometry Type') == 'Gobo' and msh.get('UUID') == fixturetype_id:
            obj = bpy.data.objects.new(goboname, msh)
        else:
            obj = load_blender_primitive(goboGeometry)
            obj.data['UUID'] = fixturetype_id
        create_gdtf_props(obj, name)
        obj['Geometry Class'] = obj.data['Geometry Class'] = geometry_class     
        obj['Geometry Type'] = obj.data['Geometry Type'] = 'Gobo'
        obj['Radius'] = obj.data['Radius'] = goboGeometry.beam_radius
        obj.dimensions = (goboGeometry.length, goboGeometry.width, 0)
        obj.name = obj.data.name = goboGeometry.name
        objectDict[cleanup_name(goboGeometry)] = obj
        constraint_child_to_parent(geometry, goboGeometry)


    def calculate_spot_blend(geometry):
        """Return spot_blend value based on beam_type."""
        beam_type = geometry.beam_type.value
        if any(beam_type == x for x in ['Wash', 'Fresnel', 'PC']):
            return 1.0
        return 0.0


    def add_child_position(geometry):
        """Add a child position."""
        obj_child = objectDict.get(cleanup_name(geometry))
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
        """Recursively update objects position, rotation and scale."""
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
                    if hasattr(geometry, "reference_root"):
                        root_reference = getattr(geometry, "reference_root")
                        setattr(child_geometry, "reference_root", root_reference)
                    constraint_child_to_parent(geometry, child_geometry)
                    update_geometry(child_geometry)


    load_geometries(root_geometry)
    update_geometry(root_geometry)


    def get_axis_objects(attribute):
        axis_objects = []
        for obj in objectDict.values():
            feature = channelData.get(obj.get('Original Name'))
            axisrange = rangeData.get(obj.get('Original Name'))
            if feature == attribute:
                obj['Mobile Axis'] = feature
                obj['Geometry Type'] = 'Axis'
                create_range_property(obj, tuple(axisrange), 'Range')
                axis_objects.append(obj)
        return axis_objects


    def check_center_object(obj):
        return (abs(round(obj.location.x, 1)) == 0.0 and abs(round(obj.location.y, 1)) == 0.0)


    yokes = get_axis_objects('Pan')
    heads = get_axis_objects('Tilt')
    base = next(ob for ob in objectDict.values() if ob.get('Use Root'))
    moving_objects = [ob for ob in objectDict.values() if ob.get('Geometry Type') == 'Axis']

    if TARGETS:
        target_uid = str(pyuid.uuid4())
        data_objects = bpy.data.objects
        main_target = bpy.data.objects.new('Target', None)
        main_target.empty_display_size = 0.4
        collection.objects.link(main_target)
        create_fixture_id(main_target, fixture_id)
        create_gdtf_props(main_target, name)
        main_target['Geometry Type'] = 'Target'
        main_target['UUID'] = target_uid
        targetData[target_uid] = main_target

    for idx, obj in enumerate(moving_objects):
        center_object = check_center_object(obj)
        check_pan = obj.get('Mobile Axis') == 'Pan'
        check_tilt = obj.get('Mobile Axis') == 'Tilt'
        center_parent = obj.parent and check_center_object(obj.parent)
        check_parent = obj.parent and obj.parent.get('Mobile Axis') in {'Pan', 'Tilt'}
        check_master = check_parent and obj.parent.parent and obj.parent.parent.get('Mobile Axis') in {'Pan', 'Tilt'}
        if TARGETS:
            if not len(base.constraints) and (check_pan and not len(obj.children) or (not check_pan and not check_tilt)):
                track_constraint = base.constraints.new('TRACK_TO')
                track_constraint.target = main_target
                continue
            else:
                lock_constraint = obj.constraints.new('LOCKED_TRACK')
            if check_tilt or check_master:
                lock_constraint.track_axis = 'TRACK_NEGATIVE_Z'
            else:
                lock_constraint.track_axis = 'TRACK_NEGATIVE_Y'
            if check_tilt:
                lock_constraint.lock_axis = 'LOCK_X'
            else:
                lock_constraint.lock_axis = 'LOCK_Z'
            if center_object and center_parent:
                lock_constraint.target = main_target
                obj['Target ID'] = target_uid
            else:
                if obj.parent and len(obj.parent.children) > 1:
                    if not center_object or (center_object and not center_parent):
                        target_name = 'Target %s' % obj.name
                        obj_target = bpy.data.objects.new(target_name, None)
                        obj_target.empty_display_type = 'SINGLE_ARROW'
                        obj_target.empty_display_size = 0.2
                        obj_target.parent = main_target
                        create_fixture_id(obj_target, fixture_id)
                        create_gdtf_props(obj_target, name)
                        obj_target['Geometry Class'] = 'Target'
                        obj_target['Reference'] = obj.get('Original Name', obj.name)
                        collection.objects.link(obj_target)
                        if not center_object:
                            obj_target.location = (obj.location.x, obj.location.y, 0)
                        elif center_object and not center_parent:
                            obj_target.location = (obj.parent.location.x, obj.parent.location.y, 0)
                        create_transform_property(obj_target)
                        lock_constraint.target = obj_target
        limit_constraint = obj.constraints.new('LIMIT_ROTATION')
        range_min = math.radians(min(rangeData.get(obj.get('Original Name'))))
        if check_master:
            obj['Sub Axis'] = True
            limit_constraint.owner_space = 'LOCAL'
        if check_tilt:
            limit_constraint.use_limit_x = True
            limit_constraint.max_x = range_min
        else:
            limit_constraint.use_limit_z = True
            limit_constraint.max_z = range_min
    if TARGETS and not yokes and not heads and not len(base.constraints):
        track_constraint = base.constraints.new('TRACK_TO')
        track_constraint.target = main_target
    
    # 2D thumbnail planning symbol
    obj = load_2d(profile, name)
    if obj is not None:
        obj['2D Symbol'] = "all"
        objectDict['2D Symbol'] = obj
        obj.show_in_front = True
        if obj.active_material.grease_pencil:
            obj.active_material.grease_pencil.show_stroke = True

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
        if obj.get('Use Root', False):
            return obj


def get_tilt(model_collection, channels):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        for channel in channels:
            if 'Tilt' == channel.get('ID') and channel.get('Geometry') == obj.get('Original Name', 'None'):
                return obj


def fixture_build(context, filename, mscale, name, position, focus_point, fixture_id,
                  gelcolor, collect, fixture, TARGETS=True, BEAMS=True, CONES=False):

    viewlayer = context.view_layer
    object_data = bpy.data.objects
    data_collect = bpy.data.collections
    layer_collect = viewlayer.layer_collection
    gdtf_profile = pygdtf.FixtureType(filename)
    fixture_name = create_fixture_name(name)
    has_gobos = is_mover = zoom_range = False
    gobo_material = random_gobo = None
    uid = gdtf_profile.fixture_type_id
    mode = FixtureMode(gdtf_profile)
    channels = []

    if fixture:
        uid = fixture.uuid
        mode = fixture.gdtf_mode
        color = convert_color(gelcolor)
        gelcolor = list(int((255/1)*i) for i in color[:3])

    def index_name(device):
        device_name = device
        if fixture_id > 0:
            device_name = 'ID%d %s' % (fixture_id, device.split('.')[0])
        return device_name

    # Remove Collection if same index
    index_collection = next((col for col in data_collect if col.get('Fixture ID') == fixture_id), False)
    if index_collection:
        for obj in index_collection.objects:
            if obj.get('Use Root'):
                position = obj.matrix_world.copy()
            if obj.get('Geometry Type') == 'Target':
                focus_point = obj.matrix_world.copy()
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
    virtual_channels = pygdtf.utils.get_virtual_channels(gdtf_profile, mode)

    for channel in channels:
        if 'Gobo' in channel['ID']:
            has_gobos = True
        if 'Zoom' in channel['ID']:
            zoom_function = channel.get('Functions')
            zoom_range = zoom_function[0].physical_from, zoom_function[0].physical_to

    for virtual in virtual_channels:
        if 'Gobo' in virtual['id']:
            has_gobos = True
        if 'Zoom' in virtual['id']:
            zoom_function = channel.get('Functions')
            zoom_range = zoom_function[0].physical_from, zoom_function[0].physical_to

    gobos = []
    linkDict = {}
    start_gobo = None
    random_glow = [random.uniform(0.0, 1.0) for _ in range(3)]
    base = get_root_model(model_collection)
    head = get_tilt(model_collection, channels)
    if has_gobos:
        start_gobo = extract_gobos(gdtf_profile, name)
        gobos.extend(collect_gobos(name))
        create_udim_tiles(context, gobos)
        random_gobo = float(random.randint(0, len(gobos)))

    if model_collection:
        root_object = None
        zoom_angle = color_ctc = multi_mover = False
        collection_name = model_collection.get('Fixture Name')
        if collect is None:
            if model_collection.name not in layer_collect.collection.children:
                layer_collect.collection.children.link(model_collection)
            active_layer = layer_collect.children.get(model_collection.name)
        print("creating fixture... %s" % model_collection.name)
        for obj in model_collection.objects:
            linkDict[obj.name] = obj
            viewlayer.objects.active = obj
            multi_mover = obj.get('Sub Axis', False)
            if TARGETS and len(obj.constraints):
                target = obj.get('Target ID')
                locked = obj.constraints.get('Locked Track')
                if locked is not None:
                    for child in obj.children:
                        locked_child = child.constraints.get('Locked Track')
                        if locked_child and locked_child.target is None:
                            locked_child.target = obj.constraints[0].target
                    if target:
                        locked.target = targetData.get(target)
            if obj.type == 'LIGHT':
                light_object = obj
                obj.hide_select = True
                obj.matrix_world = obj.matrix_world @ obj.parent.matrix_local.inverted()
                zoom_angle = obj.get('Focus')
                color_ctc = obj.get('Temperature')
                create_range_property(obj, zoom_angle, 'Focus')
                create_range_property(obj.data, zoom_angle, 'Focus', zoom_range)
                create_ctc_property(obj, color_ctc, 'Temperature')
                create_ctc_property(obj.data, color_ctc, 'Color Temperature')
                obj['UUID'] = uid
            if obj.get('Use Root'):
                root_object = obj
                if zoom_range and zoom_angle:
                    create_range_property(obj, zoom_angle, 'Focus Zoom', zoom_range)
                if has_gobos and random_gobo is not None:
                    obj['Gobo Select'] = random_gobo
                    create_gobo_property(obj, float(len(gobos)))
                create_dimmer_property(obj)
                obj['Target'] = TARGETS
                obj.id_properties_ensure()
                target_property = obj.id_properties_ui('Target')
                target_property.update(default=TARGETS)
                create_color_property(obj, gelcolor, 'RGB Beam')
                if color_ctc:
                    create_ctc_property(obj, color_ctc, 'Light CTC')
                ob_name = fixture_name if fixture is None else name
                obj.matrix_world = position @ obj.matrix_world.copy()
                obj.name = index_name(ob_name)
                create_transform_property(obj)
                obj['UUID'] = uid
            elif obj.get('Geometry Type') == 'Gobo':
                obj.select_set(False)
                obj.hide_select = True
                obj.scale = (1.0, 1.0, 1.0)
                wheelname = 'ID%d_%s_Wheel' % (fixture_id, fixture_name) if fixture_id >=1 else '%s_Wheel' % fixture_name
                if len(obj.data.materials):
                    wheel_material = obj.data.materials[0]
                    wheel_material.name = wheelname
                else:
                    wheel_material = bpy.data.materials.get(wheelname)
                if wheel_material is None or wheel_material.get('Fixture ID') != fixture_id:
                    wheel_material = bpy.data.materials.new(wheelname)
                    obj.data.materials.append(wheel_material)
                obj.active_material = wheel_material
                create_gdtf_props(wheel_material, fixture_name)
                wheel_material['Geometry Type'] = 'Gobo'
                wheel_material['Fixture ID'] = fixture_id
                wheel_material['UUID'] = uid
                wheel_material.shadow_method = 'CLIP'
                wheel_material.blend_method = 'BLEND'
            elif obj.get('Geometry Type') == 'Beam' and obj.type == 'MESH':
                obj.hide_select = True
                beamname ='ID%d_%s_Beam' % (fixture_id, fixture_name) if fixture_id >= 1 else '%s_Beam' % fixture_name
                if len(obj.data.materials):
                    emit_material = obj.data.materials[0]
                    emit_material['Fixture ID'] = fixture_id
                    emit_material.name = beamname
                else:
                    emit_material = bpy.data.materials.get(beamname)
                if emit_material is None or emit_material.get('Fixture ID') != fixture_id:
                    emit_material = bpy.data.materials.new(beamname)
                    obj.data.materials.append(emit_material)
                obj.active_material = emit_material
                create_gdtf_props(emit_material, fixture_name)
                emit_material['Fixture ID'] = fixture_id
                emit_material.shadow_method = 'NONE'
                emit_material['Geometry Type'] = 'Beam'
                emit_shader = PrincipledBSDFWrapper(emit_material, is_readonly=False, use_nodes=True)
                emit_shader.emission_strength = 1.0
                emit_shader.emission_color = gelcolor[:]
            elif obj.get('Geometry Type') == 'Glow' and obj.type == 'MESH':
                obj.hide_select = True
                glowname ='ID%d_%s_Glow' % (fixture_id, fixture_name) if fixture_id >= 1 else '%s_Glow' % fixture_name
                if len(obj.data.materials):
                    glow_material = obj.data.materials[0]
                else:
                    glow_material = bpy.data.materials.get(glowname)
                if glow_material is None or glow_material.get('Fixture ID') != fixture_id:
                    obj.data.materials.clear()
                    glow_material = bpy.data.materials.new(glowname)
                    obj.data.materials.append(glow_material)
                obj.active_material = glow_material
                create_gdtf_props(glow_material, fixture_name)
                glow_material['Fixture ID'] = fixture_id
                glow_material.shadow_method = 'NONE'
                glow_material['Geometry Type'] = 'Glow'
                glow_shader = PrincipledBSDFWrapper(glow_material, is_readonly=False, use_nodes=True)
                glow_shader.emission_strength = 1.0
                glow_shader.emission_color = random_glow[:]
            elif obj.get('Geometry Type') == 'Target':
                obj.name = index_name(obj.name)
                obj.matrix_world = focus_point
                create_transform_property(obj)
            elif obj.get('2D Symbol', None) == "all":
                obj.name = index_name('2D Symbol')
                obj.hide_viewport = True
                obj.hide_render = True
                obj.hide_set(True)

        for obj in model_collection.objects:
            for child in obj.children:
                if child.name in linkDict:
                    linkDict[child.name].parent = obj
                child.name = index_name(child.name)
            if obj.type == 'LIGHT':
                beam_angle = obj.get('Focus')
                create_dimmer_driver(obj.data, root_object, obj)
                create_color_driver(obj.data, root_object, 'RGB Beam')
                if zoom_range and beam_angle:
                    create_zoom_driver(obj.data, root_object)
                if len(gobos) and start_gobo is not None:
                    obj.location[2] += 0.01
                    nodes = obj.data.node_tree.nodes
                    links = obj.data.node_tree.links
                    emit = nodes.get('Fixture')
                    gobos_node = nodes.get('Gobos')
                    light_map = nodes.get('Gobo Map')
                    rota_node = nodes.get('Gobo Rotate')
                    light_comb = nodes.get('Gobo Select')
                    light_node = nodes.get('Light Output')
                    lightfalloff = nodes.get('Light Falloff')
                    gobos_node.image = start_gobo
                    gobos_node.color_mapping.blend_type = 'LINEAR_LIGHT'
                    emit.inputs[0].default_value[:3] = gelcolor[:]
                    create_gobo_driver(rota_node, root_object)
                    img_user = gobos_node.image_user
                    img_user.frame_duration = len(gobos)
                    seq_curve = img_user.driver_add("frame_offset")
                    seq_drive = seq_curve.driver
                    seq_drive.type = 'AVERAGE'
                    seq_var = seq_drive.variables.new()
                    seq_var.name = "gobo_select"
                    seq_target = seq_var.targets[0]
                    seq_target.id = root_object
                    seq_target.data_path = '["Gobo Select"]'
                    if color_ctc:
                        ctc_node = nodes.get('Color Temperature')
                        ctc_curve = ctc_node.inputs[0].driver_add("default_value")
                        ctc_drive = ctc_curve.driver
                        ctc_drive.type = 'AVERAGE'
                        ctc_var = ctc_drive.variables.new()
                        ctc_var.name = "light_ctc"
                        ctc_target = ctc_var.targets[0]
                        ctc_target.id = root_object
                        ctc_target.data_path = '["Light CTC"]'
                elif obj.parent and obj.parent.parent and obj.parent.parent.dimensions.z < 0.05:
                    obj.location[2] += -0.02
            elif obj.type == 'MESH' and len(obj.data.materials):
                if obj.get('Geometry Type') == 'Beam':
                    beam_material = obj.data.materials[0]
                    beam_material.use_nodes = True
                    principled_node = beam_material.node_tree.nodes.get('Principled BSDF')
                    create_color_driver(principled_node.inputs['Emission Color'], root_object, 'RGB Beam')
                    create_dimmer_driver(principled_node.inputs['Emission Strength'], root_object, obj)
                elif obj.get('Geometry Type') == 'Glow':
                    glow_material = obj.data.materials[0]
                    glow_material.use_nodes = True
                    create_color_property(root_object, random_glow, 'RGB Glow')
                    principled_node = glow_material.node_tree.nodes.get('Principled BSDF')
                    create_color_driver(principled_node.inputs['Emission Color'], root_object, 'RGB Glow')
                    create_dimmer_driver(principled_node.inputs['Emission Strength'], root_object, obj)   
                elif obj.get('Geometry Type') == 'Gobo':
                    gobo_material = obj.data.materials[0]
                    if zoom_range and zoom_angle:
                        create_range_property(obj, zoom_angle, 'Focus', zoom_range)
                        create_zoom_driver(obj, root_object)
                    if not gobo_material.use_nodes:
                        gobo_material.use_nodes = True
                        gobo_nodes = gobo_material.node_tree.nodes
                        gobo_links = gobo_material.node_tree.links
                        material_node = gobo_nodes.get('Material Output')
                        principled_bsdf = gobo_nodes.get('Principled BSDF')
                        gobo_nodes.remove(principled_bsdf)
                        opacity_node = gobo_nodes.new('ShaderNodeBsdfTransparent')
                        opacity_node.label = opacity_node.name = 'Gobo Shader'
                        open_node = gobo_nodes.new('ShaderNodeTexImage')
                        gobo_comb = gobo_nodes.new('ShaderNodeCombineXYZ')
                        gobo_rota = gobo_nodes.new('ShaderNodeVectorRotate')
                        gobo_cord = gobo_nodes.new('ShaderNodeTexCoord')
                        gobo_slot = gobo_nodes.new('ShaderNodeMapping')
                        gobo_cord.label = gobo_cord.name = 'Gobo Coordinate'
                        gobo_rota.label = gobo_rota.name = 'Gobo Rotate'
                        gobo_comb.label = gobo_comb.name = 'Gobo Select'
                        gobo_slot.label = gobo_slot.name = 'Gobo Map'
                        open_node.label = open_node.name = 'Open'
                        create_gobo_driver(gobo_rota, root_object, gobo_comb)
                        previous_node = open_node
                        load_open_gobo(open_node)
                        open_node.extension = 'EXTEND'
                        gobo_slot.location = (-660, 280)
                        open_node.location = (-420, 360)
                        gobo_rota.location = (-860, 300)
                        gobo_cord.location = (-1060, 300)
                        opacity_node.location = (100, 300)
                        gobo_slot.inputs[2].hide = gobo_slot.inputs[3].hide = True
                        gobo_links.new(opacity_node.outputs[0], material_node.inputs[0])
                        gobo_links.new(open_node.outputs[0], opacity_node.inputs[0])
                        gobo_links.new(gobo_rota.outputs[0], gobo_slot.inputs[0])
                        gobo_links.new(gobo_slot.outputs[0], open_node.inputs[0])
                        gobo_links.new(gobo_cord.outputs[0], gobo_rota.inputs[0])
                        gobo_links.new(gobo_comb.outputs[0], gobo_slot.inputs[1])
                        for idx, gobo_img in enumerate(gobos, 1):
                            node_align = int((idx - 1) * 280)
                            gobo_node = gobo_nodes.get('Gobo %d' % idx, False)
                            gobo_mix = gobo_nodes.get('Gobo Mix %d' % idx, False)
                            if not gobo_mix:
                                gobo_mix = gobo_nodes.new('ShaderNodeMixRGB')
                                gobo_mix.label = gobo_mix.name = 'Gobo Mix %d' % idx
                                gobo_mix.inputs[2].default_value[:3] = gelcolor[:]
                                gobo_mix.location = (-80 + node_align, 340)
                                gobo_mix.blend_type = 'ADD'
                            if not gobo_node:
                                gobo_node = gobo_nodes.new('ShaderNodeTexImage')
                                gobo_node.label = gobo_node.name = 'Gobo %d' % idx
                                gobo_node.location = (-420 + node_align, 80)
                                gobo_node.image = gobo_img
                            opacity_node.location = (100 + node_align, 300)
                            material_node.location = (300 + node_align, 300)
                            gobo_links.new(previous_node.outputs[0], gobo_mix.inputs[1])
                            gobo_links.new(gobo_mix.outputs[0], opacity_node.inputs[0])
                            gobo_links.new(gobo_node.outputs[0], gobo_mix.inputs[2])
                            gobo_links.new(gobo_slot.outputs[0], gobo_node.inputs[0])
                            previous_node = gobo_mix
                else:
                    for mtl in obj.data.materials:
                        obj_name = obj.get('Fixture Name', obj.name)
                        split_name = mtl.name.split('.')[0]
                        mtl_name = split_name.split('_')[-1]
                        mtl.name = '%s_%s' % (obj_name, mtl_name)
            if obj.get('Use Root'):
                if is_mover and obj.get('Movement') is None:
                    create_trackball_property(obj, 'Movement', TARGETS)
                if multi_mover and obj.get('Position') is None:
                    create_trackball_property(obj, 'Position', TARGETS)
                for parents in obj.children_recursive:
                    if len(parents.children) > 1:
                        for idx, childs in enumerate(parents.children, 1):
                            if len(childs.children) > 1:
                                for i, child in enumerate(childs.children, 1):
                                    child_name = child.name.split('.')[0]
                                    child.name = '%s %d' % (child_name, i)
                            else:
                                for child in childs.children_recursive:
                                    child_name = child.name.split('.')[0]
                                    child.name = '%s %d' % (child_name, idx)
            if obj.get('Geometry Type') == 'Axis':
                check_sub_axis = obj.get('Sub Axis')
                check_root = root_object.get('Movement')
                if check_root is None:
                    create_trackball_property(root_object, 'Movement', TARGETS)
                if check_sub_axis is None:
                    create_trackball_driver(obj, root_object, 'Movement')
                else:
                    check_root = root_object.get('Position')
                    if check_root is None:
                        create_trackball_property(root_object, 'Position', TARGETS)
                    create_trackball_driver(obj, root_object, 'Position') 
                obj.hide_select = True
                obj['UUID'] = uid

        for obj in layer_collect.collection.all_objects:
            if obj.get('UUID') == uid or (obj.get('Geometry Type') == 'Target' and obj.get('Fixture Name') == collection_name):
                obj.select_set(False) if obj.hide_select else obj.select_set(True)


def load_gdtf(context, filename, mscale, name, position, focus_point, fixture_id,
              gelcolor, collect, fixture, TARGETS=True, BEAMS=True, CONES=False):

    targetData.clear()
    channelData.clear()

    context.scene.cycles.preview_pause = True
    fixture_build(context, filename, mscale, name, position, focus_point,
                  fixture_id, gelcolor, collect, fixture, TARGETS, BEAMS, CONES)

    targetData.clear()
    channelData.clear()
    context.scene.cycles.preview_pause = False


def load_prepare(context, filename, global_matrix, collect, align_objects, align_axis, scale_objects,
                 fixture_index, fixture_count, gel_color, device_position, TARGETS, BEAMS, CONES):

    name = Path(filename).stem
    mscale = mathutils.Matrix.Scale(scale_objects, 4)

    if global_matrix is not None:
        mscale = global_matrix @ mscale

    for idx in range(fixture_index, fixture_index + fixture_count):
        count = idx - fixture_index
        distribution = count * align_objects
        align = 0.5 * (fixture_count * align_objects) - (0.5 * align_objects)
        spread = (device_position[0] + (distribution - align), device_position[1], device_position[2])
        if align_axis == 'Y':
            spread = (device_position[0], device_position[1] + (distribution - align), device_position[2])
        elif align_axis == 'Z':
            spread = (device_position[0], device_position[1], device_position[2] + (distribution - align))
        position = mathutils.Matrix.Translation(spread)
        focus_point = mathutils.Matrix.Translation((spread[0], spread[1], 0))
        load_gdtf(context, filename, mscale, name, position, focus_point,
                  idx, gel_color, collect, None, TARGETS, BEAMS, CONES)


def load(operator, context, files=None, directory="", filepath="", fixture_index=0, fixture_count=1,
         align_axis={'X'}, align_objects=1.0, scale_objects=1.0, gel_color=[1.0, 1.0, 1.0], device_position=None,
         use_collection=False, use_targets=True, use_beams=True, use_show_cone=False, global_matrix=None):

    context.window.cursor_set('WAIT')
    default_layer = context.view_layer.active_layer_collection.collection
    if device_position is None:
        device_position = [0.0, 0.0, 1.0]

    for fl in files:
        collect = None
        if use_collection:
            collect = bpy.data.collections.new(Path(fl.name).stem)
            context.scene.collection.children.link(collect)
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collect.name]
        load_prepare(context, os.path.join(directory, fl.name), global_matrix, collect, align_objects,
                     align_axis, scale_objects, fixture_index, fixture_count, gel_color, device_position,
                     TARGETS=use_targets, BEAMS=use_beams, CONES=use_show_cone)

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
