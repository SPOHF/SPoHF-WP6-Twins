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
        style red fill:#ee5858

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
        style blue fill:#464592
    end

    subgraph appcomm[AppComm DataLake]
        ac_db[(db)]
        ac_api[API]

        ac_db ---> ac_api
    end

    subgraph sources[data sources]
        subgraph blue_source[Blueberry field]
            b_sensors[Field sensors]@{ shape: cloud}
            b_manual[Manual - logs, lab data]@{ shape: cloud}
            b_yellow_cards[Yellow cards]@{ shape: cloud}
        end
        style blue_source fill:#464592

        subgraph red_sources[Tomato Greenhouse]
            r_sensors[Greenhouse sensors]@{ shape: cloud}
            r_manual[Manual - logs, lab data]@{ shape: cloud}
        end
        style red_sources fill:#ee5858
    end

    b_sensors ---> ac_db
    b_manual ---> ac_db

    r_sensors ---> ac_db
    r_manual ---> ac_db

    appcomm ---> b_sync
    appcomm ---> r_sync

    b_yellow_cards ---> b_wp3_ingestion

```



## Operations

Where does what run:

- Fontys
    - user interfaces
    - potentially: schedulers and definitions of workloads
    - temporary steps towards desired sitation, waiting for dependencies
- ProcEvolution
    - data warehouse
    - task loads, e.g. syncronization
    - analytics services


<!-- ## Work distribution

For now, roughly:

- Hochschule Niederrhein
    - data analysis, finding correlations

- ProcEvolution
    - data engine
    - makes analysis and synchronization tools available within their platform

- Fontys
    - dashboards (monitoring, predictive and prescriptive twin), access
        - model specific for the new lighting setup in the RED twin
    - operationalize WP3
    - prediction models -->
