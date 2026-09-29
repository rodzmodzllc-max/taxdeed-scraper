"""OTC list adapters. One generic mechanism today (a header-mapped tabular
list, CSV or HTML table) and no live configuration for any Texas
government source - see `tabular.TX_CANDIDATES` for why each one is a
candidate and not an adapter."""

from .tabular import TX_CANDIDATES, ColumnMap, TabularConfig, TabularListAdapter

__all__ = ["TX_CANDIDATES", "ColumnMap", "TabularConfig", "TabularListAdapter"]
