import enum

from geoalchemy2 import Geography
from sqlalchemy import Enum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


def geo_point() -> Geography:
    # spatial_index=False: indexes are declared explicitly in __table_args__
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)
