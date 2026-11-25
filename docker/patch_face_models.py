"""Use the standard library to load the installed face model resources."""

from importlib.metadata import distribution


models = distribution("face-recognition-models")
module = models.locate_file("face_recognition_models/__init__.py")
source = module.read_text(encoding="utf-8")
old_import = "from pkg_resources import resource_filename"
if models.version != "0.3.0" or source.count(old_import) != 1:
    raise SystemExit("Review the face model resource compatibility fix.")

replacement = """from importlib.resources import files


def resource_filename(package, relative_path):
    return str(files(package).joinpath(relative_path))"""
module.write_text(source.replace(old_import, replacement), encoding="utf-8")
