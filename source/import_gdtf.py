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
import pathlib
import mathutils
import traceback
import uuid as pyuid
from types import SimpleNamespace
from io_scene_3ds.import_3ds import load_3ds
from bpy_extras.image_utils import load_image
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from pathlib import Path

targetData = {}


def get_folder_path():
    FOLDER_PATH = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(FOLDER_PATH, "fixture_profiles")


def get_profile_list(directory):
    profiles = []
    for file in os.listdir(directory):
        # Parse info from file name: Company@Model.gdtf
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
    print('splitname', split_name)
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
    rotate = mtx_copy.transposed().to_3x3()
    trans_mtx = rotate[0][:]+rotate[1][:]+rotate[2][:]+translate[:]
    obj['Transform'] = trans_mtx


def trans_matrix(trans_mtx):
    trans = list(trans_mtx)
    matrix = mathutils.Matrix((trans[:3]+[0], trans[3:6]+[0], trans[6:9]+[0], trans[9:]+[1])).transposed()
    return matrix


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
    if primitive == "Cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == "Pigtail":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif primitive == "Plane":
        bpy.ops.mesh.primitive_plane_add(size=1.0)
    elif primitive == "Cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1.0)
    elif primitive == "Sphere":
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
    obj.data.transform(mathutils.Matrix.Diagonal((model.length / obj.dimensions.x, model.width / obj.dimensions.y, model.height / obj.dimensions.z)).to_4x4())
    return obj


def extract_gobos(profile):
    """now unused as we need sequences for keyframe animating"""
    gobos = []
    directory = os.path.dirname(os.path.realpath(__file__))
    folder = os.path.join(directory, "fixture_profiles")
    folder_path = os.path.join(folder, profile.fixture_type_id)
    for image_name in profile._package.namelist():
        if image_name.startswith("wheels"):
            short_name = image_name.replace("wheels/", "", 1)
            if short_name in bpy.data.images:
                image = bpy.data.images[short_name]
            else:
                profile._package.extract(image_name, folder_path)
                image_path = os.path.join(folder_path, image_name)
                image = bpy.data.images.load(image_path)
            image["Content Type"] = "Image"
            # TODO: we could add gobo names from Wheels
            gobo = {"name": image_name, "image": image}
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


def extract_gobos_as_sequence(profile):
    directory = os.path.dirname(os.path.realpath(__file__))
    folder = os.path.join(directory, "fixture_profiles")
    gdtf_path = os.path.join(folder, profile.fixture_type_id)
    images_path = os.path.join(gdtf_path, "wheels")
    sequence_path = os.path.join(gdtf_path, "sequence")
    for image_name in profile._package.namelist():
        if image_name.startswith("wheels"):
            profile._package.extract(image_name, gdtf_path)
    if not os.path.isdir(sequence_path):
        os.makedirs(sequence_path)
    first = ""
    count = 0
    for idx, image in enumerate(pathlib.Path(images_path).rglob("*"), start=1):
        destination = pathlib.Path(sequence_path, f"image_{idx:04}{image.suffix}")
        if idx == 1:
            first = str(destination.resolve())
        if idx == 256:  # more gobos then values on a channel, must stop
            break
        destination.write_bytes(image.read_bytes())
        count = idx
    if first:
        sequence = bpy.data.images.load(first)
    else:
        return None
    sequence["count"] = count
    return sequence


def load_2d(profile):
    current_path = os.path.dirname(os.path.realpath(__file__))
    profile_path = os.path.join(current_path, "fixture_profiles")
    folder_path = os.path.join(profile_path, profile.fixture_type_id, "symbols")
    filename = f"{profile.thumbnail}.svg"
    obj = None
    if filename in profile._package.namelist():
        profile._package.extract(filename, folder_path)
    else:
        # default 2D
        extract_to_folder_path = os.path.join(profile_path, profile.fixture_type_id, "primitives")
        filename = "thumbnail.svg"

    bpy.ops.wm.gpencil_import_svg(filepath="", directory=folder_path, files=[{"name": filename}], scale=1)
    if len(bpy.context.view_layer.objects.selected):
        obj = bpy.context.view_layer.objects.selected[0]
    if obj is not None:
        obj.name = "2D symbol"
        obj.users_collection[0].objects.unlink(obj)
        obj.rotation_euler[0] = math.radians(-90)
    return obj


def join_parts_apply_transforms(objs):
    join = 0
    single = None
    for ob in objs:
        mb = ob.matrix_basis  # apply some transforms
        if ob.type == "MESH" and ob.data.vertices.items():
            ob.select_set(True)  # objects for merging must be selected
            join += 1
            bpy.context.view_layer.objects.active = ob
            single = ob
            if hasattr(ob.data, "Transform"):  # glb files
                ob.data.transform(mb)
        ob.matrix_basis.identity()
    if join > 0:
        bpy.ops.object.join()  # join them together
        objs = list(bpy.context.view_layer.objects.selected)
    for obj in objs:
        obj.users_collection[0].objects.unlink(obj)
    if join == 1:
        objs = [single]  # if there was only a single object for merging
    for ob in objs:
        if ob.type == "MESH":
            obj = ob
            break

    return obj


def load_model(profile, model):
    current_path = os.path.dirname(os.path.realpath(__file__))
    profile_path = os.path.join(current_path, "fixture_profiles")
    folder_path = os.path.join(profile_path, profile.fixture_type_id)

    if model.file.extension.lower() == "3ds":
        inside_zip_path = f"models/3ds/{model.file.name}.{model.file.extension}"
        profile._package.extract(inside_zip_path, folder_path)
        file_name = os.path.join(folder_path, inside_zip_path)
        try:
            load_3ds(file_name, bpy.context, FILTER={'MESH'}, KEYFRAME=False, APPLY_MATRIX=False)
            for ob in bpy.context.selected_objects:
                ob.data.transform(mathutils.Matrix.Scale(0.001, 4))
        except Exception as e:
            bpy.ops.mesh.primitive_cube_add(size=0.1)
    else:
        inside_zip_path = f"models/gltf/{model.file.name}.{model.file.extension}"
        profile._package.extract(inside_zip_path, folder_path)
        file_name = os.path.join(folder_path, inside_zip_path)
        bpy.ops.import_scene.gltf(filepath=file_name)

    objs = list(bpy.context.selected_objects)
    # if the model is made up of multiple parts we must join them
    obj = join_parts_apply_transforms(objs)
    obj.rotation_mode = 'XYZ'
    dim_x = obj.dimensions.x or 1
    dim_y = obj.dimensions.y or 1
    dim_z = obj.dimensions.z or 1

    obj.scale = (obj.scale.x * model.length / dim_x, obj.scale.y * model.width / dim_y, obj.scale.z * model.height / dim_z)
    return obj


def build_collection(profile, name, mode, display_beams, add_target):
    # Create model collection
    collection = bpy.data.collections.new(name)
    objs = {}
    # Get root geometry reference from the selected DMX Mode
    dmx_mode = pygdtf.utils.get_dmx_mode_by_name(profile, mode)

    # Handle if dmx mode doesn't exist (maybe this is MVR import and GDTF files were replaced)
    if dmx_mode is None:
        dmx_mode = profile.dmx_modes[0]
        mode = dmx_mode.name

    root_geometry = pygdtf.utils.get_geometry_by_name(profile, dmx_mode.geometry)
    has_gobos = False

    dmx_channels = pygdtf.utils.get_dmx_channels(profile, mode)
    virtual_channels = pygdtf.utils.get_virtual_channels(profile, mode)
    # Merge all DMX breaks together
    dmx_channels_flattened = [channel for break_channels in dmx_channels for channel in break_channels]
    # dmx_channels_flattened contain list of channel with id, geometry

    for ch in dmx_channels_flattened:
        if "Gobo" in ch["id"]:
            has_gobos = True

    def load_geometries(geometry):
        """Load 3d models, primitives and shapes"""
        print(f"loading geometry {geometry.name}")

        data_meshes = bpy.data.meshes
        data_objects = bpy.data.objects
        if isinstance(geometry, pygdtf.GeometryReference):
            reference = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
            geometry.model = reference.model
            if hasattr(reference, "geometries"):
                for sub_geometry in reference.geometries:
                    setattr(sub_geometry, "reference_root", str(geometry.name))
                    load_geometries(sub_geometry)

        if geometry.model is None:
            model = pygdtf.Model(name=f"{geometry}", length=0.0001, width=0.0001, height=0.0001, primitive_type="Cube")
            geometry.model = ""
        else:
            # Deepcopy the model because GeometryReference will modify the name
            # Perhaps this could be done conditionally
            model = copy.deepcopy(pygdtf.utils.get_model_by_name(profile, geometry.model))
        if isinstance(geometry, pygdtf.GeometryReference):
            model.name = f"{geometry}"

        obj = None
        primitive = str(model.primitive_type)
        if primitive[-3:] == "1_1":
            primitive = primitive[:-3]
            model.primitive_type = pygdtf.PrimitiveType(primitive)

        # Prefer File first, as some GDTFs have both File and PrimitiveType
        if (str(model.primitive_type) == "Undefined") or (model.file is not None and model.file.name != "" and (str(model.primitive_type) != "Pigtail")):
            try:
                obj = load_model(profile, model)
            except Exception as exc:
                print("Error importing 3D model: %s" % exc)
                model.primitive_type = "Cube"
                obj = load_blender_primitive(model)
        # BlenderDMX primitives
        elif str(model.primitive_type) in ["Base", "Conventional", "Head", "Yoke"]:
            if str(model.primitive_type) in data_meshes:
                primesh = data_meshes.get(str(model.primitive_type))
                obj = data_objects.new(name + ' ' + str(model.primitive_type), primesh)
            else:
                obj = load_gdtf_primitive(model)
                obj.name = name + ' ' + str(model.primitive_type)
                obj.data.name = str(model.primitive_type)
        # Blender primitives
        else:
            if profile.fixture_type_id in data_meshes:
                primesh = data_meshes.get(profile.fixture_type_id)
                obj = data_objects.new(name + ' ' + str(model.primitive_type), primesh)
            else:
                obj = load_blender_primitive(model)
                obj.name = name + ' ' + str(model.primitive_type)
                obj.data.name = profile.fixture_type_id

        # If object was created
        if obj is not None:
            if cleanup_name(geometry) == cleanup_name(root_geometry):
                obj["Root Geometry"] = True
                obj.hide_select = False
            else:
                obj.hide_select = True
            obj.name = cleanup_name(geometry)
            obj["Geometry Type"] = get_geometry_type_as_string(geometry)
            obj["Original Name"] = geometry.name
            if isinstance(geometry, pygdtf.GeometryReference):
                obj["Reference"] = str(geometry.geometry)
            if str(model.primitive_type) == "Pigtail":
                # This is a bit ugly because of PrimitiveType (in model) and not Geometry type (in geometry)
                obj["Geometry Type"] = "Pigtail"
            objs[cleanup_name(geometry)] = obj

            mb = obj.matrix_basis.copy()
            create_transform_property(obj)
            if hasattr(obj.data, "Transform"):
                obj.data.transform(mb)
            for c in obj.children:
                c.matrix_local = mb @ c.matrix_local
            obj.matrix_basis.identity()

        if hasattr(geometry, "geometries"):
            for sub_geometry in geometry.geometries:
                load_geometries(sub_geometry)

    def get_geometry_type_as_string(geometry):
        if isinstance(geometry, pygdtf.GeometryMediaServerCamera):
            return "Camera"
        if isinstance(geometry, pygdtf.GeometryBeam):
            return "Beam"
        if isinstance(geometry, pygdtf.GeometryLaser):
            return "Laser"
        if isinstance(geometry, pygdtf.GeometryAxis):
            return "Axis"
        if isinstance(geometry, pygdtf.GeometryReference):
            geometry = pygdtf.utils.get_geometry_by_name(profile, geometry.geometry)
            return get_geometry_type_as_string(geometry)
        return "Normal"

    def create_camera(geometry):
        if not cleanup_name(geometry) in objs:
            return
        obj_child = objs[cleanup_name(geometry)]
        camera_data = bpy.data.cameras.new(name=f"{obj_child.name}")
        camera_object = bpy.data.objects.new("MediaCamera", camera_data)
        camera_object.hide_select = True
        camera_object.parent = obj_child
        camera_object.matrix_parent_inverse = obj_child.matrix_world.inverted()
        camera_object.rotation_euler[0] += math.radians(90)  # The media server camera-view points into the positive Y-direction (and Z-up).
        collection.objects.link(camera_object)

    def create_beam(geometry):
        default_factor = 1000
        data_lights = bpy.data.lights
        if cleanup_name(geometry) not in objs:
            return
        obj_child = objs[cleanup_name(geometry)]
        if "Beam" not in obj_child.name.lower():
            obj_child.name = "Beam"
        if not display_beams:  # Don't even create beam objects to save resources
            return
        if any(geometry.beam_type.value == x for x in ["None", "Glow"]):
            return

        obj_child.visible_shadow = False
        if f"Spot {obj_child.name}".split('.')[0] in data_lights:
            light_data = data_lights.get(f"Spot {obj_child.name}".split('.')[0])
        else:
            light_data = data_lights.new(f"Spot {obj_child.name}", "SPOT")
        light_data["Flux"] = geometry.luminous_flux
        light_data["Shutter"] = 0  # Here we will store values required for strobing
        light_data["Dimmer"] = 0
        light_data.energy = light_data["Flux"]  # set by default to full brightness for devices without dimmer
        light_data.diffuse_factor = max((default_factor / light_data.energy), 1.0)
        light_data.specular_factor = max(((default_factor * 2) / light_data.energy), 1.0)
        light_data.use_custom_distance = True
        light_data.cutoff_distance = 23
        light_data.spot_blend = calculate_spot_blend(geometry)
        light_data.spot_size = math.radians(geometry.beam_angle)
        light_data.shadow_soft_size = geometry.beam_radius * 0.1
        light_data["Beam Radius"] = geometry.beam_radius  # save original beam size
        light_data["Gobo Size"] = True
        # This allows the user to set this if wanted to prevent beam rendering differences
        light_data.shadow_buffer_clip_start = 0.0001
        light_object = bpy.data.objects.new("Spot", light_data)
        light_object.hide_select = True
        light_object.parent = obj_child
        obj_child.matrix_parent_inverse = light_object.matrix_world.inverted()
        collection.objects.link(light_object)

        gobo_radius = 2.2 * 0.01 * math.tan(math.radians(geometry.beam_angle / 2))
        goboGeometry = SimpleNamespace(name=f"Gobo {geometry}", length=gobo_radius, width=gobo_radius,
                                       height=0, primitive_type="Plane", beam_radius=geometry.beam_radius)

        if has_gobos:
            create_gobo(geometry, goboGeometry)

    def create_laser(geometry):
        if cleanup_name(geometry) not in objs:
            return
        obj_child = objs[cleanup_name(geometry)]
        if "Laser" not in obj_child.name.lower():
            obj_child.name = f"Laser {obj_child.name}"
        obj_child.visible_shadow = False
        obj_child.rotation_mode = "XYZ"
        obj_child["Diameter"] = geometry.beam_diameter

    def create_gobo(geometry, goboGeometry):
        obj = load_blender_primitive(goboGeometry)
        obj["Geometry Type"] = "Gobo"
        obj["Beam Radius"] = goboGeometry.beam_radius
        obj.dimensions = (goboGeometry.length, goboGeometry.width, 0)
        obj.name = goboGeometry.name
        objs[cleanup_name(goboGeometry)] = obj
        obj.location[2] += -0.01
        constraint_child_to_parent(geometry, goboGeometry)

    def calculate_spot_blend(geometry):
        """Return spot_blend value based on beam_type, maybe in the future
        we can calculate different value based on beam/field angle...?"""
        beam_type = geometry.beam_type.value
        if any(beam_type == x for x in ["Wash", "Fresnel", "PC"]):
            return 1.0
        return 0.0

    def add_child_position(geometry):
        """Add a child position"""
        obj_child = objs[cleanup_name(geometry)]
        obj_child.matrix_local = mathutils.Matrix(geometry.position.matrix)

    def constraint_child_to_parent(parent_geometry, child_geometry):
        if not cleanup_name(parent_geometry) in objs:
            return
        obj_parent = objs[cleanup_name(parent_geometry)]
        if not cleanup_name(child_geometry) in objs:
            return
        obj_child = objs[cleanup_name(child_geometry)]
        obj_child.parent = obj_parent
        obj_child.matrix_parent_inverse = obj_parent.matrix_world.inverted()

    def update_geometry(geometry):
        """Recursively update objects position, rotation and scale
        and define parent/child constraints. References are new
        sub-trees that must be processed and their root marked."""

        if not isinstance(geometry, pygdtf.GeometryReference):
            # geometry reference will have different geometry
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

            # apply position of the reference
            add_child_position(reference)

            # apply position of the referring geometry
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
                        constraint_child_to_parent(reference, child_geometry)  # parent, child
                        update_geometry(child_geometry)
            return

        if hasattr(geometry, "geometries"):
            if len(geometry.geometries) > 0:
                for child_geometry in geometry.geometries:
                    constraint_child_to_parent(geometry, child_geometry)  # parent, child
                    update_geometry(child_geometry)

    load_geometries(root_geometry)
    update_geometry(root_geometry)

    # Add target for manipulating fixture
    if add_target:
        target = bpy.data.objects.new("Target", None)
        collection.objects.link(target)
        target.empty_display_size = 0.4
        target.empty_display_type = "PLAIN_AXES"
        target.location = (0, 0, -1)

    def get_root():
        for obj in objs.values():
            if obj.get("Root Geometry", False):
                return obj

    def get_axis(attribute):
        for obj in objs.values():
            for channel in dmx_channels_flattened:
                if attribute == channel["id"] and channel["geometry"] == obj.get("Original Name", "None"):
                    return obj
            for channel in virtual_channels:
                if attribute == channel["id"] and channel["geometry"] == obj.get("Original Name", "None"):
                    return obj

    # This could be moved to the processing up higher,but for now, it's easier here
    head = get_axis("Tilt")
    if head:
        head["Feature Type"] = "Tilt"
    yoke = get_axis("Pan")
    if yoke:
        yoke["Feature Type"] = "Pan"
    base = get_root()

    # If the root has a child with Pan, create Z rotation constraint
    if add_target:
        if yoke is not None:
            for name, obj in objs.items():
                if yoke.name == obj.name:
                    if add_target:
                        constraint = obj.constraints.new("LOCKED_TRACK")
                        constraint.target = target
                        constraint.lock_axis = "LOCK_Z"
                    break

    # Track head to the target
    if add_target:
        if head is not None:
            constraint = head.constraints.new("TRACK_TO")
            constraint.target = target
        else:
            # make sure simple par fixtures can be controlled via Target
            constraint = base.constraints.new("TRACK_TO")
            constraint.target = target

    # 2D thumbnail planning symbol
    obj = load_2d(profile)
    if obj is not None:
        # should probably always show it "on top"
        obj["2D Symbol"] = "all"
        objs["2D Symbol"] = obj
        obj.show_in_front = True
        obj.active_material.grease_pencil.show_stroke = True
        obj.data.pixel_factor = 2

        # add constraints
        constraint_copyLocation = obj.constraints.new(type="COPY_LOCATION")
        constraint_copyRotation = obj.constraints.new(type="COPY_ROTATION")
        constraint_copyLocation.target = base
        constraint_copyRotation.target = base
        constraint_copyRotation.use_z = True
        constraint_copyRotation.use_x = False
        constraint_copyRotation.use_y = False

    # Link objects to collection
    for name, obj in objs.items():
        collection.objects.link(obj)

    return collection


def get_fixture_models(profile, name, dmx_mode, display_beams, add_target):
    collections = bpy.data.collections
    if profile == None:
        return None
    if name in collections:
        print("Getting collection from cache: %s" % name)
        return collections[name]
    else:
        new_collection = build_collection(profile, name, dmx_mode, display_beams, add_target)
        return new_collection


def get_root_model(model_collection):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        if obj.get("Root Geometry", False):
            return obj


def get_tilt(model_collection, channels):
    if model_collection is None:
        return None
    for obj in model_collection.objects:
        for channel in channels:
            if "Tilt" == channel.get('id') and channel.get('geometry') == obj.get("Original Name", "None"):
                return obj


def fixture_build(context, filename, mscale, name, focus_point, collect, fixture, target=True, beams=True, cones=False):
    position = mathutils.Matrix.Translation((0, 0, 1)).transposed()
    fixture_id = create_fixture_name(name)
    data_collect = bpy.data.collections
    object_data = bpy.data.objects
    uid = str(pyuid.uuid4())
    color = (1.0, 1.0, 1.0)
    channels = []
    mode = None

    if fixture:
        uid = fixture.uuid
        mode = fixture.gdtf_mode
        position = fixture.matrix.matrix
        gel_color = convert_color(fixture.color)
        color =  list(int((255/1)*i) for i in gel_color[:3])
        fixture_id = create_fixture_name(fixture.fixture_id if fixture.fixture_id else name)

    # Import and deep copy Fixture Model Collection
    gdtf_profile = pygdtf.FixtureType(filename)
    model_collection = get_fixture_models(gdtf_profile, fixture_id, mode, beams, target)
    if model_collection:
        model_collection.name = fixture_id if fixture is None else name
        if collect and model_collection.name not in collect.children:
            collect.children.link(model_collection)

    # Build DMX channels cache
    if mode is not None:
        if not any(mode == md.name for md in gdtf_profile.dmx_modes):
            mode = gdtf_profile.dmx_modes[0].name
        dmx_channels = pygdtf.utils.get_dmx_channels(gdtf_profile, mode)
        # Merge all DMX breaks together
        channels += [channel for break_channels in dmx_channels for channel in break_channels]

        has_gobos = False
        # Build cache of virtual channels
        _virtual_channels = pygdtf.utils.get_virtual_channels(gdtf_profile, mode)
        for ch in _virtual_channels:
            if "Gobo" in ch["id"]:
                has_gobos = True

        # Get all gobos
        if has_gobos:
            gobo_material = bpy.data.materials.new('Gobos')
            principled_shader = PrincipledBSDFWrapper(gobo_material, is_readonly=False, use_nodes=True)
            gobo_seq = extract_gobos_as_sequence(gdtf_profile)
            if gobo_seq is not None:
                gobo = bpy.data.images.new('Gobo')

        if "Gobo" not in bpy.data.images:
            has_gobos = False # faulty GDTF might have channels but no images

    links = {}
    target_uid = str(pyuid.uuid4())
    base = get_root_model(model_collection)
    head = get_tilt(model_collection, channels)

    if model_collection:
        print("creating model collection: '%s'" % model_collection.name)
        for obj in model_collection.objects:
            links[obj.name] = obj
            obj['Original Name'] = obj.name
            if obj.get('Geometry Type') == 'Beam':
                obj['Feature Type'] = 'Color'
                if not len(obj.data.materials):
                    emit_material = bpy.data.materials.new(obj.name + ' ' + obj.get('Geometry Type'))
                    obj.data.materials.append(emit_material)
                emitter = obj.active_material
                emitter.shadow_method = "NONE"
                emit_shader = PrincipledBSDFWrapper(emitter, is_readonly=False, use_nodes=True)
                emit_shader.emission_strength = 1.0
                emit_shader.emission_color = color
            elif 'Target' in obj.name:
                obj['Geometry Type'] = 'Target'
                obj['Feature Type'] = 'Focus'
                obj['UUID'] = target_uid
                obj.location = (0, 0, -1)
                targetData[target_uid] = obj
            elif obj.parent and obj.type == 'LIGHT':
                obj['Feature Type'] = 'Gobo'
                obj['Target'] = target_uid
                obj.data
                obj.matrix_world = obj.matrix_world @ obj.parent.matrix_local.inverted()
            elif obj.get('Geometry Type') == 'Axis':
                obj['Target'] = target_uid
            elif obj.get('Root Geometry'):
                obj['Feature Type'] = 'Control'
                obj['Target'] = target_uid
                obj.name = fixture_id if fixture is None else name
            elif obj.get("2D Symbol", None) == "all":
                obj.name = "2D Symbol"

        # Reparent children
        for obj in model_collection.objects:
            for child in obj.children:
                if child.name in links:
                    links[child.name].parent = obj

        # Relink constraints
        for obj in model_collection.objects:
            for constraint in obj.constraints:
                constraint.target = targetData.get(obj.get('Target'))

        # Set position from MVR
        if position is not None:
            translation = mathutils.Matrix(position).transposed()
            for obj in model_collection.objects:
                if obj.get("Root Geometry", False):
                    obj.matrix_world = translation @ obj.matrix_world.copy()

        # Set target's position from MVR
        if focus_point is not None:
            for obj in model_collection.objects:
                if obj.get('Geometry Type') == 'Target':
                    obj.matrix_world = mathutils.Matrix(focus_point)

        # Setup emitter
        for obj in model_collection.objects:
            if "Beam" in obj.get("Geometry Type", ""):
                emitter = obj

            if "Gobo" in obj.get("Geometry Type", ""):
                gobo_material = bpy.data.materials.new(obj.name)
                obj.active_material = gobo_material
                obj.active_material.shadow_method = "CLIP"
                obj.active_material.blend_method = "BLEND"
                obj.material_slots[0].link = 'OBJECT' # ensure that each fixture has it's own material
                obj.material_slots[0].material = gobo_material

        # Link collection to DMX collection
        if collect is None:
            bpy.context.view_layer.layer_collection.collection.children.link(model_collection)

        # Set Pigtail visibility and Beam selection
        for obj in model_collection.objects:
            if "Pigtail" in obj.get("Geometry Type", ""):
                obj.hide_set(False)
                obj.hide_viewport = False
                obj.hide_render = False
            if obj.get("Root Geometry", False):
                continue
            if "Target" in obj.name:
                continue
            if obj.get("2D Symbol", None) == "all":
                obj.hide_set(True)
                obj.hide_viewport = True
                obj.hide_render = True
                continue

            obj.hide_select = False


def load_gdtf(context, filename, mscale, name, focus_point, collect, fixture=None, target=True, show_cone=False):
    fixture_build(context, filename, mscale, name, focus_point, collect, fixture)
    targetData.clear()


def load_prepare(context, filename, mscale, collect, use_gobo_search, use_target, use_beams, use_show_cone):
    name = Path(filename).stem
    focus_point = mathutils.Matrix.Identity(4)
    load_gdtf(context, filename, mscale, name, focus_point, collect)


def load_file(operator, context, files=None, directory="", filepath="", scale_objects=1.0, use_collection=False,
              use_gobo_search=True, use_target=True, use_beams=True, use_show_cone=False, global_matrix=None):

    context.window.cursor_set('WAIT')
    mscale = mathutils.Matrix.Scale(scale_objects, 4)
    if global_matrix is not None:
        mscale = global_matrix @ mscale

    default_layer = context.view_layer.active_layer_collection.collection
    for fl in files:
        collect = None
        if use_collection:
            collect = bpy.data.collections.new(Path(fl.name).stem)
            context.scene.collection.children.link(collect)
            context.view_layer.active_layer_collection = context.view_layer.layer_collection.children[collect.name]
        load_prepare(context, os.path.join(directory, fl.name), mscale, collect, use_gobo_search, use_target, use_beams, use_show_cone)

    active = context.view_layer.layer_collection.children.get(default_layer.name)
    if active is not None:
        context.view_layer.active_layer_collection = active

    context.window.cursor_set('DEFAULT')

    return {'FINISHED'}
