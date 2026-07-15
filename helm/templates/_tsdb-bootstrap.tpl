{{/*
Renders the Helm-hook Job that provisions one twin's database on the shared
TimescaleDB instance.

Ownership split: the shared chart (helm/shared) owns the TimescaleDB *instance*;
each twin owns the *database* it writes to. So this Job lives in the twin chart
and only materialises in that twin's ArgoCD Application.

Params (dict):
  root      the root context ($)
  twin      twin key, e.g. "red" / "blue" — names the Job
  database  database to create
  role      optional login role to own the database. Omit and the database is
            owned by the postgres superuser, which is where blue still is —
            see issues/045-blue-connects-as-postgres-superuser.md.
  roleSecret / roleSecretKey  where the role's password lives (required with `role`)
*/}}
{{- define "wp6-data.tsdbBootstrapJob" -}}
{{- $root := .root -}}
{{- $sharedSecret := $root.Values.secrets.existingSecret | default (printf "%s-secrets" $root.Chart.Name) -}}
{{- $image := $root.Values.tsdbBootstrap.image | default $root.Values.tsdbBootstrap.defaultImage -}}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ $root.Chart.Name }}-{{ .twin }}-tsdb-bootstrap
  labels:
    app.kubernetes.io/name: {{ $root.Chart.Name }}-{{ .twin }}-tsdb-bootstrap
  annotations:
    # PRE-sync, not post: this Job creates the database the dashboard connects to.
    # As a post-install/post-upgrade (ArgoCD PostSync) hook it would only run after
    # the sync's resources are Healthy — but the dashboard Deployment can never go
    # Healthy until this database exists, so PostSync deadlocked and the Job never
    # ran (observed on the fresh v2 bootstrap). PreSync runs it first; it already
    # waits for TimescaleDB via pg_isready, so ordering against the shared app is safe.
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 4
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ $root.Chart.Name }}-{{ .twin }}-tsdb-bootstrap
    spec:
      restartPolicy: OnFailure
      containers:
        - name: bootstrap
          image: {{ $image | quote }}
          env:
            - name: PGHOST
              value: {{ $root.Values.tsdbBootstrap.tsdbHost | quote }}
            - name: PGPORT
              value: {{ $root.Values.tsdbBootstrap.tsdbPort | quote }}
            - name: PGUSER
              value: "postgres"
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ $sharedSecret }}
                  key: tsdb-password
            {{- if .role }}
            - name: ROLE_PASS
              valueFrom:
                secretKeyRef:
                  name: {{ .roleSecret }}
                  key: {{ .roleSecretKey }}
            {{- end }}
          command:
            - /bin/sh
            - -c
            - |
              set -e
              echo "waiting for postgres at $PGHOST:$PGPORT..."
              until pg_isready -h "$PGHOST" -p "$PGPORT" -U postgres -d postgres -t 5; do
                sleep 2
              done
              echo "postgres is ready; bootstrapping {{ .database }}"
              psql -d postgres -v ON_ERROR_STOP=1 {{ if .role }}-v role_pass="$ROLE_PASS" {{ end }}<<'SQL'
              {{- if .role }}
              SELECT format('CREATE ROLE {{ .role }} WITH LOGIN PASSWORD %L', :'role_pass')
              WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{{ .role }}')\gexec

              SELECT 'CREATE DATABASE {{ .database }} OWNER {{ .role }}'
              WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{{ .database }}')\gexec
              {{- else }}
              SELECT 'CREATE DATABASE {{ .database }}'
              WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{{ .database }}')\gexec
              {{- end }}
              SQL
              # A database created from template1 inherits timescaledb on this
              # image, but say so explicitly rather than relying on that.
              psql -d {{ .database }} -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS timescaledb"
              echo "bootstrap complete"
{{- end -}}
