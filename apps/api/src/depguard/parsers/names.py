from packaging.utils import canonicalize_name


def normalize_pypi_name(name: str) -> str:
    """PEP 503: lowercase; runs of '-', '_', '.' become one '-' (Django_Filter -> django-filter)."""
    return str(canonicalize_name(name))


def pypi_key(name: str, version: str) -> str:
    # Python lockfiles can hold two versions of one package (one per Python version),
    # so the name alone isn't unique.
    return f"{normalize_pypi_name(name)}=={version}"
