{{/*
Environment for the shared S3-compatible object store.

One bucket serves every twin and every artifact kind; the separation is by key
prefix, not by bucket (buckets are not directories, and CloudStack caps how
many a project may hold). The prefix is chosen in code —
`red/deps.py:EXPORT_PREFIX`, `blue/deps.py:EXPORT_PREFIX` — so nothing here
needs to know which twin it is rendering for.

`objectStore.bucket` is REQUIRED. There is no on-disk fallback: the
application refuses to start without it (wp6_data.shared.blob.make_store), so
the chart fails at render rather than deploying a pod that will crash-loop.
An earlier version fell back to a directory, and that silence was the bug --
the export job wrote to disk while the dashboard read an empty bucket.

Credentials are issued by CloudStack **per project account, not per bucket**,
so these keys can also read, write and delete in the other buckets in the
`developer-platform` project (classroom-backup, openproject-attachments). Real
per-bucket isolation would need MinIO users created outside CloudStack.

Params (dict):
  root  the root context ($)
*/}}
{{- define "wp6-data.objectStoreEnv" -}}
{{- $os := .root.Values.objectStore -}}
- name: WP6_S3_BUCKET
  value: {{ required "objectStore.bucket is required - the dashboards and export jobs refuse to start without it" $os.bucket | quote }}
- name: WP6_S3_ENDPOINT_URL
  value: {{ required "objectStore.endpointUrl is required" $os.endpointUrl | quote }}
- name: WP6_S3_REGION
  value: {{ $os.region | quote }}
{{- if $os.caBundle }}
# botocore ships its own vendored CA bundle, which carries the older Hellenic
# 2015 roots but NOT the "HARICA TLS RSA Root CA 2021" that anchors the store's
# certificate chain — every call fails with "unable to get local issuer
# certificate" without an override. Unset, the application falls back to
# certifi, which does carry that root; set this to an OS bundle path only if
# you need to override that.
- name: WP6_S3_CA_BUNDLE
  value: {{ $os.caBundle | quote }}
{{- end }}
- name: WP6_S3_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ $os.secrets.existingSecret | default (printf "%s-object-store" .root.Chart.Name) }}
      key: {{ $os.secrets.accessKeyIdKey }}
- name: WP6_S3_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $os.secrets.existingSecret | default (printf "%s-object-store" .root.Chart.Name) }}
      key: {{ $os.secrets.secretAccessKeyKey }}
{{- end -}}
