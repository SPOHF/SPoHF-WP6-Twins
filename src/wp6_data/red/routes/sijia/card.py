"""The Sijia source section that appears on /status for admins.

Wired into ``TwinConfig.status_extras`` from `red/dashboard.py`. Produced by
the shared factory from the Sijia descriptor; returns "" for non-admins so
the section is invisible to them (unchanged behaviour).
"""

from wp6_data.red.sijia.source import SIJIA
from wp6_data.shared.manual_ingest import make_card

render_sijia_card = make_card(SIJIA)
