"""OTC list adapters. Two generic mechanisms (a header-mapped tabular
list, CSV or HTML table; an ArcGIS FeatureServer/MapServer layer) and three
state adapters, each configured from a search-index evidence ledger and
gated (no state is activated; each refuses to run before the first
request): Alabama (ADOR state-held land), Arkansas (COSL Post Auction Sales
List), Louisiana (East Baton Rouge adjudicated property) and Arizona (Maricopa
State CP liens - a LIENS & CERTIFICATES source). No live
configuration for any Texas government source - see `tabular.TX_CANDIDATES`
for why each is a candidate and not an adapter."""

from .alabama import AlabamaFieldMap, AlabamaSourceConfig
from .arcgis import ArcGisFieldMap, ArcGisLayerConfig, ArcGisResult, fetch_all
from .arizona import ArizonaCpSourceConfig
from .arkansas import ArkansasSourceConfig
from .louisiana import LouisianaSourceConfig
from .tabular import TX_CANDIDATES, ColumnMap, TabularConfig, TabularListAdapter

__all__ = ["AlabamaFieldMap", "AlabamaSourceConfig", "ArcGisFieldMap", "ArcGisLayerConfig", "ArcGisResult", "ArizonaCpSourceConfig", "ArkansasSourceConfig",
           "LouisianaSourceConfig", "TX_CANDIDATES", "ColumnMap", "TabularConfig", "TabularListAdapter", "fetch_all"]
