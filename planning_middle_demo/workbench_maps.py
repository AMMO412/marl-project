"""Read-only urban map catalogue used by the importer and packaged software."""

from interop.urban_maps import load_map, map_catalog as _catalog


def map_catalog():
    return _catalog()


def map_document(identifier):
    return load_map(identifier)
