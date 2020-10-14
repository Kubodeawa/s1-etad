"""Tools for easy access to Sentinel-1 Extended Timing Annotation Datasets.

This package provides a set of classes to open and access all elements,
data and meta-data, of the Sentinel-1 Extended Timing Annotation Datasets
(S1-ETAD).

Basic elements are:

* :class:`Sentinel1Etad`
* :class:`Sentinel1EtadSwath`
* :class:`Sentinel1EtadBurst`
"""

from .product import (
    Sentinel1Etad, Sentinel1EtadSwath, Sentinel1EtadBurst, ECorrectionType,
)

__version__ = '0.3.0.dev1'
