"""Blue-twin Explore card extensions."""

from wp6_data.blue.routes.monitor._treatment import TREATMENT_COLORS

_FALLBACK = "#94a3b8"


def _badge(code: str) -> str:
    color = TREATMENT_COLORS.get(code, _FALLBACK)
    return (
        f'<span style="display:inline-block;width:10px;height:10px;'
        f'border-radius:50%;background:{color};margin-right:6px;'
        f'vertical-align:middle;"></span>{code}'
    )


def render_fertilization_strategies_tab() -> str:
    """Static reference table showing the field layout and fertilisation strategies."""
    rows = f"""
        <tr>
          <td><strong>Row 1</strong></td>
          <td>{_badge("Org1")}</td>
          <td>—</td>
          <td>Organic 1 (DCM)</td>
          <td>Organic 1 (DCM)</td>
        </tr>
        <tr>
          <td><strong>Row 2</strong></td>
          <td>{_badge("Org2")}</td>
          <td>—</td>
          <td>Organic 2 (Den Ouden)</td>
          <td>Organic 2 (Den Ouden)</td>
        </tr>
        <tr>
          <td><strong>Row 3</strong></td>
          <td>{_badge("Std")}</td>
          <td>—</td>
          <td>Standard (unspecified)</td>
          <td>Standard (unspecified)</td>
        </tr>
        <tr>
          <td rowspan="3"><strong>Row 4</strong><br><small>Calcium strategy</small></td>
          <td>{_badge("Ca")}</td>
          <td>V_Ca_G_Ca</td>
          <td>Std + Ca</td>
          <td>Std + Ca</td>
        </tr>
        <tr>
          <td>{_badge("V_CA")}</td>
          <td>V_Ca_G_-</td>
          <td>Std + Ca</td>
          <td>Std (no addition)</td>
        </tr>
        <tr>
          <td>{_badge("V_CA_G_BrPK")}</td>
          <td>V_Ca_G_BrPK</td>
          <td>Std + Ca</td>
          <td>Std + BrPK</td>
        </tr>
        <tr>
          <td rowspan="3"><strong>Row 5</strong><br><small>Potassium strategy</small></td>
          <td>{_badge("K")}</td>
          <td>V_K_G_K</td>
          <td>Std + K</td>
          <td>Std + K</td>
        </tr>
        <tr>
          <td>{_badge("G_K")}</td>
          <td>V_-_G_K</td>
          <td>Std (no addition)</td>
          <td>Std + K</td>
        </tr>
        <tr>
          <td>{_badge("V_K_G_CaBrP")}</td>
          <td>V_K_G_CaBrP</td>
          <td>Std + K</td>
          <td>Std + BrPCa</td>
        </tr>
    """
    return f"""
        <p>
          Field layout with five rows. Rows 4 and 5 are each divided into three
          sub-plots with different fertilisation sub-strategies. The
          <em>sub-strategy</em> column shows how V (Vegetative) and G (Generative)
          growing phases are treated; "<strong>—</strong>" means no supplemental
          addition in that phase.
        </p>
        <div style="overflow-x:auto">
          <table>
            <thead>
              <tr>
                <th>Field row</th>
                <th>Treatment code</th>
                <th>Sub-strategy</th>
                <th>Vegetative (V) phase</th>
                <th>Generative (G) phase</th>
              </tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
    """
