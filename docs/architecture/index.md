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


## C4 architecture (current state)

The diagrams below describe the current implementation, reverse-engineered from
the codebase. They follow the [C4 model](https://c4model.com/): each level zooms
one step deeper, from the system in its environment down to the components inside
the codebase and how they're deployed.

The source files live in [`diagrams/`](diagrams/) and are validated by rendering
them with [`mmdc`](https://github.com/mermaid-js/mermaid-cli). Each `.mmd` file is
the single source of truth — the embedded copies below are kept in sync manually.

### System context (C4 L1)

How WP6 fits into its environment: who uses it and which external systems it
integrates with. Note that growers/researchers also *upload* manual measurement
files (lab long-data, insect counts, Sijia phenotyping), greenhouse readings
come from the Fontys GreenTechLab platform (MySQL), and Open-Meteo powers both
Red's DLI and Blue's GDD analytics.

```mermaid
---
title: "WP6 Digital Twins - System Context (C4 Level 1)"
---
graph TB
    %% SSOT — also embedded in docs/architecture/index.md.
    %% Edit this file first, then mirror into index.md.
    classDef person fill:#08427b,color:#fff,stroke:none
    classDef system fill:#1168bd,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none

    grower["Grower / Researcher
    [Person]
    Views sensor data, DLI/GDD analytics
    and growth forecasts; uploads manual
    lab/measurement files"]:::person

    visitor["Public Visitor
    [Person]
    Explores the platform demo
    (Grey twin only)"]:::person

    wp6["WP6 Digital Twins
    [Software System]
    Blue (blueberry), Red (tomato)
    and Grey (synthetic demo) dashboards
    on a shared FastAPI platform"]:::system

    spohf["SPoHF Backoffice
    [External System]
    AppComm DataLake — aggregates
    sensor data from field devices"]:::external

    yookr["Yookr API
    [External System]
    Direct sensor data access
    for blueberry field devices"]:::external

    openmeteo["Open-Meteo
    [External System]
    Weather forecast and history;
    powers Red DLI and Blue GDD"]:::external

    oidc["OIDC Provider
    [External System]
    Identity provider for
    authenticated dashboards"]:::external

    greentechlab["Fontys GreenTechLab
    [External System]
    LoRaWAN platform storing
    greenhouse sensor tables (Red)"]:::external

    greenhouse["Greenhouse Sensors
    [External System]
    PAR, temperature, humidity
    sensors at Vitarom"]:::external

    field["Field Sensors
    [External System]
    Soil, climate, and nutrient
    sensors at Compass Agro"]:::external

    grower -->|"Views Blue/Red dashboards\n(HTTPS, OIDC)"| wp6
    grower -->|"Uploads manual files\n(CSV/XLSX, admin-gated)"| wp6
    visitor -->|"Views Grey demo\n(HTTPS, public)"| wp6
    wp6 -->|"Authenticates user\n(OIDC)"| oidc
    wp6 -->|"Fetches sensor readings\n(REST API)"| spohf
    wp6 -->|"Fetches sensor readings\n(REST API)"| yookr
    wp6 -->|"Fetches greenhouse readings\n(MySQL)"| greentechlab
    wp6 -->|"Fetches weather data\n(REST API)"| openmeteo
    greenhouse -->|"Publishes readings"| greentechlab
    field -->|"Publishes readings"| spohf
    field -->|"Publishes readings"| yookr
```

### Container view (C4 L2)

The deployable units — three dashboards (Blue, Red, Grey), the sync and export
CronJobs, and the data stores — and how they communicate. Note that DLI is part
of the Red dashboard process (not a separate container) and the shared platform
is shown as a library that every dashboard is built from. The TimescaleDB
instance is now **shared**, holding one database per twin (`wp6_blue`,
`wp6_red`); Red reads its *live* greenhouse feed from MySQL but persists manual
uploads and risk episodes in `wp6_red`. Each authenticated dashboard also mounts
a PersistentVolumeClaim for raw uploaded files.

```mermaid
---
title: "WP6 Digital Twins - Container Diagram (C4 Level 2)"
---
graph TB
    %% SSOT — also embedded in docs/architecture/index.md.
    %% Edit this file first, then mirror into index.md.
    classDef person fill:#08427b,color:#fff,stroke:none
    classDef container fill:#1168bd,color:#fff,stroke:none
    classDef database fill:#1168bd,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none
    classDef cronjob fill:#438dd5,color:#fff,stroke:none
    classDef shared fill:#0a3d62,color:#fff,stroke:none
    classDef storage fill:#3c6382,color:#fff,stroke:none

    grower["Grower / Researcher
    [Person]"]:::person
    visitor["Public Visitor
    [Person]"]:::person

    subgraph wp6["WP6 Digital Twins"]
        direction TB

        subgraph platform["Shared Platform (wp6_data.shared)"]
            app_factory["App Factory
            [Library: FastAPI + Jinja2]
            Builds a dashboard from a
            TwinConfig (provider, theme,
            metadata, extra routers); hosts
            the generic manual-ingest pipeline"]:::shared
        end

        subgraph blue_twin["Blue Twin (Blueberries)"]
            blue_dash["Blue Dashboard
            [Container: FastAPI]
            Chart compare, GDD tracker,
            soil forecast, manual uploads,
            and SPoHF / Yookr source toggle"]:::container
            blue_uploads[("Blue Manual Uploads
            [PVC]
            Raw insect / long-data /
            fertigation files")]:::storage
        end

        subgraph red_twin["Red Twin (Tomatoes)"]
            red_dash["Red Dashboard
            [Container: FastAPI]
            DLI analysis + ML forecast
            (trained on startup), wire
            risk views, Sijia uploads"]:::container
            red_uploads[("Red Manual Uploads
            [PVC]
            Raw Sijia measurement
            files")]:::storage
        end

        subgraph grey_twin["Grey Twin (Demo)"]
            grey_dash["Grey Dashboard
            [Container: FastAPI]
            Public demo with synthetic
            in-memory sensor data —
            exercises the shared platform"]:::container
        end

        subgraph data_engine["Data Engine"]
            sync_job["wp6-data Sync Job
            [Container: Python CronJob]
            python -m wp6_data:
            SPoHF + Yookr ingest
            (sequential, every 15 min)"]:::cronjob

            blue_export["Blue CSV Export Job
            [Container: Python CronJob]
            Nightly export of Blue
            sensor data to CSV"]:::cronjob

            red_export["Red CSV Export Job
            [Container: Python CronJob]
            Nightly export of Red
            sensor tables to CSV"]:::cronjob
        end

        subgraph tsdb_inst["Shared TimescaleDB [PostgreSQL 17]"]
            tsdb_blue[("wp6_blue
            [Database]
            readings, sync_metadata,
            daily_coverage, manual_uploads")]:::database
            tsdb_red[("wp6_red
            [Database]
            readings, risk_episodes,
            risk_state, manual_uploads")]:::database
        end
    end

    mysqldb[("MySQL
    [External Database: MySQL 8]
    Fontys GreenTechLab —
    greenhouse sensor tables
    (Red live feed)")]:::external

    spohf["SPoHF Backoffice
    [External: REST API]"]:::external
    yookr["Yookr API
    [External: REST API]"]:::external
    openmeteo["Open-Meteo
    [External: REST API]"]:::external
    oidc["OIDC Provider
    [External: HTTPS]"]:::external

    %% User flows
    grower -->|"HTTPS\n(OIDC)"| blue_dash
    grower -->|"HTTPS\n(OIDC)"| red_dash
    visitor -->|"HTTPS\n(public)"| grey_dash

    %% Auth flow
    blue_dash -.->|"OIDC"| oidc
    red_dash -.->|"OIDC"| oidc

    %% Platform composition (each dashboard IS a configured app_factory)
    blue_dash -.->|"built from"| app_factory
    red_dash -.->|"built from"| app_factory
    grey_dash -.->|"built from"| app_factory

    %% Blue data access
    blue_dash -->|"Async queries\n(psycopg3 pool)\nproject filter:\nspohf-datalake | yookr"| tsdb_blue
    blue_dash -->|"Daily weather\n(HTTPS, GDD)"| openmeteo
    blue_dash -->|"Stores uploads"| blue_uploads

    %% Red data access (live feed from MySQL, manual + risk in TSDB)
    red_dash -->|"Async queries\n(aiomysql, live feed)"| mysqldb
    red_dash -->|"Manual + risk\n(psycopg3 pool)"| tsdb_red
    red_dash -->|"Daily forecast\n(HTTPS, DLI)"| openmeteo
    red_dash -->|"Stores uploads"| red_uploads
    %% grey_dash has no datastore (in-memory)

    %% Sync job (single process runs both ingests sequentially)
    sync_job -->|"Paginated fetch\n(httpx)"| spohf
    sync_job -->|"Per-sensor fetch\n(httpx)"| yookr
    sync_job -->|"Batch upsert"| tsdb_blue

    %% Export jobs
    blue_export -->|"Read readings"| tsdb_blue
    red_export -->|"Read sensor tables"| mysqldb
```

### Component view (C4 L3)

Inside the codebase. The shared platform (`wp6_data.shared`) defines a
`SensorDataProvider` Protocol; each twin (`wp6_data.blue`, `wp6_data.red`,
`wp6_data.grey`) provides an implementation plus a `TwinConfig`, and
`create_app(config)` assembles the FastAPI dashboard. Twin-specific features
(DLI and the wire **risk engine** for Red, GDD and soil forecasting for Blue)
attach as `extra_routers`. Two cross-cutting subsystems now live in the shared
platform: a generic **manual-ingest pipeline** (`ManualSource` descriptor +
transactional `ManualIngestService` + content-addressed `UploadStorage`) that
Blue (insects, long-data, fertigation) and Red (Sijia) plug their CSV/XLSX
sources into, and a twin-agnostic `OpenMeteoClient` shared by Red's DLI model
and Blue's GDD tracker. Red's provider is **federated** — it reads the live
greenhouse feed from MySQL and wire/manual data from the `wp6_red` database.

```mermaid
---
title: "WP6 Digital Twins - Component Diagram (C4 Level 3)"
---
graph TB
    %% SSOT — also embedded in docs/architecture/index.md.
    %% Edit this file first, then mirror into index.md.
    classDef component fill:#438dd5,color:#fff,stroke:none
    classDef platform fill:#0a3d62,color:#fff,stroke:none
    classDef protocol fill:#8e44ad,color:#fff,stroke:none
    classDef database fill:#1168bd,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none
    classDef storage fill:#3c6382,color:#fff,stroke:none

    %% ── External systems ──
    spohf_api["SPoHF REST API
    [External]"]:::external
    yookr_api["Yookr REST API
    [External]"]:::external
    openmeteo_api["Open-Meteo API
    [External]"]:::external
    oidc_provider["OIDC Provider
    [External]"]:::external
    tsdb_blue[("TimescaleDB wp6_blue
    readings | sync_metadata
    daily_coverage | manual_uploads")]:::database
    tsdb_red[("TimescaleDB wp6_red
    readings | risk_episodes
    risk_state | manual_uploads")]:::database
    mysqldb[("MySQL
    GTL greenhouse + wire tables
    (Red live feed)")]:::database
    uploads_pvc[("Manual Uploads
    [PVC, content-addressed]")]:::storage

    %% ────────────────────────────────────────────────
    %% Shared Platform — the heart of the application
    %% ────────────────────────────────────────────────
    subgraph platform["Shared Platform (wp6_data.shared)"]
        app_factory["create_app
        [Component]
        Builds FastAPI app from
        TwinConfig: routes, auth,
        provider dispatch, lifespan"]:::platform

        twin_config["TwinConfig
        [Dataclass]
        twin_id, title, theme, data_sources,
        metadata, extra_routers, hero_cards,
        status_extras, explore_extra_tabs,
        require_auth, lifespan hooks"]:::platform

        provider_protocol["SensorDataProvider
        [Protocol]
        fetch_data, fetch_available_sensors,
        fetch_device_data, fetch_manual_metadata,
        fetch_sync_metrics, fetch_daily_coverage"]:::protocol

        shared_routes["Shared Routes
        [Component]
        home | charts | dashboard_page
        status | api | health"]:::platform

        auth_mod["Auth (OIDC)
        [Component]
        startup_oidc, make_auth_router,
        verify_session_user/admin"]:::platform

        metadata_mod["MetadataRegistry
        [Component]
        Loads metadata.yaml:
        device + sensor labels, units"]:::platform

        subgraph manual_ingest["Manual Ingest (shared.manual_ingest)"]
            mi_source["ManualSource
            [Descriptor]
            slug, categorical_value,
            parse, validate, replace_scope"]:::platform
            mi_service["ManualIngestService
            [Component]
            Transactional validate/apply:
            delete prior + audit + insert"]:::platform
            mi_routes["make_source_router / make_card
            [Component]
            Admin-gated preview | apply | history"]:::platform
            mi_cli["run_ingest (CLI)
            [Component]
            Headless validate + apply"]:::platform
        end

        upload_storage["UploadStorage
        [Component]
        SHA256-addressed file store,
        keeps latest 2 per source"]:::platform

        weather["OpenMeteoClient
        [Component]
        Twin-agnostic forecast +
        archive (DLI and GDD)"]:::platform

        misc_shared["templates | aggregation
        charts | export | time
        sensor_summary | compat
        [Components]"]:::platform
    end

    %% ────────────────────────────────────────────────
    %% Blue Twin
    %% ────────────────────────────────────────────────
    subgraph blue_layer["Blue Twin (wp6_data.blue)"]
        blue_config["dashboard.config
        [TwinConfig instance]
        2 DataSources: spohf-datalake
        and yookr"]:::component
        blue_provider["BlueSensorProvider
        [Component, x2]
        TSDB-backed, project-filtered
        (one per DataSource)"]:::component
        blue_deps["deps / tsdb / yookr
        [Component]
        wp6_blue queries, schema,
        project-scoped fetch"]:::component
        blue_routes_x["Blue Extra Routes
        [Components]
        ops | api | charts | monitor
        mixed_views | broken_sensors"]:::component
        blue_gdd["gdd
        [Component]
        Growing Degree Days from
        Open-Meteo modeled weather"]:::component
        blue_soil["soil_forecaster
        [Component]
        Ridge soil moisture/temp
        7d + 30d forecast"]:::component
        blue_manual["manual sources
        [ManualSource x3]
        insects | long_data |
        fertigation_events"]:::component
        blue_metadata[("blue/metadata.yaml")]:::component
    end

    %% ────────────────────────────────────────────────
    %% Red Twin
    %% ────────────────────────────────────────────────
    subgraph red_layer["Red Twin (wp6_data.red)"]
        red_config["dashboard.config
        [TwinConfig instance]
        1 DataSource: mysql (live feed)"]:::component
        red_provider["RedSensorProvider
        [Component]
        Federated: MySQL + wire
        + wp6_red readings"]:::component
        red_db["MySQLConnection
        [Component]
        aiomysql pool, sensor +
        wire table mapping"]:::component
        red_tsdb["tsdb
        [Component]
        wp6_red schema + queries
        (readings, risk tables)"]:::component
        red_routes_x["Red Extra Routes
        [Components]
        browse | charts | multi_height
        dli | dli_model | sijia"]:::component
        red_sijia["sijia
        [ManualSource]
        Excel phenotyping upload
        (source='sijia')"]:::component
        red_metadata[("red/metadata.yaml")]:::component

        subgraph dli_layer["DLI sub-package (red.dli)"]
            dli_model["TwoStageLightModel
            [Component]
            Two-stage Ridge regression
            persisted to .pkl"]:::component
            dli_calc["calculator
            [Component]
            PAR→DLI integral,
            lamp contribution"]:::component
            dli_lamp["lamp / schedule
            [Component]
            Lamp profile + hourly
            schedule inference"]:::component
            dli_agg["aggregation
            [Component]
            Daily features,
            cyclic day-of-year"]:::component
        end

        subgraph risk_layer["Risk engine (red.risk)"]
            risk_engine["engine / metrics / episodes
            [Component]
            Pure: VPD, wet-hours, CO2
            depletion, canopy DLI episodes"]:::component
            risk_service["service / cli
            [Component]
            Fetch wire → evaluate
            → persist range"]:::component
            risk_store["store / config
            [Component]
            risk_episodes + risk_state
            upsert; thresholds from yaml"]:::component
        end
    end

    %% ────────────────────────────────────────────────
    %% Grey Twin (demo / platform smoke test)
    %% ────────────────────────────────────────────────
    subgraph grey_layer["Grey Twin (wp6_data.grey)"]
        grey_config["dashboard.config
        [TwinConfig instance]
        require_auth=False,
        in-memory data source"]:::component
        grey_provider["GreySensorProvider
        [Component]
        Sine-wave synthetic data,
        no DB"]:::component
        grey_metadata[("grey/metadata.yaml")]:::component
    end

    %% ────────────────────────────────────────────────
    %% Sync layer (independent CronJob processes)
    %% ────────────────────────────────────────────────
    subgraph sync_layer["Sync Orchestration (wp6_data.sync)"]
        spohf_orch["SyncOrchestrator
        [Component]
        Windowed sync with
        early-stop on duplicates"]:::component
        yookr_orch["YookrSyncOrchestrator
        [Component]
        Per-sensor ingestion
        via SensorRegistry (CSV)"]:::component
    end

    %% ────────────────────────────────────────────────
    %% API client + DB layers
    %% ────────────────────────────────────────────────
    subgraph api_layer["API Clients (wp6_data.api, wp6_data.yookr)"]
        spohf_client["SpoHFClient
        [Component]
        Paginated async fetcher
        with timestamp windowing"]:::component
        yookr_client["YookrClient
        [Component]
        Session auth, per-sensor
        monthly-windowed fetcher"]:::component
    end

    subgraph db_layer["Database Layer (wp6_data.db)"]
        pool["ConnectionPool
        [Component]
        Async psycopg3 pool
        (singleton, lazy init)"]:::component
        queries["Queries
        [Component]
        upsert_readings,
        upsert_daily_coverage"]:::component
        schema["Schema
        [Component]
        Idempotent DDL:
        hypertables + indexes"]:::component
    end

    config["Settings (Pydantic)
    [Component]
    WP6_* env vars for all
    connections and behavior"]:::component

    %% ────────────────────────────────────────────────
    %% Connections — platform composition
    %% ────────────────────────────────────────────────
    twin_config -->|"data_sources[*].provider"| provider_protocol
    app_factory -->|"reads"| twin_config
    app_factory -->|"mounts"| shared_routes
    app_factory -->|"wires"| auth_mod
    app_factory -->|"loads"| metadata_mod
    shared_routes -->|"depends on"| provider_protocol
    auth_mod -->|"OIDC flow"| oidc_provider
    misc_shared -.->|"used by"| shared_routes

    %% Manual ingest wiring
    mi_routes -->|"uses"| mi_service
    mi_cli -->|"uses"| mi_service
    mi_service -->|"dispatch on"| mi_source
    mi_service -->|"persist files"| upload_storage
    mi_service -->|"insert readings"| queries
    upload_storage --> uploads_pvc
    weather -->|"forecast/archive"| openmeteo_api

    %% Per-twin: each is a TwinConfig + provider implementing the protocol
    blue_config -->|"built by"| app_factory
    red_config -->|"built by"| app_factory
    grey_config -->|"built by"| app_factory

    blue_provider -.->|"implements"| provider_protocol
    red_provider -.->|"implements"| provider_protocol
    grey_provider -.->|"implements"| provider_protocol

    %% Blue wiring
    blue_config -->|"data_sources"| blue_provider
    blue_config -->|"extra_routers"| blue_routes_x
    blue_config -->|"metadata"| blue_metadata
    blue_provider --> blue_deps
    blue_routes_x --> blue_gdd
    blue_routes_x --> blue_soil
    blue_routes_x --> blue_deps
    blue_gdd -->|"weather"| weather
    blue_manual -->|"register via"| mi_routes
    blue_deps --> pool

    %% Red wiring
    red_config -->|"data_sources"| red_provider
    red_config -->|"extra_routers"| red_routes_x
    red_config -->|"metadata"| red_metadata
    red_provider --> red_db
    red_provider --> red_tsdb
    red_routes_x --> dli_model
    red_routes_x --> red_db
    red_routes_x -->|"risk views"| risk_service
    red_sijia -->|"register via"| mi_routes
    dli_model --> dli_calc
    dli_model --> dli_lamp
    dli_model --> dli_agg
    dli_model -->|"weather"| weather
    risk_service --> risk_engine
    risk_service --> risk_store
    risk_service -->|"wire readings"| red_db
    risk_store --> red_tsdb
    red_tsdb --> pool

    %% Grey wiring
    grey_config -->|"data_sources"| grey_provider
    grey_config -->|"metadata"| grey_metadata

    %% Data layer
    pool --> tsdb_blue
    pool --> tsdb_red
    schema --> pool
    red_db --> mysqldb

    %% Sync (separate processes — not the dashboards)
    spohf_orch --> spohf_client
    spohf_orch --> queries
    yookr_orch --> yookr_client
    yookr_orch --> queries
    queries --> pool
    spohf_client -->|"GET /api/v1/data"| spohf_api
    yookr_client -->|"POST /login\nGET /sensor/read"| yookr_api

    %% Config flows everywhere
    config -.->|"configures"| spohf_orch
    config -.->|"configures"| yookr_orch
    config -.->|"configures"| pool
    config -.->|"configures"| blue_config
    config -.->|"configures"| red_config
```

### Deployment view

Current state: every workload runs in the Fontys Kubernetes cluster. The only
external datastore is the Fontys GreenTechLab MySQL (Red's live greenhouse
feed). The in-cluster TimescaleDB StatefulSet is shared by both twins, holding a
`wp6_blue` and a `wp6_red` database; a Helm post-install/upgrade hook Job
provisions the `wp6_red` role and database. Each authenticated dashboard mounts a
manual-uploads PVC, and connection details are split across three secrets (a
shared one for OIDC + API tokens + the TSDB superuser password, plus per-twin
secrets for each database URL and MySQL/role credentials). The desired split with
ProcEvolution hosting the data warehouse and sync jobs is described in
*Operations* above; the diagram intentionally reflects what's deployed today, not
the target architecture.

```mermaid
---
title: "WP6 Digital Twins - Deployment Diagram"
---
graph TB
    %% SSOT — also embedded in docs/architecture/index.md.
    %% Edit this file first, then mirror into index.md.
    %% Current state: everything runs in the Fontys K8s cluster.
    %% (The desired-state split with ProcEvolution is described in
    %% the "Operations" section of architecture/index.md.)
    classDef k8s fill:#326ce5,color:#fff,stroke:none
    classDef pod fill:#438dd5,color:#fff,stroke:none
    classDef storage fill:#1168bd,color:#fff,stroke:none
    classDef ingress fill:#08427b,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none
    classDef cronjob fill:#6b9ed6,color:#fff,stroke:none
    classDef job fill:#7b6bd6,color:#fff,stroke:none

    %% ── External actors and services ──
    user["Grower / Researcher
    [Browser]"]:::external
    visitor["Public Visitor
    [Browser]"]:::external
    spohf_ext["backoffice.spohf.com"]:::external
    yookr_ext["api.yookr.org"]:::external
    openmeteo_ext["api.open-meteo.com"]:::external
    oidc_ext["OIDC Provider"]:::external
    mysql_ext[("Fontys GTL MySQL 8
    [External Managed DB]
    Greenhouse + wire sensor tables
    (85.215.61.145:3306)")]:::external

    %% ── Fontys IDP cluster, namespace spohf-system ──
    subgraph fontys["Fontys IDP K8s Cluster — namespace: spohf-system"]
        direction TB

        blue_ingress["Ingress
        wp6-blue.spohf.fontysvenlo.dev"]:::ingress
        red_ingress["Ingress
        wp6-red.spohf.fontysvenlo.dev"]:::ingress
        grey_ingress["Ingress
        wp6-grey.spohf.fontysvenlo.dev"]:::ingress

        blue_deploy["Blue Dashboard
        [Deployment: 1 replica]
        FastAPI + Uvicorn"]:::pod
        red_deploy["Red Dashboard
        [Deployment: 1 replica]
        FastAPI + Uvicorn"]:::pod
        grey_deploy["Grey Dashboard
        [Deployment: 1 replica]
        FastAPI + Uvicorn
        (no DB, no auth)"]:::pod

        sync_cron["wp6-data Sync
        [CronJob: */15 * * * *]
        python -m wp6_data:
        SPoHF + Yookr (sequential)
        (uses wp6-data-blue image)"]:::cronjob

        blue_export_cron["Blue CSV Export
        [CronJob: 0 2 * * *]
        Nightly Blue export"]:::cronjob
        red_export_cron["Red CSV Export
        [CronJob: 0 2 * * *]
        Nightly Red sensor export"]:::cronjob

        red_bootstrap["Red TSDB Bootstrap
        [Job: Helm post-install/upgrade hook]
        Creates wp6_red role + database
        in the shared TimescaleDB"]:::job

        subgraph tsdb_sts["TimescaleDB [StatefulSet: 1 replica] — PostgreSQL 17 + TimescaleDB"]
            db_blue[("wp6_blue
            [Database]")]:::storage
            db_red[("wp6_red
            [Database]")]:::storage
        end

        tsdb_pvc[("PersistentVolumeClaim
        timescaledb-data")]:::storage

        blue_uploads_pvc[("PVC
        blue-manual-uploads")]:::storage
        red_uploads_pvc[("PVC
        red-manual-uploads")]:::storage

        secret_main["wp6-data-secrets
        [Secret, externally provisioned]
        OIDC client/session,
        TSDB superuser password,
        SPoHF + Yookr API tokens"]:::k8s

        secret_blue["wp6-data-blue-secrets
        [Secret, externally provisioned]
        tsdb-url (wp6_blue)"]:::k8s

        secret_red["wp6-data-red-secrets
        [Secret, externally provisioned]
        MySQL password,
        tsdb-url (wp6_red),
        tsdb-red-password"]:::k8s
    end

    %% ── User → Ingress → Deployment ──
    user -->|"HTTPS"| blue_ingress
    user -->|"HTTPS"| red_ingress
    visitor -->|"HTTPS"| grey_ingress
    blue_ingress --> blue_deploy
    red_ingress --> red_deploy
    grey_ingress --> grey_deploy

    %% ── Auth ──
    blue_deploy -.->|"OIDC"| oidc_ext
    red_deploy -.->|"OIDC"| oidc_ext

    %% ── Dashboard data access ──
    blue_deploy -->|"psycopg3\nport 5432"| db_blue
    blue_deploy -->|"HTTPS (GDD)"| openmeteo_ext
    red_deploy -->|"aiomysql\nport 3306 (live feed)"| mysql_ext
    red_deploy -->|"psycopg3\nport 5432 (manual + risk)"| db_red
    red_deploy -->|"HTTPS (DLI)"| openmeteo_ext

    %% ── Storage ──
    tsdb_sts --- tsdb_pvc
    blue_deploy --- blue_uploads_pvc
    red_deploy --- red_uploads_pvc

    %% ── Bootstrap hook provisions the red database ──
    red_bootstrap -->|"psql\nport 5432"| tsdb_sts

    %% ── Sync job (single process, runs both ingests sequentially) ──
    sync_cron -->|"HTTPS"| spohf_ext
    sync_cron -->|"HTTPS"| yookr_ext
    sync_cron -->|"port 5432"| db_blue

    %% ── Export jobs ──
    blue_export_cron -->|"port 5432"| db_blue
    red_export_cron -->|"port 3306"| mysql_ext

    %% ── Secret mounts ──
    %% Shared secret: OIDC + API tokens + TSDB superuser (bootstrap)
    secret_main -.->|"mounted"| blue_deploy
    secret_main -.->|"mounted"| red_deploy
    secret_main -.->|"mounted"| sync_cron
    secret_main -.->|"mounted"| red_bootstrap
    %% Blue secret: wp6_blue connection URL (dashboard, sync, export)
    secret_blue -.->|"mounted"| blue_deploy
    secret_blue -.->|"mounted"| sync_cron
    secret_blue -.->|"mounted"| blue_export_cron
    %% Red secret: MySQL password + wp6_red URL + role password
    secret_red -.->|"mounted"| red_deploy
    secret_red -.->|"mounted"| red_export_cron
    secret_red -.->|"mounted"| red_bootstrap
    %% grey_deploy needs no secrets — it's stateless and public
```


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
