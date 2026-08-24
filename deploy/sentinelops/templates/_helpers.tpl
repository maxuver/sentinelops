{{- define "sentinelops.labels" -}}
app.kubernetes.io/part-of: sentinelops
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
