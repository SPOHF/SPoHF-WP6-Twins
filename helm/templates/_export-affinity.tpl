{{/*
Pins a twin's export CronJob pod to whichever node runs that twin's dashboard.

The exports PVC is ReadWriteOnce on a block StorageClass (cloudstack-csi is the
only class on the cluster — there is no RWX option). A block volume attaches to
exactly one node, and the dashboard Deployment holds that attachment for its
whole lifetime. The export CronJob mounts the same PVC to write into it, so
unless it is scheduled onto the dashboard's node the kubelet can never attach
the volume: the pod sits Pending on

  Warning  FailedAttachVolume  Multi-Attach error for volume "pvc-…"
                               Volume is already used by pod(s) …-dashboard-…

and 30 minutes later activeDeadlineSeconds reaps the Job as DeadlineExceeded.
That is what silently broke both twins' nightly exports for 23 days after the
v2 cluster migration — the old cluster had few enough nodes that the scheduler
happened to co-locate them; venlodp has seven, so it effectively never did.

Note that mounting the volume readOnly in the dashboard (as it does) is not a
way out: RWO exclusivity is enforced at the volume-attachment layer, not the
mount layer.

Co-locating is safe because two pods on the *same* node share one attachment
happily. It is `required…IgnoredDuringExecution`, so if the dashboard is
rescheduled the next export run simply follows it to the new node.

Params (dict):
  root  the root context ($)
  twin  twin key, e.g. "red" / "blue" — selects that twin's dashboard pods
*/}}
{{- define "wp6-data.exportPodAffinity" -}}
podAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app.kubernetes.io/name: {{ .root.Chart.Name }}-{{ .twin }}-dashboard
      topologyKey: kubernetes.io/hostname
{{- end -}}
