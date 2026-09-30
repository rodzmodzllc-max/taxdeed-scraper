"""OTC list adapters. Two generic mechanisms (a header-mapped tabular
list, CSV or HTML table; an ArcGIS FeatureServer/MapServer layer), one
state adapter FOUNDATION (Alabama: contract, gates and fixture parsing,
no transport - see its header), and no live configuration for any
government source - see `tabular.TX_CANDIDATES` for why each Texas one is
a candidate and not an adapter, and the arcgis module's header for why no
layer is configured."""

from .alabama import AlabamaFieldMap, AlabamaSourceConfig
from .arcgis import ArcGisFieldMap, ArcGisLayerConfig, ArcGisResult, fetch_all
from .tabular import TX_CANDIDATES, ColumnMap, TabularConfig, TabularListAdapter

__all__ = ["AlabamaFieldMap", "AlabamaSourceConfig", "ArcGisFieldMap", "ArcGisLayerConfig", "ArcGisResult",
           "TX_CANDIDATES", "ColumnMap", "TabularConfig", "TabularListAdapter", "fetch_all"]
