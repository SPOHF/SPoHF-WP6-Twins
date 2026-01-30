# WP6 Digital Twins in the context of SPoHF


## Data flows

Desired situation

<script type="module">
    Array.from(document.getElementsByClassName("language-mermaid")).forEach(element => {
      element.classList.add("mermaid");
    });
    import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
    import elkLayouts from 'https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0/dist/mermaid-layout-elk.esm.min.mjs';
    mermaid.registerLayoutLoaders(elkLayouts);
    mermaid.initialize({ startOnLoad: true });
</script>

```mermaid
---
config:
  layout: elk
---
flowchart TD
    subgraph WP6 - Digital Twins
        subgraph red[Red Twin - Tomatoes]
            subgraph r_analytics[Analytics]
                a_predict[predictions]
                a_enrich[enrichments]
            end

            subgraph r_gui[User Interface]
                r_dashboard1[sensor dashboard]
                r_dashboard2[plant dashboard]
            end

            r_sync[sync service]

            subgraph r_data[Data engine]
                r_db[(data warehouse)]
                r_jobs[task runner]
            end

            r_sync ---> r_jobs

            r_jobs <--> r_db

            r_jobs <--> r_gui

            r_analytics <--> r_jobs

        end
        style red fill:red

        subgraph blue[Blue Twin - Blueberries]
            subgraph b_analytics[Analytics]
                b_predict[predictions]
                b_enrich[enrichments]
                b_wp3_classification[WP3 insect classification]
            end

            subgraph b_gui[User Interface]
                b_dashboard[sensor dashboard]

                b_wp3_ingestion[WP3 ingestion]
            end

            b_sync[sync service]

            subgraph b_data[Data engine]
                b_db[(Data Warehouse)]
                b_jobs[task runner]
            end

            b_sync ---> b_jobs

            b_jobs <--> b_db

            b_jobs <--> b_gui

            b_analytics <--> b_jobs
        end
        style blue fill:blue
    end

    subgraph appcomm[AppComm DataLake]
        ac_db[(db)]
        ac_api[API]

        ac_db ---> ac_api
    end

    subgraph sources[data sources]
        subgraph blue_source[Blueberry field]
            b_sensors[Greenhouse sensors]@{ shape: cloud}
            b_manual[Manual - logs, lab data]@{ shape: cloud}
            b_yellow_cards[Yellow cards]@{ shape: cloud}
        end
        style blue_source fill:blue

        subgraph red_sources[Tomato Greenhouse]
            r_sensors[Field sensors]@{ shape: cloud}
            r_manual[Manual - logs, lab data]@{ shape: cloud}
        end
        style red_sources fill:red
    end

    b_sensors ---> ac_db
    b_manual ---> ac_db

    r_sensors ---> ac_db
    r_manual ---> ac_db

    appcomm ---> b_sync
    appcomm ---> r_sync

    b_yellow_cards ---> b_wp3_ingestion

```

## Descriptions

There are two digital twins.
On a high level, what they share:
- similar overall design
  - so that parts (code, infrastructre) can be reused
- the data formats
- the fact that there is (a lot of) data, that we visualize over time (basic dashboard)

In behavior they are different:
- different user interfaces
- different type of analysis
- and, obviously - different plants (lifecycle, needs), environments (field vs greenhouse)

### Blue Twin

The blue(berry) twin approach is as following:
Different fertilization strategies are used in a field where other variables (e.g. irrigation) are kept the same. from where chemical analysis shows which one works the best.
This of course is a slow feedback cycle.

Based on which works the best, the goal of the twin is to find the correlations in the sensor data with the best fertilization strategy, to see if there is a faster feedback cycle from the sensors.

This ultimately helps prescribing actions to take over the year to get a more desirable harvest.

these actions include: irrigation, adding nutrients, pest control

### Red Twin

The red twin (tomato) is as following:
As tomatoes grow in greenhouses, the climate is controlled at large scale.

A setup is being made for measuring at different heights:
- light (PAR)
- temperature
- humidity
- fruit thickness

From here we can visualize and model the microclimate around a single plant and its growth.

This ultimately prescribe actions that lead to reduced costs without impacting the harvest.

these actions may include: leaf maintenance, heat control, light control and positioning and water control.


## Operations

Where does what run:

- Fontys
    - user interfaces
    - temporary steps towards desired sitation, waiting for dependencies
- ProcEvolution
    - (everything else)
    - data warehouse
    - analytics services


<!-- ## Work distribution

For now, roughly:

- Nochschule Niederrhein
    - data analysis, finding correlations

- ProcEvolution
    - data engine
    - makes analysis and synchronization tools available within their platform

- Fontys
    - dashboards (monitoring, predictive and prescriptive twin), access
        - model specific for the new lighting setup in the RED twin
    - operationalize WP3
    - prediction models -->
